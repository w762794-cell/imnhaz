import os
import re
import asyncio
import edge_tts
from pydub import AudioSegment
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from flask import Flask, request
from deep_translator import GoogleTranslator
import whisper

TELEGRAM_BOT_TOKEN = "8820637952:AAHpabuhIsWJccfmcHUYUL2NOO892SX8a7o"
WEBHOOK_URL = "https://imnhaz.onrender.com"
PORT = int(os.environ.get("PORT", 5000))

app_flask = Flask(__name__)
telegram_app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

def parse_time_to_ms(time_str):
    """បម្លែងម៉ោង SRT (00:00:01,234) ទៅជា Milliseconds"""
    h, m, s_ms = time_str.replace(',', ':').split(':')
    return int(h) * 3600000 + int(m) * 60000 + int(s_ms[0]) * 1000 + int(s_ms[1])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 សួស្តី! Bot ដំណើរការជោគជ័យហើយ។\n"
        "📌 មុខងារដែលមាន:\n"
        "1. ផ្ញើ SRT ➔ បម្លែងជា Audio ត្រូវតាមវិនាទី (ប្រុស/ស្រី)\n"
        "2. ផ្ញើ MP3/MP4 ➔ Transcribe ជា Text\n"
        "*(ចំណាំ: សម្រាប់បកប្រែ SRT ជាខ្មែរ សូមប្រើពាក្យ ឬ Command បន្ថែម)*"
    )

# ១. Function បម្លែង SRT ទៅជា Audio ត្រូវតាមវិនាទី (មានសំឡេងប្រុស និងស្រី)
async def handle_srt_to_timed_audio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document or not document.file_name.endswith('.srt'):
        await update.message.reply_text("សូមផ្ញើតែឯកសារ .srt មកប៉ុណ្ណោះ!")
        return

    file = await context.bot.get_file(document.file_id)
    file_path = f"downloads/{document.file_name}"
    os.makedirs("downloads", exist_ok=True)
    await file.download_to_drive(file_path)

    await update.message.reply_text("⏳ កំពុងគណនាវិនាទី និងបង្កើតសំឡេង (ប្រុស និងស្រី)...")

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = re.compile(r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\Z)', re.DOTALL)
    matches = pattern.findall(content)

    if not matches:
        await update.message.reply_text("❌ ទម្រង់ឯកសារ SRT មិនត្រឹមត្រូវ!")
        return

    final_audio = AudioSegment.silent(duration=0)
    current_pos = 0

    for i, match in enumerate(matches):
        start_str, text = match[1], match[3].replace('\n', ' ')
        start_ms = parse_time_to_ms(start_str)
        
        # បន្ថែម Silence តាមកាលវិនាទីពិតប្រាកដ
        if start_ms > current_pos:
            final_audio += AudioSegment.silent(duration=(start_ms - current_pos))

        # ប្តូរវេនសំឡេង ស្រី (en-US-AriaNeural) និង ប្រុស (en-US-GuyNeural)
        voice = "en-US-AriaNeural" if i % 2 == 0 else "en-US-GuyNeural"
        temp_audio_path = f"downloads/temp_{i}.mp3"

        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(temp_audio_path)

        segment_audio = AudioSegment.from_mp3(temp_audio_path)
        final_audio += segment_audio
        current_pos = start_ms + len(segment_audio)

        if os.path.exists(temp_audio_path):
            os.remove(temp_audio_path)

    output_path = "downloads/timed_output.mp3"
    final_audio.export(output_path, format="mp3")

    await update.message.reply_audio(audio=open(output_path, 'rb'), caption="🎙️ សំឡេងអានត្រូវតាមវិនាទី (ប្រុស/ស្រី) បានរួចរាល់!")

# ២. Function Transcribe MP3 / MP4 ទៅជា Text
async def handle_transcript(update: Update, context: ContextTypes.DEFAULT_TYPE):
    media = update.message.audio or update.message.video or update.message.document
    if not media:
        return
        
    file = await context.bot.get_file(media.file_id)
    file_path = "downloads/media_file.mp4"
    os.makedirs("downloads", exist_ok=True)
    await file.download_to_drive(file_path)

    await update.message.reply_text("🎧 កំពុង Transcribe អូឌីយ៉ូ/វីដេអូ សូមរង់ចាំបន្តិច...")
    model = whisper.load_model("base")
    result = model.transcribe(file_path)

    output_txt = "downloads/transcript.txt"
    with open(output_txt, 'w', encoding='utf-8') as f:
        f.write(result["text"])

    await update.message.reply_document(document=open(output_txt, 'rb'), caption="📝 Transcribe រួចរាល់!")

telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.Document.FileExtension("srt"), handle_srt_to_timed_audio))
telegram_app.add_handler(MessageHandler(filters.AUDIO | filters.VIDEO, handle_transcript))

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
