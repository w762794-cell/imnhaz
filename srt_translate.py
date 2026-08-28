"""
srt_translate.py
-----------------
បកប្រែខ្លឹមសារនៅក្នុងឯកសារ SRT ទៅជាភាសាខ្មែរ ខណៈពេលរក្សា timestamp ដដែល។
ប្រើ deep-translator (Google Translate engine, ឥតគិតថ្លៃ គ្មានត្រូវការ API key)។
"""

import srt
from deep_translator import GoogleTranslator
from srt_audio import parse_srt_file


def translate_srt_file(in_path: str, out_path: str, target_lang: str = "km") -> str:
    subs = parse_srt_file(in_path)
    translator = GoogleTranslator(source="auto", target=target_lang)

    new_subs = []
    for sub in subs:
        original_text = sub.content.strip()
        if not original_text:
            translated_text = original_text
        else:
            try:
                translated_text = translator.translate(original_text)
            except Exception:
                # ប្រសិនបើ translate បរាជ័យសម្រាប់បន្ទាត់ណាមួយ រក្សាអត្ថបទដើមវិញ
                translated_text = original_text

        new_subs.append(
            srt.Subtitle(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                content=translated_text,
            )
        )

    result = srt.compose(new_subs)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)

    return out_path
