import os
import io
import logging
import tempfile

import pysrt
import edge_tts
from pydub import AudioSegment
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

        final_audio = AudioSegment.silent(duration=0)
        cursor_ms = 0

        for i, sub in enumerate(subs):
            forced_voice, clean_text = strip_marker(sub.text.replace("\n", " "))
            if not clean_text:
                continue

            if forced_voice:
                voice = forced_voice
            elif default_voice:
                voice = default_voice
            else:
                voice = VOICE_MALE if i % 2 == 0 else VOICE_FEMALE

            start_ms = srt_time_to_ms(sub.start)
            gap = start_ms - cursor_ms
            if gap > 0:
                final_audio += AudioSegment.silent(duration=gap)
                cursor_ms += gap

            try:
                clip = await synthesize(clean_text, voice)
            except Exception as e:
                logger.error("TTS failed for line %s: %s", i, e)
                continue

            final_audio += clip
            cursor_ms += len(clip)

        out_path = os.path.join(tmp, "output.mp3")
        final_audio.export(out_path, format="mp3", bitrate="128k")

        await query.edit_message_text(f"បានជ្រើសរើស: {label}\nបានបញ្ចប់! កំពុងផ្ញើសំឡេង...")
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
        "ដោយចុច button ខ្ញុំនឹងបំប្លែងវាទៅជាសំឡេងខ្មែរឲ្យ ដោយឥតគិតថ្លៃ។\n\n"
        "គន្លឹះ: បើចង់ចម្រុះប្រុស/ស្រីក្នុងឯកសារតែមួយ បន្ថែម [M] ឬ [F] នៅដើមបន្ទាត់ "
        "ក្នុង .srt រួចជ្រើសរើស 🔀 ឆ្លាស់ស្វ័យប្រវត្តិ។"
    )


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.FileExtension("srt"), handle_srt))
    app.add_handler(CallbackQueryHandler(handle_voice_choice))
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
