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

# --- ជម្រើសសំឡេងសម្រាប់ SRT -> Audio ---
VOICE_MALE = "voice_male"
VOICE_FEMALE = "voice_female"
VOICE_ALTERNATE = "voice_alternate"


def main_menu_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("🔊 SRT -> Audio (ប្រុស/ស្រី)", callback_data=MODE_SRT2AUDIO)],
        [InlineKeyboardButton("🌐 បកប្រែ SRT ជាភាសាខ្មែរ", callback_data=MODE_TRANSLATE)],
        [InlineKeyboardButton("📝 Transcribe MP3 / MP4", callback_data=MODE_TRANSCRIBE)],
    ]
    return InlineKeyboardMarkup(buttons)


def voice_choice_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("👨 សំឡេងប្រុស (Piseth)", callback_data=VOICE_MALE)],
        [InlineKeyboardButton("👩 សំឡេងស្រី (Sreymom)", callback_data=VOICE_FEMALE)],
        [InlineKeyboardButton("👫 ឆ្លាស់គ្នា (Piseth + Sreymom)", callback_data=VOICE_ALTERNATE)],
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

    if mode == MODE_SRT2AUDIO:
        # សម្រាប់ SRT -> Audio ត្រូវសួរជម្រើសសំឡេងជាមុនសិន
        context.user_data["mode"] = MODE_SRT2AUDIO
        await query.edit_message_text(
            "សូមជ្រើសរើសសំឡេងដែលអ្នកចង់បាន:",
            reply_markup=voice_choice_keyboard(),
        )
        return

    context.user_data["mode"] = mode
    prompts = {
        MODE_TRANSLATE: "សូមផ្ញើឯកសារ .srt មកខ្ញុំ ខ្ញុំនឹងបកប្រែជាភាសាខ្មែរ 🌐",
        MODE_TRANSCRIBE: "សូមផ្ញើឯកសារ .mp3 ឬ .mp4 មកខ្ញុំ ខ្ញុំនឹងស្តាប់ ហើយសរសេរជាអត្ថបទ 📝",
    }
    await query.edit_message_text(prompts.get(mode, "សូមផ្ញើឯកសារ"))


async def voice_choice_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    choice = query.data  # voice_male | voice_female | voice_alternate

    voice_mode_map = {
        VOICE_MALE: "male",
        VOICE_FEMALE: "female",
        VOICE_ALTERNATE: "alternate",
    }
    context.user_data["voice_mode"] = voice_mode_map.get(choice, "alternate")
    context.user_data["mode"] = MODE_SRT2AUDIO

    labels = {
        VOICE_MALE: "សំឡេងប្រុស Piseth 👨",
        VOICE_FEMALE: "សំឡេងស្រី Sreymom 👩",
        VOICE_ALTERNATE: "ឆ្លាស់គ្នា Piseth+Sreymom 👫",
    }
    await query.edit_message_text(
        f"បានជ្រើសរើស: {labels.get(choice, '')}\n\n"
        "សូមផ្ញើឯកសារ .srt មកខ្ញុំ ខ្ញុំនឹងបំលែងទៅជាសំឡេង 🔊"
    )


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

    # --- ពិនិត្យទំហំ file មុន download ---
    # Telegram Bot API (ស្តង់ដារ) អនុញ្ញាតឲ្យ bot ទាញយក (download) file បានតែត្រឹម ~20MB ប៉ុណ្ណោះ
    # ក្រៅពីនេះ get_file() នឹងបរាជ័យ (មិនថាទំហំ upload អនុញ្ញាតដល់ 50MB ក៏ដោយ)
    file_size = getattr(doc, "file_size", None)
    MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024
    if file_size and file_size > MAX_DOWNLOAD_BYTES:
        size_mb = file_size / (1024 * 1024)
        await update.message.reply_text(
            f"❌ File នេះទំហំ {size_mb:.1f} MB ធំជាងកម្រិតដែល Telegram Bot API អនុញ្ញាតឲ្យ "
            f"bot ទាញយកបាន (កំណត់ត្រឹម 20MB)។\n\n"
            "សូមកាត់ file ឲ្យតូចជាង ឬបំលែងទៅជា audio (.mp3) ជាមុនសិន "
            "(ឯកសារ audio ជាធម្មតាមានទំហំតូចជាង video ច្រើន)។"
        )
        return

    file_name = getattr(doc, "file_name", None) or "input_file"
    ext = os.path.splitext(file_name)[1].lower()

    with tempfile.TemporaryDirectory() as work_dir:
        input_path = os.path.join(work_dir, file_name)

        try:
            tg_file = await context.bot.get_file(doc.file_id)
            await tg_file.download_to_drive(input_path)
        except Exception as e:
            logger.exception("Download failed")
            await update.message.reply_text(
                f"❌ មិនអាចទាញយក file បានទេ: {e}\n\n"
                "ជាទូទៅមូលហេតុគឺ file ធំពេក (លើសពី 20MB) — សូមសាកល្បងជាមួយ file តូចជាង។"
            )
            return

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

    voice_mode = context.user_data.get("voice_mode", "alternate")
    voice_label = {
        "male": "Piseth 👨",
        "female": "Sreymom 👩",
        "alternate": "Piseth+Sreymom 👫",
    }.get(voice_mode, "Piseth+Sreymom 👫")

    status_msg = await update.message.reply_text(
        f"កំពុងបំលែងជាសំឡេង ({voice_label})... 0%"
    )
    await context.bot.send_chat_action(update.effective_chat.id, ChatAction.UPLOAD_DOCUMENT)

    out_path = os.path.join(work_dir, "output.mp3")

    last_reported = {"pct": -1}

    async def progress_cb(current, total):
        pct = int(current / total * 100)
        if pct != last_reported["pct"] and pct % 10 == 0:
            last_reported["pct"] = pct
            try:
                await status_msg.edit_text(f"កំពុងបំលែងជាសំឡេង ({voice_label})... {pct}%")
            except Exception:
                pass

    await build_audio_from_srt(
        input_path, out_path, work_dir,
        voice_mode=voice_mode,
        progress_cb=progress_cb,
    )

    await status_msg.edit_text("បញ្ចប់! កំពុងផ្ញើឯកសារសំឡេង... ✅")

    # ផ្ញើជា document (.mp3) ដើម្បីធានាថា download បាន 100%
    with open(out_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename="dubbed_audio.mp3",
            caption=f"សំឡេងបានបំលែងរួចរាល់ ({voice_label}) 🔊",
        )


async def handle_translate(update, context, input_path, ext, work_dir):
    if ext != ".srt":
        await update.message.reply_text("សូមផ្ញើឯកសារ .srt ប៉ុណ្ណោះសម្រាប់មុខងារនេះ")
        return

    status_msg = await update.message.reply_text("កំពុងបកប្រែ... 🌐 0%")
    out_path = os.path.join(work_dir, "translated_km.srt")

    progress_state = {"current": 0, "total": None}

    def _progress_cb(current, total):
        progress_state["current"] = current
        progress_state["total"] = total

    # translate_srt_file ប្រើ time.sleep() ខាងក្នុង (ដើម្បីជៀសវាង rate-limit ពី translator)
    # ដូច្នេះត្រូវរត់ក្នុង background thread ដើម្បីកុំឲ្យ block bot ទាំងមូល
    task = asyncio.create_task(
        asyncio.to_thread(translate_srt_file, input_path, out_path, "km", 3, 0.6, _progress_cb)
    )

    elapsed = 0
    last_reported_pct = -1
    MAX_WAIT_SECONDS = 8 * 60  # បើលើសពី ៨ នាទីនៅតែគ្មានវឌ្ឍនភាព -> បោះបង់ ជំនួសគាំងជានិច្ច

    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except asyncio.TimeoutError:
            elapsed += 5

            if elapsed >= MAX_WAIT_SECONDS:
                task.cancel()
                await status_msg.edit_text(
                    "❌ ការបកប្រែចំណាយពេលយូរពេក (លើសពី 8 នាទី) ដូច្នេះខ្ញុំបានបោះបង់។\n\n"
                    "ជាទូទៅមូលហេតុគឺ translator engine ទាំង ២ ត្រូវបានទប់ស្កាត់ជាបណ្តោះអាសន្ន។ "
                    "សូមសាកល្បងម្តងទៀតក្រោយពីប្រាំនាទី។"
                )
                return

            total = progress_state["total"]
            current = progress_state["current"]
            if total:
                pct = min(int(current / total * 100), 99)
                if pct != last_reported_pct:
                    last_reported_pct = pct
                    try:
                        await status_msg.edit_text(f"កំពុងបកប្រែ... 🌐 {pct}%")
                    except Exception:
                        pass

    task.result()  # បើ error កើតឡើង នឹង raise ត្រឡប់ទៅ caller (ចាប់ដោយ try/except ខាងក្រៅ)

    await status_msg.edit_text("បកប្រែរួចរាល់! ✅")
    with open(out_path, "rb") as f:
        await update.message.reply_document(f, filename="translated_km.srt")


async def handle_transcribe(update, context, input_path, ext, work_dir):
    if ext not in (".mp3", ".mp4", ".wav", ".m4a", ".ogg", ".mov", ".mkv"):
        await update.message.reply_text("សូមផ្ញើឯកសារ .mp3 ឬ .mp4 សម្រាប់មុខងារនេះ")
        return

    status_msg = await update.message.reply_text(
        "កំពុងស្តាប់ និងសរសេរជាអត្ថបទ... 📝 0%"
    )
    out_srt = os.path.join(work_dir, "transcript.srt")

    # language=None -> auto-detect. ដាក់ "km" បើដឹងថាជាសំឡេងខ្មែរ ដើម្បីភាពត្រឹមត្រូវខ្ពស់ជាង
    # model_size default = "base" (តូច លឿន ត្រូវការ RAM តិចជាង) ព្រោះ Render free tier
    # មាន RAM តែ 512MB ប៉ុណ្ណោះ — "small"/"medium" អាចធ្វើឲ្យ process OOM-crash
    # (បើ host លើម៉ាស៊ីនផ្ទាល់ខ្លួនដែលមាន RAM ច្រើន អាចប្តូរទៅ "small"/"medium"/"large-v3")
    model_size = os.environ.get("WHISPER_MODEL_SIZE", "base")

    # --- shared state ដែល background thread សរសេរចូល, ហើយ async loop អាន ---
    # (សរសេរ/អាន key លើ dict ធម្មតាមួយ គឺ thread-safe គ្រប់គ្រាន់សម្រាប់ករណីនេះក្នុង CPython)
    progress_state = {"current": 0.0, "total": None}

    def _progress_cb(current_seconds, total_seconds):
        progress_state["current"] = current_seconds
        progress_state["total"] = total_seconds

    # --- ដំណើរការ transcribe (blocking/CPU-heavy) នៅក្នុង background thread ---
    # ដើម្បីកុំឲ្យ block event loop របស់ bot (បើមិនធ្វើបែបនេះ bot នឹងឈប់ឆ្លើយតប
    # សារផ្សេងទៀត រួមទាំង /start ខណៈកំពុង transcribe)
    task = asyncio.create_task(
        asyncio.to_thread(
            transcribe_to_srt, input_path, out_srt, work_dir, None, model_size, _progress_cb
        )
    )

    elapsed = 0
    last_reported_pct = -1
    MAX_WAIT_SECONDS = 8 * 60  # បើលើសពី ៨ នាទីនៅតែគ្មានវឌ្ឍនភាព -> បោះបង់ ជំនួសគាំងជានិច្ច

    while not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=5)
        except asyncio.TimeoutError:
            elapsed += 5

            if elapsed >= MAX_WAIT_SECONDS:
                task.cancel()
                await status_msg.edit_text(
                    "❌ ការស្តាប់ចំណាយពេលយូរពេក (លើសពី 8 នាទី) ដូច្នេះខ្ញុំបានបោះបង់។\n\n"
                    "ជាទូទៅមូលហេតុគឺ Render free tier ខ្សោយពេក ឬបញ្ហា network។ "
                    "សូមសាកល្បងជាមួយ file ខ្លីជាង ឬសាកល្បងម្តងទៀតក្រោយពីប្រាំនាទី។"
                )
                return

            total = progress_state["total"]
            current = progress_state["current"]

            if total:
                pct = min(int(current / total * 100), 99)  # 99% រហូតដល់ចប់ពិតប្រាកដ
                if pct != last_reported_pct:
                    last_reported_pct = pct
                    try:
                        await status_msg.edit_text(
                            f"កំពុងស្តាប់ និងសរសេរជាអត្ថបទ... 📝 {pct}%"
                        )
                    except Exception:
                        pass
            elif elapsed % 20 == 0:
                # មិនទាន់ដឹងប្រវែងសរុប (ឧ. កំពុង download/load model នៅឡើយ)
                try:
                    await status_msg.edit_text(
                        f"កំពុងរៀបចំ (download/load model)... 📝 ({elapsed} វិនាទី)"
                    )
                except Exception:
                    pass

    # បើ task raise exception, .result() នឹង raise វាឡើងវិញឲ្យ caller ចាប់
    task.result()

    await status_msg.edit_text("ស្តាប់រួចរាល់! កំពុងផ្ញើលទ្ធផល... ✅")

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
    app.add_handler(
        CallbackQueryHandler(voice_choice_callback, pattern="^voice_(male|female|alternate)$")
    )
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
