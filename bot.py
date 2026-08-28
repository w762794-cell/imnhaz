import os
import re
import asyncio
import tempfile
import threading
from pathlib import Path

from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

from deep_translator import GoogleTranslator
import edge_tts
from pydub import AudioSegment
from faster_whisper import WhisperModel


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = "8820637952:AAHpabuhIsWJccfmcHUYUL2NOO892SX8a7o"

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")

# Whisper model:
# tiny  = fast / lower accuracy
# base  = better accuracy
# small = better but needs more RAM
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "tiny")

# Khmer voices
MALE_VOICE = "km-KH-PisethNeural"
FEMALE_VOICE = "km-KH-SreymomNeural"

# Temporary folder
TEMP_DIR = Path(tempfile.gettempdir()) / "telegram_srt_bot"
TEMP_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# FLASK SERVER
# Render Web Service needs a port
# =========================================================

web = Flask(__name__)


@web.get("/")
def home():
    return "Telegram Media Bot is running."


@web.get("/health")
def health():
    return {"status": "ok"}


def run_web():
    port = int(os.getenv("PORT", "10000"))
    web.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


# =========================================================
# GLOBAL USER STATE
# =========================================================

user_modes = {}


# =========================================================
# SRT PARSER
# =========================================================

TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*"
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


def time_to_ms(h, m, s, ms):
    return (
        int(h) * 3600000
        + int(m) * 60000
        + int(s) * 1000
        + int(ms)
    )


def ms_to_srt(ms):
    h = ms // 3600000
    ms %= 3600000

    m = ms // 60000
    ms %= 60000

    s = ms // 1000
    ms %= 1000

    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_srt(text):
    blocks = re.split(r"\n\s*\n", text.strip())

    subtitles = []

    for block in blocks:
        lines = block.splitlines()

        if len(lines) < 2:
            continue

        time_line = None
        time_index = None

        for i, line in enumerate(lines):
            if "-->" in line:
                time_line = line
                time_index = i
                break

        if not time_line:
            continue

        match = TIME_RE.search(time_line)

        if not match:
            continue

        start = time_to_ms(*match.groups()[:4])
        end = time_to_ms(*match.groups()[4:])

        text_lines = lines[time_index + 1:]

        text = "\n".join(text_lines).strip()

        if not text:
            continue

        subtitles.append(
            {
                "start": start,
                "end": end,
                "text": text,
            }
        )

    return subtitles


# =========================================================
# SRT -> AUDIO
# =========================================================

async def create_tts(text, output_file, voice):
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
    )

    await communicate.save(output_file)


async def srt_to_audio(srt_file, output_file, voice):
    text = Path(srt_file).read_text(
        encoding="utf-8-sig"
    )

    subtitles = parse_srt(text)

    if not subtitles:
        raise ValueError("SRT file មិនត្រឹមត្រូវ ឬគ្មាន subtitle")

    total_end = max(x["end"] for x in subtitles)

    # Create empty timeline
    final_audio = AudioSegment.silent(
        duration=total_end + 500
    )

    for index, sub in enumerate(subtitles):
        clean_text = re.sub(
            r"<[^>]+>",
            "",
            sub["text"]
        )

        clean_text = clean_text.replace(
            "\n",
            " "
        )

        if not clean_text.strip():
            continue

        tts_file = TEMP_DIR / f"tts_{os.getpid()}_{index}.mp3"

        try:
            await create_tts(
                clean_text,
                str(tts_file),
                voice,
            )

            clip = AudioSegment.from_file(
                str(tts_file)
            )

            start = sub["start"]
            end = sub["end"]

            target_duration = max(
                100,
                end - start
            )

            # Make speech fit inside SRT timing.
            if len(clip) > target_duration:
                clip = clip[:target_duration]

            final_audio = final_audio.overlay(
                clip,
                position=start,
            )

        finally:
            if tts_file.exists():
                tts_file.unlink()

    final_audio.export(
        output_file,
        format="mp3",
        bitrate="128k",
    )


# =========================================================
# SRT -> KHMER
# =========================================================

def translate_srt(input_file, output_file):
    text = Path(input_file).read_text(
        encoding="utf-8-sig"
    )

    subtitles = parse_srt(text)

    if not subtitles:
        raise ValueError("SRT file មិនត្រឹមត្រូវ")

    translator = GoogleTranslator(
        source="auto",
        target="km",
    )

    output = []

    for index, sub in enumerate(subtitles, 1):

        original = sub["text"]

        try:
            translated = translator.translate(
                original.replace("\n", " ")
            )

        except Exception:
            translated = original

        output.append(
            str(index)
        )

        output.append(
            f"{ms_to_srt(sub['start'])} --> "
            f"{ms_to_srt(sub['end'])}"
        )

        output.append(translated)
        output.append("")

    Path(output_file).write_text(
        "\n".join(output),
        encoding="utf-8"
    )


# =========================================================
# TRANSCRIPT MP3 / MP4
# =========================================================

_whisper_model = None


def get_whisper():
    global _whisper_model

    if _whisper_model is None:
        _whisper_model = WhisperModel(
            WHISPER_MODEL,
            device="cpu",
            compute_type="int8",
        )

    return _whisper_model


def transcribe_media(input_file):
    model = get_whisper()

    segments, info = model.transcribe(
        input_file,
        beam_size=5,
    )

    result = []

    for segment in segments:
        start = segment.start
        end = segment.end
        text = segment.text.strip()

        result.append(
            f"[{start:.2f}s --> {end:.2f}s] {text}"
        )

    return "\n".join(result)


# =========================================================
# TELEGRAM MENU
# =========================================================

def main_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "🎙️ SRT → Audio",
                callback_data="srt_audio",
            )
        ],
        [
            InlineKeyboardButton(
                "🇰🇭 SRT → Khmer",
                callback_data="srt_khmer",
            )
        ],
        [
            InlineKeyboardButton(
                "📝 MP3/MP4 → Transcript",
                callback_data="transcript",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


def voice_menu():
    keyboard = [
        [
            InlineKeyboardButton(
                "👨 សំឡេងប្រុស",
                callback_data="voice_male",
            ),
            InlineKeyboardButton(
                "👩 សំឡេងស្រី",
                callback_data="voice_female",
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ ត្រឡប់",
                callback_data="back",
            )
        ],
    ]

    return InlineKeyboardMarkup(keyboard)


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🤖 Media Converter Bot\n\n"
        "សូមជ្រើសរើស Function:",
        reply_markup=main_menu(),
    )


# =========================================================
# BUTTON HANDLER
# =========================================================

async def button_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    query = update.callback_query

    await query.answer()

    user_id = query.from_user.id

    if query.data == "back":

        user_modes.pop(user_id, None)

        await query.edit_message_text(
            "🤖 ជ្រើសរើស Function:",
            reply_markup=main_menu(),
        )

        return

    if query.data == "srt_audio":

        user_modes[user_id] = {
            "mode": "srt_audio"
        }

        await query.edit_message_text(
            "🎙️ SRT → Audio\n\n"
            "សូមជ្រើសរើសសំឡេង:",
            reply_markup=voice_menu(),
        )

        return

    if query.data == "voice_male":

        user_modes[user_id] = {
            "mode": "srt_audio",
            "voice": MALE_VOICE,
        }

        await query.edit_message_text(
            "👨 ជ្រើសរើសសំឡេងប្រុសរួចរាល់!\n\n"
            "ឥឡូវផ្ញើ file `.srt` មក។"
        )

        return

    if query.data == "voice_female":

        user_modes[user_id] = {
            "mode": "srt_audio",
            "voice": FEMALE_VOICE,
        }

        await query.edit_message_text(
            "👩 ជ្រើសរើសសំឡេងស្រីរួចរាល់!\n\n"
            "ឥឡូវផ្ញើ file `.srt` មក។"
        )

        return

    if query.data == "srt_khmer":

        user_modes[user_id] = {
            "mode": "srt_khmer"
        }

        await query.edit_message_text(
            "🇰🇭 SRT → Khmer\n\n"
            "សូមផ្ញើ file `.srt` មក។"
        )

        return

    if query.data == "transcript":

        user_modes[user_id] = {
            "mode": "transcript"
        }

        await query.edit_message_text(
            "📝 MP3/MP4 → Transcript\n\n"
            "សូមផ្ញើ MP3 ឬ MP4 មក។"
        )

        return


# =========================================================
# FILE HANDLER
# =========================================================

async def file_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    user_id = update.effective_user.id

    mode_data = user_modes.get(user_id)

    if not mode_data:

        await update.message.reply_text(
            "សូមចុច /start ហើយជ្រើសរើស Function មុន។"
        )

        return

    document = update.message.document

    if not document:

        return

    filename = document.file_name or "file"

    suffix = Path(filename).suffix.lower()

    allowed = [
        ".srt",
        ".mp3",
        ".mp4",
        ".m4a",
        ".wav",
        ".mov",
        ".mkv",
    ]

    if suffix not in allowed:

        await update.message.reply_text(
            "❌ File មិន support\n\n"
            "Support: SRT / MP3 / MP4 / M4A / WAV / MOV / MKV"
        )

        return

    status = await update.message.reply_text(
        "⏳ កំពុង download file..."
    )

    work_dir = Path(
        tempfile.mkdtemp(
            dir=TEMP_DIR
        )
    )

    input_file = work_dir / filename

    try:

        tg_file = await context.bot.get_file(
            document.file_id
        )

        await tg_file.download_to_drive(
            custom_path=str(input_file)
        )

        mode = mode_data["mode"]

        # =================================================
        # SRT -> AUDIO
        # =================================================

        if mode == "srt_audio":

            if suffix != ".srt":

                await status.edit_text(
                    "❌ Function នេះត្រូវការ `.srt`"
                )

                return

            voice = mode_data.get(
                "voice",
                MALE_VOICE,
            )

            output = work_dir / "audio.mp3"

            await status.edit_text(
                "🎙️ កំពុងបង្កើត Audio...\n"
                "វាអានតាម timestamp ក្នុង SRT។"
            )

            await srt_to_audio(
                str(input_file),
                str(output),
                voice,
            )

            await update.message.reply_audio(
                audio=open(output, "rb"),
                caption="✅ SRT → Audio រួចរាល់"
            )

        # =================================================
        # SRT -> KHMER
        # =================================================

        elif mode == "srt_khmer":

            if suffix != ".srt":

                await status.edit_text(
                    "❌ Function នេះត្រូវការ `.srt`"
                )

                return

            output = work_dir / "khmer.srt"

            await status.edit_text(
                "🇰🇭 កំពុងបកប្រែទៅភាសាខ្មែរ..."
            )

            await asyncio.to_thread(
                translate_srt,
                str(input_file),
                str(output),
            )

            await update.message.reply_document(
                document=open(output, "rb"),
                caption="✅ SRT បកប្រែជាខ្មែរ រួចរាល់"
            )

        # =================================================
        # TRANSCRIPT
        # =================================================

        elif mode == "transcript":

            if suffix not in [
                ".mp3",
                ".mp4",
                ".m4a",
                ".wav",
                ".mov",
                ".mkv",
            ]:

                await status.edit_text(
                    "❌ Function នេះត្រូវការ MP3/MP4"
                )

                return

            await status.edit_text(
                "📝 កំពុង Transcribe...\n"
                "សូមរង់ចាំ..."
            )

            result = await asyncio.to_thread(
                transcribe_media,
                str(input_file),
            )

            output = work_dir / "transcript.txt"

            output.write_text(
                result,
                encoding="utf-8"
            )

            await update.message.reply_document(
                document=open(output, "rb"),
                caption="✅ Transcript រួចរាល់"
            )

        await status.delete()

    except Exception as e:

        await status.edit_text(
            "❌ មានបញ្ហា:\n\n"
            f"{str(e)[:3500]}"
        )

    finally:

        user_modes.pop(user_id, None)

        try:
            for item in work_dir.iterdir():
                item.unlink(missing_ok=True)

            work_dir.rmdir()

        except Exception:
            pass


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):

    await update.message.reply_text(
        "📁 សូមផ្ញើជា file មកខ្ញុំ "
        "ដើម្បីដំណើរការ។",
        reply_markup=main_menu(),
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):

    print(
        "ERROR:",
        context.error,
    )


# =========================================================
# MAIN
# =========================================================

def main():

    # Start web server for Render
    threading.Thread(
        target=run_web,
        daemon=True,
    ).start()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            button_handler
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            file_handler,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler,
        )
    )

    app.add_error_handler(
        error_handler
    )

    print("BOT STARTED")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()