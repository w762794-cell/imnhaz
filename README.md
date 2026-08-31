# Khmer SRT → Voice Telegram Bot (ឥតគិតថ្លៃ)

Bot នេះទទួលឯកសារ `.srt` ហើយបំប្លែងទៅជាឯកសារសំឡេង MP3 ជាភាសាខ្មែរ
ដោយប្រើ **edge-tts** — library ដែលទាញយកសំឡេងពី Microsoft Edge browser
(feature "Read aloud") ដោយ**ឥតគិតថ្លៃ និងមិនត្រូវការ API key ឬគណនី Azure ទេ**។
វាប្រើ voice neural ដូចគ្នាបេះបិទនឹង Azure:

- **km-KH-PisethNeural** — សំឡេងប្រុស
- **km-KH-SreymomNeural** — សំឡេងស្រី

មិនចាំបាច់ចុះឈ្មោះ Azure, Google Cloud ឬដាក់ credit card អ្វីទាំងអស់។

## របៀបកំណត់ភេទសំឡេងក្នុង SRT

លំនាំដើម bot នឹងឆ្លាស់ប្រុស/ស្រីស្វ័យប្រវត្តិតាមលេខបន្ទាត់ subtitle។
បើចង់កំណត់ច្បាស់លាស់ ដាក់ prefix នៅដើមបន្ទាត់ក្នុងឯកសារ .srt:

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

## Deploy លើ Render (ឥតគិតថ្លៃ)

1. Push ថតឯកសារនេះទាំងអស់ (`bot.py`, `requirements.txt`, `Dockerfile`, `render.yaml`)
   ទៅ GitHub repository មួយ (អាចធ្វើពី GitHub app លើទូរសព្ទ ឬ github.com)។

2. ចូល [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint**,
   ភ្ជាប់ទៅ repository នោះ។ Render នឹងអាន `render.yaml` ហើយបង្កើត
   **Background Worker** service ស្វ័យប្រវត្តិ ជាមួយ **Free plan**
   (មិនត្រូវការ web port ព្រោះ bot ប្រើ polling មិនមែន webhook)។

3. ក្នុងផ្ទាំង Environment របស់ service កំណត់តម្លៃ variable មួយគត់៖
   - `TELEGRAM_BOT_TOKEN`

4. ចុច **Deploy**។ Render នឹង build Docker image (ដំឡើង ffmpeg ស្វ័យប្រវត្តិ)
   ហើយចាប់ផ្ដើម bot ជាមួយ `python bot.py`។

5. បើក Telegram ស្វែងរក bot របស់អ្នក ផ្ញើ `/start` រួចផ្ញើឯកសារ `.srt` ដើម្បីសាកល្បង។

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
- Render free plan នៅសម្រាកបន្ទាប់ពី idle រយៈពេលមួយ ដូច្នេះលើកដំបូងបន្ទាប់ពី
  idle ការឆ្លើយតបអាចយឺតបន្តិច។
- បើ subtitle វែងជាងចន្លោះពេលកំណត់ (start-end) សំឡេងអាចលើសពេលដែលកំណត់
  ក្នុង .srt បន្តិច — bot នេះតម្រៀបតាមចំណុចចាប់ផ្ដើម (start time) មិនកាត់ឬបង្រួមល្បឿនសំឡេងទេ។
