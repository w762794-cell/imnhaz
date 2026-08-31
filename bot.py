import os
import io
import logging
import tempfile

import pysrt
import edge_tts
from pydub import AudioSegment
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, ContextTypes, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

# Free Microsoft neural voices (same catalog Edge browser's "Read aloud" uses).
# No API key or Azure account needed.
VOICE_MALE = "km-KH-PisethNeural"
VOICE_FEMALE = "km-KH-SreymomNeural"


def detect_voice(text: str, default_alternate_idx: int):
    """
    Decide which voice to use for a subtitle line.
    Supports optional markers at the start of a line:
      [M] / male: / ប្រុស:  -> Piseth (male)
      [F] / female: / ស្រី: -> Sreymom (female)
    Otherwise alternates male/female based on line index.
    """
    stripped = text.strip()
    lower = stripped.lower()

    if stripped.startswith("[M]") or lower.startswith("male:") or stripped.startswith("ប្រុស:"):
        clean = stripped.split(":", 1)[-1].split("]", 1)[-1].strip()
        return VOICE_MALE, clean
    if stripped.startswith("[F]") or lower.startswith("female:") or stripped.startswith("ស្រី:"):
        clean = stripped.split(":", 1)[-1].split("]", 1)[-1].strip()
        return VOICE_FEMALE, clean

    voice = VOICE_MALE if default_alternate_idx % 2 == 0 else VOICE_FEMALE
    return voice, stripped


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

    status_msg = await update.message.reply_text("កំពុងដំណើរការ... សូមរង់ចាំបន្តិច។")

    with tempfile.TemporaryDirectory() as tmp:
        srt_path = os.path.join(tmp, doc.file_name)
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(srt_path)

        try:
            subs = pysrt.open(srt_path, encoding="utf-8")
        except Exception as e:
            await status_msg.edit_text(f"មិនអាចអានឯកសារ SRT បានទេ: {e}")
            return

        if len(subs) == 0:
            await status_msg.edit_text("ឯកសារ SRT មិនមានខ្លឹមសារទេ។")
            return

        final_audio = AudioSegment.silent(duration=0)
        cursor_ms = 0

        for i, sub in enumerate(subs):
            voice, clean_text = detect_voice(sub.text.replace("\n", " "), i)
            if not clean_text:
                continue

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

        await status_msg.edit_text("បានបញ្ចប់! កំពុងផ្ញើសំឡេង...")
        with open(out_path, "rb") as f:
            await update.message.reply_audio(audio=f, filename="voice.mp3", title="Khmer SRT Voice")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "សួស្តី! ផ្ញើឯកសារ .srt មកខ្ញុំ ខ្ញុំនឹងបំប្លែងវាទៅជាសំឡេងខ្មែរ "
        "(ប្រុស Piseth / ស្រី Sreymom) ដោយឥតគិតថ្លៃ។\n\n"
        "គន្លឹះ: បន្ថែម [M] ឬ [F] នៅដើមបន្ទាត់ដើម្បីកំណត់ភេទសំឡេងច្បាស់លាស់ "
        "បើមិនដូច្នេះទេ bot នឹងឆ្លាស់ប្រុស/ស្រីដោយស្វ័យប្រវត្តិ។"
    )


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.FileExtension("srt"), handle_srt))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
