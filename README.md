# Khmer SRT → Voice Telegram Bot (ឥតគិតថ្លៃ)

Bot នេះទទួលឯកសារ `.srt` ហើយបំប្លែងទៅជាឯកសារសំឡេង MP3 ជាភាសាខ្មែរ
ដោយប្រើ **edge-tts** — library ដែលទាញយកសំឡេងពី Microsoft Edge browser
(feature "Read aloud") ដោយ**ឥតគិតថ្លៃ និងមិនត្រូវការ API key ឬគណនី Azure ទេ**។
វាប្រើ voice neural ដូចគ្នាបេះបិទនឹង Azure:

- **km-KH-PisethNeural** — សំឡេងប្រុស
- **km-KH-SreymomNeural** — សំឡេងស្រី

មិនចាំបាច់ចុះឈ្មោះ Azure, Google Cloud ឬដាក់ credit card អ្វីទាំងអស់។

## របៀបប្រើ

ផ្ញើឯកសារ `.srt` ទៅ bot នឹងបង្ហាញ button ៣ ជម្រើសឲ្យចុច៖

- **👨 ប្រុស (Piseth)** — អានគ្រប់បន្ទាត់ដោយសំឡេងប្រុស
- **👩 ស្រី (Sreymom)** — អានគ្រប់បន្ទាត់ដោយសំឡេងស្រី
- **🔀 ឆ្លាស់ស្វ័យប្រវត្តិ** — ឆ្លាស់ប្រុស/ស្រីតាមលេខបន្ទាត់ស្វ័យប្រវត្តិ

## របៀបកំណត់ភេទសំឡេងច្រើនក្នុងឯកសារតែមួយ

បើផ្ញើឯកសារជាមួយ [M]/[F] ស្រាប់ បន្ទាត់ដែលមាន marker នេះនឹងប្រើសំឡេងដែលកំណត់
ជានិច្ច ទោះបីជាចុច button ប្រុសឬស្រីក៏ដោយ (marker សុទ្ធតែសំខាន់ជាង button)។
ដាក់ prefix នៅដើមបន្ទាត់ក្នុងឯកសារ .srt:

```
1
00:00:01,000 --> 00:00:03,000
[M] សួស្តី តើអ្នកសុខសប្បាយទេ?

2
00:00:03,500 --> 00:00:06,000
[F] ខ្ញុំសុខសប្បាយ អរគុណ!
```

## អ្វីដែលត្រូវការមុនចាប់ផ្ដើម

មានតែមួយយ៉ាងគត់៖ **Telegram Bot Token**
— បង្កើត bot ជាមួយ [@BotFather](https://t.me/BotFather) ក្នុង Telegram
ដោយវាយ `/newbot` ហើយចម្លង token ដែលបានមក។ (ធ្វើពីទូរសព្ទបានស្រួល)

## Deploy លើ Render (ឥតគិតថ្លៃ ១០០%)

1. Push ថតឯកសារនេះទាំងអស់ (`bot.py`, `requirements.txt`, `Dockerfile`, `render.yaml`)
   ទៅ GitHub repository មួយ (អាចធ្វើពី GitHub app លើទូរសព្ទ ឬ github.com)។

2. ចូល [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**,
   ភ្ជាប់ទៅ repository នោះ។ Render នឹងអាន `render.yaml` ហើយបង្កើត
   **Web Service** ជាមួយ **Free plan** ស្វ័យប្រវត្តិ
   (Render មិនផ្ដល់ Free plan សម្រាប់ Background Worker ទេ ដូច្នេះ bot នេះប្រើ
   Web Service ជំនួសវិញ ជាមួយ health-check server តូចមួយក្នុង `bot.py`
   ដើម្បីបំពេញលក្ខខណ្ឌ "port" របស់ Render — ខាងក្នុងវានៅតែជា Telegram polling ធម្មតា)។

3. ក្នុងផ្ទាំង Environment របស់ service កំណត់តម្លៃ variable មួយគត់៖
   - `TELEGRAM_BOT_TOKEN`

4. ចុច **Deploy**។ Render នឹង build Docker image (ដំឡើង ffmpeg ស្វ័យប្រវត្តិ)
   ហើយចាប់ផ្ដើម bot ជាមួយ `python bot.py`។

5. បើក Telegram ស្វែងរក bot របស់អ្នក ផ្ញើ `/start` រួចផ្ញើឯកសារ `.srt` ដើម្បីសាកល្បង។

## កុំឲ្យ bot ដេកលក់ (សំខាន់សម្រាប់ Free plan)

Free Web Service លើ Render **ដេកលក់ស្វ័យប្រវត្តិបន្ទាប់ពី ១៥ នាទីគ្មាន traffic**។
Bot ខាងក្នុងធ្វើ Telegram polling ដដែល តែ Render មិនដឹងថាមាន traffic ចូល
ក្រៅពី HTTP request ទេ ដូច្នេះត្រូវការសេវាឥតគិតថ្លៃមួយមកជូត (ping) URL របស់
service រៀងរាល់ ~ ១០ នាទី៖

1. ចម្លង URL សាធារណៈរបស់ service (មើលនៅផ្នែកខាងលើ Render Dashboard ជា
   `https://xxxxx.onrender.com`)
2. ចុះឈ្មោះឥតគិតថ្លៃនៅ [UptimeRobot](https://uptimerobot.com) ឬ
   [cron-job.org](https://cron-job.org)
3. បង្កើត monitor/job ថ្មី ដាក់ URL ខាងលើ កំណត់ឲ្យ ping រៀងរាល់ ៥-១០ នាទី

បើមិនធ្វើជំហាននេះទេ bot នៅតែដំណើរការបាន ប៉ុន្តែនឹងឆ្លើយយឺត (30-60 វិនាទី)
ពេលដំបូងក្រោយពេលមិនប្រើរយៈពេលយូរ ព្រោះ Render ត្រូវពេលដើម្បីភ្ញាក់ឡើងវិញ។

## ដំណើរការនៅ local (សាកល្បង ជាជម្រើស)

```bash
pip install -r requirements.txt
# ffmpeg ត្រូវតែដំឡើងក្នុងម៉ាស៊ីនផងដែរ (apt install ffmpeg / brew install ffmpeg)

export TELEGRAM_BOT_TOKEN="xxxx"
python bot.py
```

## កំណត់ចំណាំ

- edge-tts ជា service ដែល Microsoft មិនបានចេញផ្សាយជា public API ផ្លូវការទេ
  (community reverse-engineer ពី Edge browser) — ដូច្នេះវាមិនធានាឋិតថេរ 100%
  រយៈពេលវែងទេ បើ Microsoft ប្តូរអ្វីមួយ។ ប៉ុន្តែបច្ចុប្បន្នមានស្ថេរភាពល្អ
  និងត្រូវបានគេប្រើប្រាស់យ៉ាងទូលំទូលាយ។
- Render free plan នៅសម្រាកបន្ទាប់ពី idle រយៈពេលមួយ (សូមមើលផ្នែក "កុំឲ្យ bot
  ដេកលក់" ខាងលើ)។
- Render free Web Service មិនអនុញ្ញាតឲ្យប្ដូរជា Background Worker ក្រោយ
  deploy រួចទេ បើចង់ប្ដូរត្រូវលុបហើយបង្កើត service ថ្មី។
