# SRT → Voice Telegram Bot (ភាសាខ្មែរ)

Bot Telegram ដែលបំលែងឯកសារ `.srt` ទៅជាឯកសារសំឡេង `.mp3` ដោយប្រើសំឡេង Neural
ភាសាខ្មែរគុណភាពខ្ពស់ (ឥតគិតថ្លៃ) តាមរយៈ **edge-tts**:

- 👨 **Piseth** — សំឡេងប្រុស (`km-KH-PisethNeural`)
- 👩 **Sreymom** — សំឡេងស្រី (`km-KH-SreymomNeural`)

សំឡេងចេញមកនឹងចាប់ផ្តើម/បញ្ចប់ត្រូវតាមពេលវេលា (timestamp) នៃឯកសារ SRT
(បើបន្ទាត់ណាមួយនិយាយវែងជាងចន្លោះពេលកំណត់ ខ្លួន Bot នឹងបង្រួញល្បឿននិយាយបន្តិច
ដើម្បីរក្សាពេលវេលាឲ្យជិតទៅតាម SRT ដដែល)។

## រចនាសម្ព័ន្ធឯកសារ

```
srt-tts-bot/
├── bot.py            # កូដសំខាន់របស់ bot
├── requirements.txt  # library ដែលត្រូវការ
├── Dockerfile        # សម្រាប់ deploy (មាន ffmpeg)
├── render.yaml        # config សម្រាប់ deploy លើ Render
└── README.md
```

## ១. រៀបចំ Telegram Bot

1. ចាក់សារទៅ [@BotFather](https://t.me/BotFather) លើ Telegram
2. វាយ `/newbot` រួចធ្វើតាមការណែនាំ
3. ចម្លង **Bot Token** ដែលបានមក (ឧទាហរណ៍ `123456:ABC-...`)

## ២. សាកល្បងលើម៉ាស៊ីនផ្ទាល់ខ្លួន (Local)

ត្រូវការ Python 3.11+ និង `ffmpeg` ដំឡើងក្នុងម៉ាស៊ីន:

```bash
# ដំឡើង ffmpeg (Ubuntu/Debian)
sudo apt-get install ffmpeg

# ដំឡើង library
pip install -r requirements.txt

# កំណត់ token
export BOT_TOKEN="ដាក់_token_របស់អ្នក_នៅទីនេះ"

# run
python bot.py
```

បើ run ជោគជ័យ Bot នឹងចាប់ផ្តើមក្នុងរបៀប polling ដោយស្វ័យប្រវត្តិ
(ព្រោះមិនមាន `RENDER_EXTERNAL_URL`)។

## ៣. Deploy លើ Render (Free Tier)

### របៀបទី១៖ ប្រើ Blueprint (ងាយបំផុត)

1. Upload code នេះទៅ GitHub repository ថ្មីមួយ
2. ចូល [Render Dashboard](https://dashboard.render.com/) → **New** → **Blueprint**
3. ភ្ជាប់ទៅ repository របស់អ្នក (Render នឹងអាន `render.yaml` ដោយស្វ័យប្រវត្តិ)
4. នៅពេលសួររក environment variable `BOT_TOKEN` សូមបំពេញ token ពី BotFather
5. ចុច **Apply** — Render នឹង build image ពី `Dockerfile` ហើយ deploy ជា Web Service

### របៀបទី២៖ បង្កើត Web Service ដោយដៃ

1. Push code ទៅ GitHub
2. Render Dashboard → **New** → **Web Service**
3. ជ្រើសរើស repository → Environment ជ្រើសរើស **Docker**
4. Plan ជ្រើសរើស **Free**
5. Environment Variables → បន្ថែម `BOT_TOKEN` = token របស់អ្នក
6. ចុច **Create Web Service**

Render នឹងផ្តល់ URL ជូនស្វ័យប្រវត្តិ (`RENDER_EXTERNAL_URL`) ដែល `bot.py`
ប្រើដើម្បីចុះឈ្មោះ webhook ដោយស្វ័យប្រវត្តិ — មិនចាំបាច់កំណត់អ្វីបន្ថែមទេ។

### ចំណាំសំខាន់អំពី Render Free Tier

- សេវា Free នឹង **ដេកលក់ (sleep)** បន្ទាប់ពីគ្មានចរាចរណ៍ ~15 នាទី ហើយនឹងចំណាយពេល
  ប្រហែល 30-60 វិនាទីដើម្បីភ្ញាក់ឡើងវិញនៅពេលមានសារចូលថ្មី។
- ដើម្បីជៀសវាងបញ្ហានេះ អ្នកអាចប្រើសេវា ping (ដូចជា UptimeRobot) ឲ្យចូលមើល
  URL របស់ Bot រៀងរាល់ ១០ នាទីម្តង ដើម្បីរក្សា Bot ឲ្យភ្ញាក់ជានិច្ច។

## ៤. របៀបប្រើប្រាស់ Bot

1. ស្វែងរក Bot របស់អ្នកលើ Telegram រួច `/start`
2. ផ្ញើឯកសារ `.srt`
3. ចុចជ្រើសរើសសំឡេង **ប្រុស (Piseth)** ឬ **ស្រី (Sreymom)**
4. រង់ចាំ Bot ដំណើរការ (រយៈពេលអាស្រ័យលើប្រវែងឯកសារ) រួច Bot នឹងផ្ញើឯកសារ
   `.mp3` ត្រឡប់មកវិញ

## ចំណុចអាចកែលម្អបន្ថែម (ស្រេចចិត្ត)

- បន្ថែម progress update រៀងរាល់ N បន្ទាត់ សម្រាប់ឯកសារវែងៗ
- បន្ថែមជម្រើសបញ្ចេញជា `.wav` ជំនួស `.mp3`
- ដាក់ queue/database សម្រាប់អ្នកប្រើច្រើននាក់ក្នុងពេលតែមួយ
- ប្រើ Redis/Postgres ជំនួស dict ក្នុងសតិ (`user_files`) បើចង់ scale ធំ
