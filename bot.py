import os
import io
import logging
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pysrt
import edge_tts
from pydub import AudioSegment
from pydub.effects import speedup as pydub_speedup
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    MessageHandler,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# httpx logs the full request URL (including the bot token) at INFO level.
# Silence it so the token never ends up in Render's logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Free Microsoft neural voices (same catalog Edge browser's "Read aloud" uses).
# No API key or Azure account needed.
VOICE_MALE = "km-KH-PisethNeural"
VOICE_FEMALE = "km-KH-SreymomNeural"

# Callback data values for the inline buttons
CB_MALE = "voice_male"
CB_FEMALE = "voice_female"
CB_AUTO = "voice_auto"

# If a synthesized line is longer than its subtitle slot, speed it up to fit —
# but never distort it more than this factor.
MAX_SPEEDUP = 2.5
# Only bother speeding up if the overrun is meaningfully large.
SPEEDUP_THRESHOLD = 1.03


def strip_marker(text: str):
    """
    If a line starts with an explicit marker, return (forced_voice, clean_text).
    Otherwise return (None, original_text) so the caller's chosen voice applies.
      [M] / male: / ប្រុស:  -> forces Piseth (male)
      [F] / female: / ស្រី: -> forces Sreymom (female)
    """
    stripped = text.strip()
    lower = stripped.lower()

    if stripped.startswith("[M]") or lower.startswith("male:") or stripped.startswith("ប្រុស:"):
        clean = stripped.split(":", 1)[-1].split("]", 1)[-1].strip()
        return VOICE_MALE, clean
    if stripped.startswith("[F]") or lower.startswith("female:") or stripped.startswith("ស្រី:"):
        clean = stripped.split(":", 1)[-1].split("]", 1)[-1].strip()
        return VOICE_FEMALE, clean

    return None, stripped


async def synthesize(text: str, voice_name: str) -> AudioSegment:
    communicate = edge_tts.Communicate(text, voice_name)
    audio_bytes = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes.extend(chunk["data"])
    return AudioSegment.from_file(io.BytesIO(bytes(audio_bytes)), format="mp3")


def srt_time_to_ms(srt_time) -> int:
    return (
        (srt_time.hours * 3600 + srt_time.minutes * 60 + srt_time.seconds) * 1000
        + srt_time.milliseconds
    )


async def build_timed_audio(subs, pick_voice):
    """
    Synthesize each subtitle line and place it on a timeline anchored to the
    SRT start times (via overlay), so playback always matches the subtitle
    timing instead of drifting when a line runs long. Lines longer than their
    allotted slot (start -> end) are sped up, capped at MAX_SPEEDUP, to fit.

    pick_voice(forced_voice, line_index) -> voice_name
    Returns (canvas_or_None, success_count, fail_count, last_error).
    """
    clips = []  # (start_ms, AudioSegment)
    success_count = 0
    fail_count = 0
    last_error = None

    for i, sub in enumerate(subs):
        forced_voice, clean_text = strip_marker(sub.text.replace("\n", " "))
        if not clean_text:
            continue

        voice = pick_voice(forced_voice, i)
        start_ms = srt_time_to_ms(sub.start)
        end_ms = srt_time_to_ms(sub.end)
        allotted_ms = max(end_ms - start_ms, 1)

        try:
            clip = await synthesize(clean_text, voice)
        except Exception as e:
            logger.error("TTS failed for line %s (%r): %s", i, clean_text, e)
            fail_count += 1
            last_error = e
            continue

        success_count += 1

        if len(clip) > allotted_ms:
            ratio = min(len(clip) / allotted_ms, MAX_SPEEDUP)
            if ratio > SPEEDUP_THRESHOLD:
                try:
                    clip = pydub_speedup(clip, playback_speed=ratio)
                except Exception as e:
                    logger.warning("Speedup failed for line %s: %s", i, e)

        clips.append((start_ms, clip))

    if not clips:
        return None, success_count, fail_count, last_error

    total_ms = max(start + len(clip) for start, clip in clips)
    canvas = AudioSegment.silent(duration=total_ms)
    for start, clip in clips:
        canvas = canvas.overlay(clip, position=start)

    return canvas, success_count, fail_count, last_error


async def handle_srt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".srt"):
        await update.message.reply_text("សូមផ្ញើឯកសារ .srt ។")
        return

    tg_file = await doc.get_file()
    file_bytes = await tg_file.download_as_bytearray()

    # Stash the file for this user until they tap a voice button.
    context.user_data["srt_bytes"] = bytes(file_bytes)
    context.user_data["srt_filename"] = doc.file_name

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("👨 ប្រុស (Piseth)", callback_data=CB_MALE),
                InlineKeyboardButton("👩 ស្រី (Sreymom)", callback_data=CB_FEMALE),
            ],
            [InlineKeyboardButton("🔀 ឆ្លាស់ស្វ័យប្រវត្តិ", callback_data=CB_AUTO)],
        ]
    )
    await update.message.reply_text(
        "ជ្រើសរើសសំឡេងដែលអ្នកចង់បាន៖", reply_markup=keyboard
    )


async def handle_voice_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    file_bytes = context.user_data.get("srt_bytes")
    if not file_bytes:
        await query.edit_message_text("ឯកសារនេះផុតកំណត់ហើយ សូមផ្ញើ .srt ម្ដងទៀត។")
        return

    choice = query.data
    if choice == CB_MALE:
        default_voice = VOICE_MALE
        label = "សំឡេងប្រុស (Piseth)"
    elif choice == CB_FEMALE:
        default_voice = VOICE_FEMALE
        label = "សំឡេងស្រី (Sreymom)"
    else:
        default_voice = None  # alternate automatically per line
        label = "ឆ្លាស់ស្វ័យប្រវត្តិ"

    def pick_voice(forced_voice, i):
        if forced_voice:
            return forced_voice
        if default_voice:
            return default_voice
        return VOICE_MALE if i % 2 == 0 else VOICE_FEMALE

    await query.edit_message_text(f"បានជ្រើសរើស: {label}\nកំពុងដំណើរការ... សូមរង់ចាំបន្តិច។")

    with tempfile.TemporaryDirectory() as tmp:
        srt_path = os.path.join(tmp, context.user_data.get("srt_filename", "input.srt"))
        with open(srt_path, "wb") as f:
            f.write(file_bytes)

        try:
            subs = pysrt.open(srt_path, encoding="utf-8")
        except Exception as e:
            await query.edit_message_text(f"មិនអាចអានឯកសារ SRT បានទេ: {e}")
            return

        if len(subs) == 0:
            await query.edit_message_text("ឯកសារ SRT មិនមានខ្លឹមសារទេ។")
            return

        canvas, success_count, fail_count, last_error = await build_timed_audio(subs, pick_voice)

        if canvas is None:
            await query.edit_message_text(
                "សុំទោស! ការបំប្លែងសំឡេងបានបរាជ័យទាំងអស់ "
                f"({fail_count} បន្ទាត់)។ មូលហេតុ: {last_error}\n\n"
                "សូមសាកល្បងម្ដងទៀត បើនៅតែបញ្ហា សូមពិនិត្យ Render logs។"
            )
            return

        out_path = os.path.join(tmp, "output.mp3")
        canvas.export(out_path, format="mp3", bitrate="128k")

        status_note = f"បានជោគជ័យ {success_count} បន្ទាត់ (ត្រូវតាមវិនាទីក្នុង .srt)"
        if fail_count:
            status_note += f" — បរាជ័យ {fail_count} បន្ទាត់"

        await query.edit_message_text(f"បានជ្រើសរើស: {label}\n{status_note}\nកំពុងផ្ញើសំឡេង...")
        with open(out_path, "rb") as f:
            await context.bot.send_audio(
                chat_id=query.message.chat_id,
                audio=f,
                filename="voice.mp3",
                title="Khmer SRT Voice",
            )

    context.user_data.pop("srt_bytes", None)
    context.user_data.pop("srt_filename", None)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "សួស្តី! ផ្ញើឯកសារ .srt មកខ្ញុំ រួចជ្រើសរើសសំឡេងប្រុស (Piseth) ឬស្រី (Sreymom) "
        "ដោយចុច button ខ្ញុំនឹងបំប្លែងវាទៅជាសំឡេងខ្មែរឲ្យ ត្រូវតាមវិនាទីក្នុង .srt ដោយឥតគិតថ្លៃ។\n\n"
        "គន្លឹះ: បើចង់ចម្រុះប្រុស/ស្រីក្នុងឯកសារតែមួយ បន្ថែម [M] ឬ [F] នៅដើមបន្ទាត់ "
        "ក្នុង .srt រួចជ្រើសរើស 🔀 ឆ្លាស់ស្វ័យប្រវត្តិ។"
    )


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - bot is running")

    def log_message(self, format, *args):
        pass  # keep Render logs clean, no per-ping noise


def start_health_server():
    """
    Render's free plan is a Web Service and requires an open port to consider
    the deploy healthy. The bot itself only does Telegram polling (no HTTP
    server needed for that), so this tiny server exists purely to satisfy
    Render's port check. Use an external uptime pinger (see README) to keep
    the free instance from spinning down after 15 minutes of no traffic.
    """
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    server.serve_forever()


def main():
    threading.Thread(target=start_health_server, daemon=True).start()

    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.FileExtension("srt"), handle_srt))
    app.add_handler(CallbackQueryHandler(handle_voice_choice))
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
