import os
import re
import logging
import tempfile
import asyncio

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

MAX_SPEEDUP = 1.6  # cap how much we speed up audio to fit a slot


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


def speed_up(seg: AudioSegment, factor: float) -> AudioSegment:
    """Speed up an AudioSegment by `factor` while keeping the same frame rate,
    used so long TTS lines still roughly fit inside their subtitle slot."""
    new_frame_rate = int(seg.frame_rate * factor)
    sped = seg._spawn(seg.raw_data, overrides={"frame_rate": new_frame_rate})
    return sped.set_frame_rate(seg.frame_rate)


async def tts_to_file(text: str, voice: str, out_path: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(out_path)


async def build_audio_from_srt(srt_path: str, voice: str) -> str:
    subs = parse_srt(srt_path)
    tmp_dir = tempfile.mkdtemp()

    timeline = AudioSegment.silent(duration=0)
    current_ms = 0

    for i, sub in enumerate(subs):
        start_ms = int(sub.start.total_seconds() * 1000)
        end_ms = int(sub.end.total_seconds() * 1000)
        slot_duration_ms = max(end_ms - start_ms, 200)

        # Insert silence so this line starts exactly at its SRT timestamp
        if start_ms > current_ms:
            timeline += AudioSegment.silent(duration=start_ms - current_ms)
            current_ms = start_ms
        elif start_ms < current_ms:
            # Previous line overran into this one's start time; just continue,
            # we cannot move time backwards.
            pass

        clean_text = strip_tags(sub.content)

        if clean_text:
            seg_path = os.path.join(tmp_dir, f"seg_{i}.mp3")
            await tts_to_file(clean_text, voice, seg_path)
            seg_audio = AudioSegment.from_file(seg_path)

            # If the generated speech is longer than its subtitle slot,
            # speed it up a bit so timing stays close to the SRT.
            if len(seg_audio) > slot_duration_ms > 0:
                factor = min(len(seg_audio) / slot_duration_ms, MAX_SPEEDUP)
                seg_audio = speed_up(seg_audio, factor)
        else:
            seg_audio = AudioSegment.silent(duration=slot_duration_ms)

        timeline += seg_audio
        current_ms += len(seg_audio)

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
