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

MAX_RATE_BOOST_PCT = 35  # cap on how much faster we ask the TTS engine itself
                          # to speak (native, natural-sounding), applied only
                          # when a line would actually run into the next
                          # line's start

TTS_MAX_ATTEMPTS = 4          # retries if edge-tts drops/truncates audio
TTS_RETRY_DELAY_SEC = 1.2     # pause before retrying a failed/short segment
TTS_INTER_REQUEST_DELAY_SEC = 0.25  # small pause between consecutive lines
MIN_MS_PER_WORD = 120         # rough floor used to detect truncated audio


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
        output_path, failed_lines = await build_audio_from_srt(srt_path, voice_name)
        with open(output_path, "rb") as audio_file:
            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                filename="voice_output.mp3",
                caption=f"✅ បំលែងបានជោគជ័យ! (សំឡេង៖ {label})",
            )

        if failed_lines:
            lines_text = "\n".join(
                f"• បន្ទាត់ #{n} ({ts}): {preview}..."
                for n, ts, preview in failed_lines[:20]
            )
            more = f"\n... និងច្រើនទៀត ({len(failed_lines) - 20})" if len(failed_lines) > 20 else ""
            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ បន្ទាត់ចំនួន {len(failed_lines)} មិនអាចបំលែងជាសំឡេងបានទេ "
                    f"(ដាក់ជាស្ងាត់ជំនួសវិញ)៖\n{lines_text}{more}"
                ),
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
    # ignore_errors=True skips a malformed block instead of aborting parsing
    # (or silently dropping) every subtitle that comes after it -- common
    # with machine-translated .srt files that have small formatting quirks.
    subs = list(srt.parse(content, ignore_errors=True))
    logger.info("Parsed %d subtitle entries from %s", len(subs), path)
    return subs


def strip_tags(text: str) -> str:
    # Only remove well-known subtitle formatting tags (italic/bold/underline/
    # font/color), instead of a generic "<...>" pattern -- a generic pattern
    # will eat every character (including whole lines of real dialogue)
    # between a stray, unclosed "<" and the next ">" anywhere later in the
    # text, which is common in machine-translated .srt files.
    text = re.sub(r"</?\s*(i|b|u|font)[^>]*>", "", text, flags=re.IGNORECASE)
    # Also strip ASS/SSA-style override tags, e.g. {\an8}, {\i1}
    text = re.sub(r"\{\\[^}]*\}", "", text)
    # Multi-line subtitle blocks (two speakers, wrapped lines, etc.) should
    # read as one continuous phrase -- a raw newline sent to edge-tts can
    # sometimes cause it to only speak part of the text.
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


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


async def tts_to_file(text: str, voice: str, out_path: str, rate: str = "+0%"):
    """Synthesize `text` to `out_path`, retrying if edge-tts drops the
    connection or returns audio that looks truncated (too short for the
    amount of text given). `rate` (e.g. "+20%") asks the TTS engine to
    natively speak faster/slower, which sounds far more natural than
    mechanically time-stretching the audio afterward."""
    word_count = max(len(text.split()), 1)
    expected_min_ms = word_count * MIN_MS_PER_WORD

    last_err = None
    for attempt in range(1, TTS_MAX_ATTEMPTS + 1):
        try:
            communicate = edge_tts.Communicate(text, voice, rate=rate)
            await communicate.save(out_path)

            if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
                duration_ms = len(AudioSegment.from_file(out_path))
                # Audio noticeably shorter than expected usually means
                # edge-tts cut off partway through -- treat as a failure
                # and retry rather than silently keeping the clipped line.
                if duration_ms >= expected_min_ms * 0.5:
                    return
                last_err = RuntimeError(
                    f"suspiciously short audio ({duration_ms}ms for "
                    f"{word_count} words, expected >= {expected_min_ms * 0.5:.0f}ms)"
                )
            else:
                last_err = RuntimeError("edge-tts returned an empty file")
        except Exception as e:  # noqa: BLE001
            last_err = e

        logger.warning(
            "TTS attempt %d/%d failed for %r: %s",
            attempt, TTS_MAX_ATTEMPTS, text[:60], last_err,
        )
        if attempt < TTS_MAX_ATTEMPTS:
            await asyncio.sleep(TTS_RETRY_DELAY_SEC)

    raise RuntimeError(f"TTS failed after {TTS_MAX_ATTEMPTS} attempts: {last_err}")


async def build_audio_from_srt(srt_path: str, voice: str):
    subs = parse_srt(srt_path)
    tmp_dir = tempfile.mkdtemp()

    # Pass 1: generate every line's raw audio (no tempo changes yet) and
    # remember its exact SRT start/end time.
    raw_items = []  # dicts: start_ms, end_ms, audio
    failed_lines = []  # (line_number, start_timestamp, text_preview)

    for i, sub in enumerate(subs):
        start_ms = int(sub.start.total_seconds() * 1000)
        end_ms = int(sub.end.total_seconds() * 1000)
        slot_duration_ms = max(end_ms - start_ms, 200)

        clean_text = strip_tags(sub.content)

        if clean_text:
            seg_path = os.path.join(tmp_dir, f"seg_{i}.mp3")
            try:
                await tts_to_file(clean_text, voice, seg_path)
                seg_audio = AudioSegment.from_file(seg_path)
            except Exception as e:  # noqa: BLE001
                # One line's TTS permanently failing (after all retries)
                # should not throw away every other line in the file --
                # fall back to silence for this slot and keep going, but
                # remember it so we can tell the user exactly which line
                # was skipped.
                logger.error("Giving up on line %d (%r): %s", i + 1, clean_text[:60], e)
                failed_lines.append((i + 1, str(sub.start), clean_text[:60]))
                seg_audio = AudioSegment.silent(duration=slot_duration_ms)

            # Small pause between requests -- helps avoid the TTS service
            # rate-limiting/dropping back-to-back connections on long files.
            await asyncio.sleep(TTS_INTER_REQUEST_DELAY_SEC)
        else:
            seg_audio = AudioSegment.silent(duration=slot_duration_ms)

        raw_items.append({
            "start_ms": start_ms,
            "end_ms": end_ms,
            "audio": seg_audio,
            "text": clean_text,
        })

    # Pass 2: only speed up a line if it would otherwise actually overlap
    # the NEXT line's start -- not just because it runs past its own
    # nominal end time. Subtitles usually have a small natural gap before
    # the next line begins, so most overruns fit there for free with zero
    # change, keeping the speaking pace natural and consistent. When a line
    # genuinely needs to be faster, we ask edge-tts to *natively* speak it
    # faster (rate=+N%) instead of mechanically time-stretching the
    # recording -- this sounds like a person speaking briskly rather than a
    # sped-up tape, which is what makes tools like Voicertool sound natural.
    segments = []  # (start_ms, AudioSegment)
    total_duration_ms = 0

    for i, item in enumerate(raw_items):
        start_ms = item["start_ms"]
        seg_audio = item["audio"]

        if i + 1 < len(raw_items):
            available_ms = raw_items[i + 1]["start_ms"] - start_ms
        else:
            available_ms = None  # last line -- nothing after it to bump into

        if available_ms and available_ms > 0 and len(seg_audio) > available_ms and item["text"]:
            factor = len(seg_audio) / available_ms
            pct = min(int(round((factor - 1.0) * 100)), MAX_RATE_BOOST_PCT)

            if pct > 0:
                try:
                    fast_path = os.path.join(tmp_dir, f"seg_{i}_fast.mp3")
                    await tts_to_file(item["text"], voice, fast_path, rate=f"+{pct}%")
                    seg_audio = AudioSegment.from_file(fast_path)
                    await asyncio.sleep(TTS_INTER_REQUEST_DELAY_SEC)
                except Exception as e:  # noqa: BLE001
                    # If asking the engine to re-speak faster fails for some
                    # reason, fall back to a mechanical stretch rather than
                    # leaving the line overlapping even more than necessary.
                    logger.warning("Rate-boost regen failed for line %d: %s", i + 1, e)
                    seg_audio = time_stretch(seg_audio, factor)

        segments.append((start_ms, seg_audio))
        total_duration_ms = max(total_duration_ms, start_ms + len(seg_audio), item["end_ms"])

    # Pass 3: build a silent canvas spanning the whole file and overlay
    # each line at its exact SRT start time. Placing lines by absolute
    # position (instead of concatenating them one after another) means a
    # line that runs slightly long can never push every later line out of
    # sync -- each line's start time always matches the SRT exactly.
    timeline = AudioSegment.silent(duration=total_duration_ms)
    for start_ms, seg_audio in segments:
        timeline = timeline.overlay(seg_audio, position=start_ms)

    output_path = os.path.join(tmp_dir, "output.mp3")
    timeline.export(output_path, format="mp3", bitrate="192k")
    return output_path, failed_lines




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
