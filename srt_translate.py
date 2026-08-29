"""
srt_translate.py
-----------------
បកប្រែខ្លឹមសារនៅក្នុងឯកសារ SRT ទៅជាភាសាខ្មែរ ខណៈពេលរក្សា timestamp ដដែល។
ប្រើ deep-translator (Google Translate engine, ឥតគិតថ្លៃ គ្មានត្រូវការ API key)។
"""

import time
import srt
from deep_translator import GoogleTranslator
from srt_audio import parse_srt_file


def _is_valid_translation(text) -> bool:
    """ពិនិត្យថាតើលទ្ធផលដែលទទួលបានមើលទៅសមហេតុផលឬអត់ (មិនមែន None/empty/error page)"""
    if not text or not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped:
        return False
    # Google Translate ដែលត្រូវបានទប់ស្កាត់ (rate-limit) ជាធម្មតាត្រឡប់ HTML/error markers
    lowered = stripped.lower()
    error_markers = ("<html", "<!doctype", "error", "too many requests", "blocked")
    if any(marker in lowered for marker in error_markers) and len(stripped) < 200:
        # អត្ថបទខ្លីៗដែលមាន keyword ទាំងនេះទំនងជា error មិនមែនការបកប្រែពិតទេ
        # (ខ្លីជាង 200 តួ ដើម្បីជៀសវាងច្រឡំជាមួយអត្ថបទដើមដែលចៃដន្យមាន "error" ក្នុងន័យផ្សេង)
        return False
    return True


def translate_srt_file(in_path: str, out_path: str, target_lang: str = "km",
                        max_retries: int = 2, delay_seconds: float = 0.4) -> str:
    subs = parse_srt_file(in_path)
    translator = GoogleTranslator(source="auto", target=target_lang)

    new_subs = []
    for sub in subs:
        original_text = sub.content.strip()

        if not original_text:
            translated_text = original_text
        else:
            translated_text = None
            for attempt in range(max_retries + 1):
                try:
                    result = translator.translate(original_text)
                    if _is_valid_translation(result):
                        translated_text = result
                        break
                except Exception:
                    pass

                # បរាជ័យ ឬលទ្ធផលមិនត្រឹមត្រូវ -> សម្រាកបន្តិចមុនសាកល្បងម្តងទៀត
                # (ជៀសវាង rate-limit ពី Google Translate)
                if attempt < max_retries:
                    time.sleep(delay_seconds * (attempt + 1))

            if translated_text is None:
                # ព្យាយាមអស់ចំនួនដងកំណត់ហើយ នៅតែបរាជ័យ -> រក្សាអត្ថបទដើមវិញ
                # (ជៀសវាងកុំឲ្យ error text ចូល file)
                translated_text = original_text

            # ពន្យារពេលបន្តិចរវាងបន្ទាត់នីមួយៗ ជៀសវាង Google Translate ទប់ស្កាត់
            # ដោយសារ request ញឹកញាប់ពេក
            time.sleep(delay_seconds)

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
