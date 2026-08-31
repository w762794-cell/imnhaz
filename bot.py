import os
import re
import logging
import tempfile
import asyncio
import subprocess

import srt
import edge_tts
from pydub import AudioSegment
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]

# Edge-TTS Khmer neural voices
VOICES = {
    "male": "km-KH-PisethNeural",
    "female": "km-KH-SreymomNeural",
}

# In-memory map: chat_id -> path of the uploaded .srt file
user_files: dict[int, str] = {}

MAX_TEMPO = 2.2   # cap on how much we may speed up speech to fit a slot
MIN_TEMPO = 0.75  # cap on how much we may slow speech down to fill a slot


# --------------------------------------------------------------------------
# Telegram handlers
# --------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "សួស្តី! 👋\n\n"
        "ខ្ញុំជា Bot បំលែងឯកសារ SRT ទៅជាសំឡេងនិយាយ (Text-to-Speech)។\n\n"
        "📌 របៀបប្រើ៖\n"
        "1️⃣ ផ្ញើឯកសារ .srt មកខ្ញុំ\n"
        "2️⃣ ជ្រើសរើសសំឡេង ប្រុស (Piseth) ឬ ស្រី (Sreymom)\n"
        "3️⃣ រង់ចាំ ខ្ញុំនឹងផ្ញើឯកសារសំឡេង (.mp3) ត្រឡប់មកវិញ ដែលត្រូវតាមពេលវេលានៃ SRT"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc.file_name.lower().endswith(".srt"):
        await update.message.reply_text("⚠️ សូមផ្ញើតែឯកសារ .srt ប៉ុណ្ណោះ។")
        return

    status_msg = await update.message.reply_text("⬇️ កំពុងទាញយកឯកសារ...")

    tmp_dir = tempfile.mkdtemp()
    srt_path = os.path.join(tmp_dir, doc.file_name)

    tg_file = await doc.get_file()
    await tg_file.download_to_drive(srt_path)

    user_files[update.effective_chat.id] = srt_path

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👨 ប្រុស (Piseth)", callback_data="male"),
                InlineKeyboardButton("👩 ស្រី (Sreymom)", callback_data="female"),
            ]
        ]
    )
    await status_msg.edit_text("✅ ទទួលឯកសារបានហើយ។ សូមជ្រើសរើសសំឡេង៖", reply_markup=keyboard)


async def handle_voice_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    voice_key = query.data
    voice_name = VOICES.get(voice_key)

    srt_path = user_files.get(chat_id)
    if not srt_path or not os.path.exists(srt_path):
        await query.edit_message_text("⚠️ រកមិនឃើញឯកសារ SRT ទេ សូមផ្ញើម្តងទៀត។")
        return

    label = "ប្រុស (Piseth)" if voice_key == "male" else "ស្រី (Sreymom)"
    await query.edit_message_text(f"🎙️ កំពុងបំលែងជាសំឡេង {label}...\nសូមរង់ចាំបន្តិច ⏳")

    try:
        output_path = await build_audio_from_srt(srt_path, voice_name)
        with open(output_path, "rb") as audio_file:
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                filename="voice_output.mp3",
                caption=f"✅ បំលែងបានជោគជ័យ! (សំឡេង៖ {label})",
            )
    except Exception as e:  # noqa: BLE001
        logger.exception("Error while building audio")
        await context.bot.send_message(chat_id=chat_id, text=f"❌ មានបញ្ហា៖ {e}")
    finally:
        user_files.pop(chat_id, None)


# --------------------------------------------------------------------------
# SRT -> timed audio logic
# --------------------------------------------------------------------------

def parse_srt(path: str):
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    return list(srt.parse(content))


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _atempo_chain(factor: float) -> str:
    """Build an ffmpeg 'atempo' filter chain for an arbitrary factor.
    A single atempo filter only accepts 0.5-2.0, so factors outside that
    range are split into multiple chained filters."""
    filters = []
    remaining = factor
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    filters.append(f"atempo={remaining:.6f}")
    return ",".join(filters)


def time_stretch(seg: AudioSegment, factor: float) -> AudioSegment:
    """Speed up or slow down `seg` by `factor` while keeping the same pitch/
    voice character, using ffmpeg's atempo filter (no chipmunk/child-voice
    effect like a naive frame-rate resample would cause)."""
    if abs(factor - 1.0) < 0.02:
        return seg  # difference is negligible, skip processing

    tmp_dir = tempfile.mkdtemp()
    in_path = os.path.join(tmp_dir, "in.wav")
    out_path = os.path.join(tmp_dir, "out.wav")
    seg.export(in_path, format="wav")

    filter_chain = _atempo_chain(factor)
    subprocess.run(
        ["ffmpeg", "-y", "-i", in_path, "-filter:a", filter_chain, out_path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return AudioSegment.from_file(out_path, format="wav")


async def tts_to_file(text: str, voice: str, out_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


async def build_audio_from_srt(srt_path: str, voice: str) -> str:
    subs = parse_srt(srt_path)
    tmp_dir = tempfile.mkdtemp()

    # First pass: generate (and tempo-fit) every line's audio, and remember
    # the exact SRT start time it belongs at. We don't place anything on a
    # timeline yet.
    segments = []  # list of (start_ms, AudioSegment)
    total_duration_ms = 0

    for i, sub in enumerate(subs):
        start_ms = int(sub.start.total_seconds() * 1000)
        end_ms = int(sub.end.total_seconds() * 1000)
        slot_duration_ms = max(end_ms - start_ms, 200)

        clean_text = strip_tags(sub.content)

        if clean_text:
            seg_path = os.path.join(tmp_dir, f"seg_{i}.mp3")
            await tts_to_file(clean_text, voice, seg_path)
            seg_audio = AudioSegment.from_file(seg_path)

            # Nudge speech tempo so its duration lines up with its subtitle
            # slot as closely as possible, without changing pitch/voice.
            if slot_duration_ms > 0 and len(seg_audio) > 0:
                factor = len(seg_audio) / slot_duration_ms
                factor = max(MIN_TEMPO, min(factor, MAX_TEMPO))
                seg_audio = time_stretch(seg_audio, factor)
        else:
            seg_audio = AudioSegment.silent(duration=slot_duration_ms)

        segments.append((start_ms, seg_audio))
        total_duration_ms = max(total_duration_ms, start_ms + len(seg_audio), end_ms)

    # Second pass: build a silent canvas spanning the whole file and overlay
    # each line at its exact SRT start time. Placing lines by absolute
    # position (instead of concatenating them one after another) means a
    # line that runs slightly long can never push every later line out of
    # sync -- each line's start time always matches the SRT exactly.
    timeline = AudioSegment.silent(duration=total_duration_ms)
    for start_ms, seg_audio in segments:
        timeline = timeline.overlay(seg_audio, position=start_ms)

    output_path = os.path.join(tmp_dir, "output.mp3")
    timeline.export(output_path, format="mp3", bitrate="192k")
    return output_path



# --------------------------------------------------------------------------
# App entrypoint (webhook on Render, polling locally)
# --------------------------------------------------------------------------

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(CallbackQueryHandler(handle_voice_choice))

    port = int(os.environ.get("PORT", 8080))
    render_url = os.environ.get("RENDER_EXTERNAL_URL")  # auto-set by Render

    if render_url:
        logger.info("Starting in WEBHOOK mode on %s", render_url)
        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=f"{render_url}/{BOT_TOKEN}",
        )
    else:
        logger.info("Starting in POLLING mode (local dev)")
        app.run_polling()


if __name__ == "__main__":
    main()
