# Telegram SRT / Audio Bot

Bot នេះមានមុខងារ ៣:
1. **SRT -> Audio** — អានឯកសារ `.srt` ចេញជាសំឡេង ដោយឆ្លាស់សំឡេងប្រុស/ស្រី និងតម្រឹមតាមពេលវេលា (timestamp) ក្នុងឯកសារដើម
2. **បកប្រែ SRT ជាភាសាខ្មែរ** — បកប្រែខ្លឹមសារក្នុង `.srt` ទៅជាភាសាខ្មែរ ដោយរក្សា timestamp ដដែល
3. **Transcribe MP3/MP4** — ស្តាប់ឯកសារសំឡេង/វីដេអូ ហើយសរសេរជាអត្ថបទ + ឯកសារ `.srt`

## តម្រូវការ (Requirements)

- Python 3.10+
- **ffmpeg** ត្រូវដំឡើងក្នុងម៉ាស៊ីន (សម្រាប់ pydub និងការទាញយក audio ពី video)
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Windows: download ពី https://ffmpeg.org/download.html ហើយដាក់ក្នុង PATH

## ការដំឡើង (Installation)

```bash
# 1) បង្កើត virtual environment (មិនចាំបាច់ ប៉ុន្តែផ្តល់អនុសាសន៍)
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate

# 2) ដំឡើង library ទាំងអស់
pip install -r requirements.txt
```

## ការកំណត់ Token

1. បើក Telegram ស្វែងរក **@BotFather**
2. វាយ `/newbot` រួចធ្វើតាមការណែនាំ ដើម្បីទទួលបាន **Bot Token**
3. Copy ឯកសារ `.env.example` ទៅជា `.env`
4. ដាក់ token ចូលទៅក្នុង `.env`:

```
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRstuVwxyZ
```

## រត់ Bot

```bash
python bot.py
```

បើឃើញ log "Bot កំពុងដំណើរការ..." មានន័យថា bot ដំណើរការជោគជ័យហើយ។ សូមចូល Telegram រកឈ្មោះ bot របស់អ្នក ហើយវាយ `/start`។

## របៀបប្រើប្រាស់

1. វាយ `/start` — នឹងឃើញ menu ជាប៊ូតុង ៣ ជម្រើស
2. ចុចជ្រើសរើសមុខងារ
3. ផ្ញើឯកសារតាមតម្រូវការ (`.srt` សម្រាប់ជម្រើសទី ១,២ / `.mp3` ឬ `.mp4` សម្រាប់ជម្រើសទី ៣)
4. រង់ចាំ bot ដំណើរការ រួចទទួលលទ្ធផលត្រឡប់មកវិញ

## ចំណាំសំខាន់ៗ

- **សំឡេង TTS**: ប្រើ Microsoft Edge TTS (`edge-tts`) ដែលឥតគិតថ្លៃ។ សំឡេងខ្មែរប្រើ:
  - ស្រី: `km-KH-SreymomNeural`
  - ប្រុស: `km-KH-PisethNeural`
  - តក្កវិជ្ជាឆ្លាស់សំឡេងស្ថិតនៅក្នុងអនុគមន៍ `pick_voice()` ក្នុងឯកសារ `srt_audio.py` — អ្នកអាចកែសម្រួលបាន (ឧ. ផ្អែកលើ speaker tag ជាក់លាក់ជាងនេះ)
- **Transcribe**: ប្រើ `faster-whisper` ម៉ូឌែល `medium` ជាលំនាំដើម។ ប្រសិនបើម៉ាស៊ីនយឺត អាចប្តូរទៅ `small` ឬ `base` ក្នុងឯកសារ `bot.py` (function `handle_transcribe`, argument `model_size`)។ លើកដំបូងហៅ វានឹង download ម៉ូឌែលដោយស្វ័យប្រវត្តិ (ត្រូវការ internet)
- **កំណត់ទំហំឯកសារ**: Telegram Bot API កំណត់ទំហំ upload/download នៅប្រហែល 20MB (download) និង 50MB (upload) ។ សម្រាប់ឯកសារធំជាងនេះ ត្រូវប្រើ Local Bot API Server ដោយឡែក
- **ល្បឿនដំណើរការ**: TTS និង Whisper ប្រើពេលតាមទំហំឯកសារ — ឯកសារវែងអាចចំណាយពេលច្រើននាទី

## Deploy លើ Render (តាមរយៈ GitHub, ធ្វើពី iOS បាន)

ជំហានទាំងនេះមិនត្រូវការ terminal ឬកុំព្យូទ័រទេ — ធ្វើតាមរយៈ browser លើ iPhone/iPad បាន។

### ជំហានទី ១ — Push code ចូល GitHub

1. បើក GitHub app (ឬ website github.com) លើ iOS
2. បង្កើត repository ថ្មី (public ឬ private ក៏បាន) ឧ. ឈ្មោះ `telegram-srt-bot`
3. Upload ឯកសារទាំងអស់ខាងក្រោមចូល repo (ចុច "Add file" → "Upload files" លើ website version, ងាយជាងធ្វើលើ Safari ជាង app):
   - `bot.py`, `srt_audio.py`, `srt_translate.py`, `transcribe.py`
   - `requirements.txt`, `Dockerfile`, `.gitignore`, `render.yaml`
   - **កុំ** upload `.env` (ព័ត៌មាន token សម្ងាត់) — Render នឹងសុំវាដោយឡែក

### ជំហានទី ២ — ភ្ជាប់ទៅ Render

1. ចូល https://render.com ចុះឈ្មោះ/login (អាចប្រើ GitHub account ចូលផ្ទាល់)
2. ចុច **New +** → **Web Service**
3. ជ្រើសរើស connect GitHub repository ដែលទើប upload
4. Render នឹងឃើញ `Dockerfile` ដោយស្វ័យប្រវត្តិ ជ្រើសរើស **Runtime: Docker**
5. ជ្រើសរើស **Plan: Free**
6. នៅក្នុងផ្នែក **Environment Variables** បន្ថែម:
   - Key: `BOT_TOKEN` — Value: token ដែលទទួលបានពី @BotFather
   - Key: `WHISPER_MODEL_SIZE` — Value: `small` (ឬ `base` បើចង់លឿនជាង)
7. ចុច **Create Web Service**

Render នឹង build និង deploy ដោយស្វ័យប្រវត្តិ (ចំណាយពេលប្រហែល ៣-៨ នាទីលើកដំបូង ព្រោះត្រូវ download ffmpeg + libraries)។ នៅពេលឃើញ log "Bot កំពុងដំណើរការ..." មានន័យថារួចរាល់។

### ចំណុចសំខាន់អំពី Render Free Tier

- **Free Web Service នៅលក់ដេក (sleep) បន្ទាប់ពី 15 នាទីគ្មានចរាចរណ៍ web traffic** — ព្រោះ bot នេះមិនមាន visitor ធម្មតាទេ (គ្រាន់តែ health-check endpoint) វាអាចនៅដេកលក់ ហើយ Telegram bot នឹងឈប់ឆ្លើយតប រហូតដល់មាន request ថ្មីមក wake វា
  - ដំណោះស្រាយ៖ ប្រើសេវាឥតគិតថ្លៃដូចជា **UptimeRobot** ឬ **cron-job.org** ដើម្បី ping URL របស់ Render service (Render ផ្តល់ URL ជូនស្វ័យប្រវត្តិ ឧ. `https://telegram-srt-bot.onrender.com`) រៀងរាល់ ១០-១៤ នាទីម្តង ដើម្បីរក្សា service ឲ្យភ្ញាក់ជានិច្ច
  - ឬប្រើ **Render paid plan** ($7/ខែឡើងទៅ) ដែលមិនដេកលក់
- **RAM 512MB (free tier)**: បើ `faster-whisper` model ធំពេក (medium/large) អាចធ្វើឲ្យ service crash ដោយសារអស់ memory — ប្រើ `small` ឬ `base` សម្រាប់ free tier
- រាល់ដងដែល redeploy ឬ service restart, whisper model ត្រូវ download ម្តងទៀត (ចំណាយពេលបន្តិច តែធម្មតា)

### កែប្រែ code នាពេលក្រោយ (ពី iOS)

ប្រើ GitHub website (Safari) ឬ app ដើម្បីកែឯកសារដោយផ្ទាល់ (ចុច pencil icon លើឯកសារ → កែ → Commit) ។ រាល់ commit ថ្មីទៅ branch main, Render នឹង **redeploy ដោយស្វ័យប្រវត្តិ**។

## រចនាសម្ព័ន្ធឯកសារ

```
telegram_srt_bot/
├── bot.py              # ចំណុចចូល Telegram bot (handlers + health-check server)
├── srt_audio.py         # SRT -> Audio (TTS + timing alignment)
├── srt_translate.py      # SRT -> ការបកប្រែជាភាសាខ្មែរ
├── transcribe.py        # MP3/MP4 -> Text/SRT (faster-whisper)
├── requirements.txt
├── Dockerfile            # សម្រាប់ deploy លើ Render (មាន ffmpeg)
├── render.yaml           # Render Blueprint (optional, one-click config)
├── .gitignore
├── .env.example
└── README.md
```
