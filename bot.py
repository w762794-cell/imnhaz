"""
bot.py
------
Telegram Bot ដែលមាន 3 មុខងារ:
  1) /srt2audio  -> ផ្ញើ file .srt -> bot បំលែងទៅជា audio (.mp3) អានតាមពេលវេលា
                     ដោយឆ្លាស់សំឡេងប្រុស/ស្រី
  2) /translate  -> ផ្ញើ file .srt -> bot បកប្រែទៅជាភាសាខ្មែរ ហើយផ្ញើ .srt ថ្មីត្រឡប់មកវិញ
  3) /transcribe -> ផ្ញើ file .mp3 ឬ .mp4 -> bot ស្តាប់ ហើយបំលែងទៅជាអត្ថបទ + .srt

របៀបដំណើរការ:
  python bot.py
(ត្រូវការដាក់ BOT_TOKEN ក្នុងឯកសារ .env ជាមុនសិន សូមមើល README.md)
"""

import os
import logging
import asyncio
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# --- ផ្នែកនេះមានតែមួយគោលបំណង៖ បំពេញលក្ខខណ្ឌ "health check" របស់ Render ---
# Render (Web Service, free tier) តម្រូវឲ្យ app listen លើ port ណាមួយ
# ដើម្បីដឹងថា service កំពុងដំណើរការ។ Telegram bot (polling) មិនប្រើ port ដោយខ្លួនឯងទេ
# ដូច្នេះយើងបើក HTTP server តូចមួយស្របគ្នា គ្រាន់តែឆ្លើយ "OK" ប៉ុណ្ណោះ។
class _HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def log_message(self, format, *args):
        pass  # បិទ log រំខានពី health check requests


def start_health_check_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info(f"Health-check server កំពុងស្តាប់លើ port {port}")

from srt_audio import build_audio_from_srt
from srt_translate import translate_srt_file
from transcribe import transcribe_to_srt

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- តំណាងឲ្យ "mode" ដែល user កំពុងជ្រើសរើស (រក្សាទុកក្នុង user_data) ---
MODE_SRT2AUDIO = "srt2audio"
MODE_TRANSLATE = "translate"
MODE_TRANSCRIBE = "transcribe"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("🔊 SRT -> Audio (ប្រុស/ស្រី)", callback_data=MODE_SRT2AUDIO)],
        [InlineKeyboardButton("🌐 បកប្រែ SRT ជាភាសាខ្មែរ", callback_data=MODE_TRANSLATE)],
        [InlineKeyboardButton("📝 Transcribe MP3 / MP4", callback_data=MODE_TRANSCRIBE)],
    ]
    return InlineKeyboardMarkup(buttons)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "សួស្តី! 👋 ខ្ញុំជា Bot ជំនួយសម្រាប់ SRT / សំឡេង / វីដេអូ។\n\n"
        "សូមជ្រើសរើសមុខងារខាងក្រោម រួចផ្ញើឯកសារមកខ្ញុំ:"
    )
    await update.message.reply_text(text, reply_markup=main_menu_keyboard())


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    mode = query.data
    context.user_data["mode"] = mode

    prompts = {
        MODE_SRT2AUDIO: "សូមផ្ញើឯកសារ .srt មកខ្ញុំ ខ្ញុំនឹងបំលែងទៅជាសំឡេង 🔊",
        MODE_TRANSLATE: "សូមផ្ញើឯកសារ .srt មកខ្ញុំ ខ្ញុំនឹងបកប្រែជាភាសាខ្មែរ 🌐",
        MODE_TRANSCRIBE: "សូមផ្ញើឯកសារ .mp3 ឬ .mp4 មកខ្ញុំ ខ្ញុំនឹងស្តាប់ ហើយសរសេរជាអត្ថបទ 📝",
    }
    await query.edit_message_text(prompts.get(mode, "សូមផ្ញើឯកសារ"))


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = context.user_data.get("mode")
    if not mode:
        await update.message.reply_text(
            "សូមជ្រើសរើសមុខងារជាមុនសិន /start", reply_markup=main_menu_keyboard()
        )
        return

    doc = update.message.document or update.message.audio or update.message.video
    if not doc:
        await update.message.reply_text("សូមផ្ញើជា file ដែលត្រឹមត្រូវ (document/audio/video)")
        return

    file_name = getattr(doc, "file_name", None) or "input_file"
    ext = os.path.splitext(file_name)[1].lower()

    with tempfile.TemporaryDirectory() as work_dir:
        input_path = os.path.join(work_dir, file_name)
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(input_path)

        try:
            if mode == MODE_SRT2AUDIO:
                await handle_srt2audio(update, context, input_path, ext, work_dir)
            elif mode == MODE_TRANSLATE:
                await handle_translate(update, context, input_path, ext, work_dir)
            elif mode == MODE_TRANSCRIBE:
                await handle_transcribe(update, context, input_path, ext, work_dir)
        except Exception as e:
            logger.exception("Processing failed")
            await update.message.reply_text(f"❌ មានបញ្ហា: {e}")


async def handle_srt2audio(update, context, input_path, ext, work_dir):
    if ext != ".srt":
        await update.message.reply_text("សូមផ្ញើឯកសារ .srt ប៉ុណ្ណោះសម្រាប់មុខងារនេះ")
        return

    status_msg = await update.message.reply_text("កំពុងបំលែងជាសំឡេង... 0%")
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.RECORD_VOICE)

    out_path = os.path.join(work_dir, "output.mp3")

    last_reported = {"pct": -1}

    async def progress_cb(current, total):
        pct = int(current / total * 100)
        if pct != last_reported["pct"] and pct % 10 == 0:
            last_reported["pct"] = pct
            try:
                await status_msg.edit_text(f"កំពុងបំលែងជាសំឡេង... {pct}%")
            except Exception:
                pass

    await build_audio_from_srt(input_path, out_path, work_dir, progress_cb=progress_cb)

    await status_msg.edit_text("បញ្ចប់! កំពុងផ្ញើឯកសារសំឡេង... ✅")
    with open(out_path, "rb") as f:
        await update.message.reply_audio(f, filename="dubbed_audio.mp3")


async def handle_translate(update, context, input_path, ext, work_dir):
    if ext != ".srt":
        await update.message.reply_text("សូមផ្ញើឯកសារ .srt ប៉ុណ្ណោះសម្រាប់មុខងារនេះ")
        return

    await update.message.reply_text("កំពុងបកប្រែ... 🌐")
    out_path = os.path.join(work_dir, "translated_km.srt")
    translate_srt_file(input_path, out_path, target_lang="km")

    with open(out_path, "rb") as f:
        await update.message.reply_document(f, filename="translated_km.srt")


async def handle_transcribe(update, context, input_path, ext, work_dir):
    if ext not in (".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".mov", ".mkv"):
        await update.message.reply_text("សូមផ្ញើឯកសារ .mp3 ឬ .mp4 សម្រាប់មុខងារនេះ")
        return

    await update.message.reply_text("កំពុងស្តាប់ និងសរសេរជាអត្ថបទ... 📝 (អាចចំណាយពេលបន្តិច)")
    out_srt = os.path.join(work_dir, "transcript.srt")

    # language=None -> auto-detect. ដាក់ "km" បើដឹងថាជាសំឡេងខ្មែរ ដើម្បីភាពត្រឹមត្រូវខ្ពស់ជាង
    # model_size="small" ព្រោះ Render free/starter tier មាន RAM មិនច្រើន
    # (បើ host លើម៉ាស៊ីនផ្ទាល់ខ្លួនដែលមាន RAM ច្រើន អាចប្តូរទៅ "medium" ឬ "large-v3")
    model_size = os.environ.get("WHISPER_MODEL_SIZE", "small")
    transcribe_to_srt(input_path, out_srt, work_dir, language=None, model_size=model_size)

    with open(out_srt, "r", encoding="utf-8") as f:
        content = f.read()

    with open(out_srt, "rb") as f:
        await update.message.reply_document(f, filename="transcript.srt")

    # ផ្ញើអត្ថបទសុទ្ធជា message ដែរ បើវាមិនវែងពេក
    plain_text = "\n".join(
        line for line in content.splitlines()
        if line and not line.strip().isdigit() and "-->" not in line
    ).strip()
    if plain_text and len(plain_text) < 3500:
        await update.message.reply_text(f"អត្ថបទដែលបានស្តាប់ចេញ:\n\n{plain_text}")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("សូមកំណត់ BOT_TOKEN នៅក្នុងឯកសារ .env ជាមុនសិន")

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(menu_callback))
    app.add_handler(
        MessageHandler(filters.Document.ALL | filters.AUDIO | filters.VIDEO, handle_document)
    )

    # បើក health-check server សម្រាប់ Render (មិនប៉ះពាល់អ្វីទេប្រសិនបើ run local)
    start_health_check_server()

    logger.info("Bot កំពុងដំណើរការ...")
    app.run_polling()


if __name__ == "__main__":
    main()
