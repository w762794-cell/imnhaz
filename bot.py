import os
import asyncio
import edge_tts
import whisper
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from deep_translator import GoogleTranslator

# កំណត់ Token របស់ Telegram Bot របស់អ្នកនៅទីនេះ
TELEGRAM_BOT_TOKEN = "8820637952:AAHpabuhIsWJccfmcHUYUL2NOO892SX8a7o"

# 1. Function សម្រាប់បម្លែង SRT ទៅជា Audio (សំឡេងប្រុស និង ស្រី)
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

    await update.message.reply_text("⏳ កំពុងដំណើរការបង្កើតសំឡេង (ប្រុស និង ស្រី)...")

    # អានဖိုင် SRT និងបម្លែង (ឧទាហរណ៍ជ្រើសរើសសំឡេង ស្រី: en-US-AriaNeural, ប្រុស: en-US-GuyNeural)
    female_voice = "en-US-AriaNeural"
    male_voice = "en-US-GuyNeural"
    
    output_audio = "downloads/output_audio.mp3"
    
    with open(file_path, 'r', encoding='utf-8') as f:
        srt_content = f.read()

    # បម្លែងអត្ថបទក្នុង SRT ទៅជាសំឡេង (អាចកែសម្រួលដើម្បីបែងចែក Speaker តាមតម្រូវការ)
    await text_to_speech(srt_content, female_voice, output_audio)
    
    await update.message.reply_audio(audio=open(output_audio, 'rb'), caption="🎙️ សំឡេងបានរួចរាល់!")

# 2. Function បកប្រែ SRT ជាភាសាខ្មែរ
async def handle_translate_srt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document.file_name.endswith('.srt'):
        await update.message.reply_text("សូមផ្ញើឯកសារ .srt ដើម្បីបកប្រែ!")
        return

    file = await context.bot.get_file(document.file_id)
    file_path = f"downloads/{document.file_name}"
    os.makedirs("downloads", exist_ok=True)
    await file.download_to_drive(file_path)

    await update.message.reply_text("🌐 កំពុងបកប្រែ SRT ទៅជាភាសាខ្មែរ...")

    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    translated_lines = []
    translator = GoogleTranslator(source='auto', target='km')

    for line in lines:
        # រំលងលេខលំដាប់ និងតាមកាលវិនាទីរបស់ SRT
        if '-->' in line or line.strip().isdigit() or not line.strip():
            translated_lines.append(line)
        else:
            try:
                translated = translator.translate(line.strip())
                translated_lines.append(translated + "\n")
            except:
                translated_lines.append(line)

    output_path = "downloads/translated_km.srt"
    with open(output_path, 'w', encoding='utf-8') as f:
        f.writelines(translated_lines)

    await update.message.reply_document(document=open(output_path, 'rb'), caption="🇰🇭 SRT បកប្រែជាភាសាខ្មែរជោគជ័យ!")

# 3. Function Transcribe MP3 / MP4 ទៅជា Text
async def handle_transcript(update: Update, context: ContextTypes.DEFAULT_TYPE):
    media = update.message.audio or update.message.video or update.message.document
    if not media:
        await update.message.reply_text("សូមផ្ញើឯកសារ MP3 ឬ MP4 មក!")
        return

    file = await context.bot.get_file(media.file_id)
    file_path = f"downloads/{media.file_name if hasattr(media, 'file_name') else 'media.mp4'}"
    os.makedirs("downloads", exist_ok=True)
    await file.download_to_drive(file_path)

    await update.message.reply_text("🎧 កំពុង Transcribe អូឌីយ៉ូ/វីដេអូ (សូមរង់ចាំបន្តិច)...")

    # ប្រើ OpenAI Whisper សម្រាប់ Transcribe
    model = whisper.load_model("base")
    result = model.transcribe(file_path)

    output_txt = "downloads/transcript.txt"
    with open(output_txt, 'w', encoding='utf-8') as f:
        f.write(result["text"])

    await update.message.reply_document(document=open(output_txt, 'rb'), caption="📝 អត្ថបទ Transcribe បានរួចរាល់!")

# កូដចាប់ផ្តើម Bot
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", lambda u, c: u.message.reply_text("សួស្តី! សូមផ្ញើឯកសារ SRT, MP3 ឬ MP4 មកកាន់ Bot ដើម្បីចាប់ផ្តើម។")))
    app.add_handler(MessageHandler(filters.Document.FileExtension("srt"), handle_srt_to_audio)) # អាចប្តូរតាម Command ពេលជាក់ស្តែង
    app.add_handler(MessageHandler(filters.AUDIO | filters.VIDEO, handle_transcript))

    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
