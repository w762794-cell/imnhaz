import os
import asyncio
import edge_tts
import whisper
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request

# កំណត់ Token និង URL ដែលបានផ្ដល់ជូន
TELEGRAM_BOT_TOKEN = "8820637952:AAHpabuhIsWJccfmcHUYUL2NOO892SX8a7o"
WEBHOOK_URL = "https://imnhaz.onrender.com"
PORT = int(os.environ.get("PORT", 5000))

app_flask = Flask(__name__)
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# 1. Function សម្រាប់បម្លែង SRT ទៅជា Audio
async def text_to_speech(text, voice, output_file):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_file)

async def handle_srt_to_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document.file_name.endswith('.srt'):
        await update.message.reply_text("សូមផ្ញើតែឯកសារ .srt មកប៉ុណ្ណោះ!")
        return

    file = await context.bot.get_file(document.file_id)
    file_path = f"downloads/{document.file_name}"
    os.makedirs("downloads", exist_ok=True)
    await file.download_to_drive(file_path)

    await update.message.reply_text("⏳ កំពុងដំណើរការបង្កើតសំឡេង...")
    output_audio = "downloads/output_audio.mp3"
    
    with open(file_path, 'r', encoding='utf-8') as f:
        srt_content = f.read()

    await text_to_speech(srt_content, "en-US-AriaNeural", output_audio)
    await update.message.reply_audio(audio=open(output_audio, 'rb'), caption="🎙️ សំឡេងបានរួចរាល់!")

# 2. Command /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("សួស្តី! Bot ដំណើរការជោគជ័យហើយ។ សូមផ្ញើឯកសារ SRT មកកាន់ខ្ញុំ។")

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.Document.FileExtension("srt"), handle_srt_to_audio))

@app_flask.route(f"/{TELEGRAM_BOT_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    asyncio.run(telegram_app.process_update(update))
    return "OK"

@app_flask.route("/")
def index():
    return "Bot is running!"

if __name__ == "__main__":
    if WEBHOOK_URL:
        async def set_wh():
            await telegram_app.bot.set_webhook(url=f"{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}")
        asyncio.run(set_wh())
    
    app_flask.run(host="0.0.0.0", port=PORT)
