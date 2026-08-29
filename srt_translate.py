"""
srt_translate.py
-----------------
បកប្រែខ្លឹមសារនៅក្នុងឯកសារ SRT ទៅជាភាសាខ្មែរ ខណៈពេលរក្សា timestamp ដដែល។
ប្រើ deep-translator ជាមួយ engine ២ (Google Translate ជាចម្បង, MyMemory ជា fallback)
ដើម្បីបង្កើនឱកាសបកប្រែជោគជ័យ ១០០% ព្រោះ Google Translate ឥតគិតថ្លៃមួយម្នាក់ឯង
ជួនកាល rate-limit លើ cloud server (ដូចជា Render) ។
"""

import time
import srt
from deep_translator import GoogleTranslator, MyMemoryTranslator
from srt_audio import parse_srt_file


def _is_valid_translation(text) -> bool:
    """ពិនិត្យថាតើលទ្ធផលដែលទទួលបានមើលទៅសមហេតុផលឬអត់ (មិនមែន None/empty/error page)"""
    if not text or not isinstance(text, str):
        return False
    stripped = text.strip()
    if not stripped:
        return False
    # Server ដែលត្រូវបានទប់ស្កាត់ (rate-limit) ជាធម្មតាត្រឡប់ HTML/error markers
    lowered = stripped.lower()
    error_markers = (
        "<html", "<!doctype", "error", "too many requests", "blocked",
        "quota", "mymemory warning", "internal server error",
        "please try again", "bad request",
    )
    if any(marker in lowered for marker in error_markers) and len(stripped) < 250:
        # អត្ថបទខ្លីៗដែលមាន keyword ទាំងនេះទំនងជា error មិនមែនការបកប្រែពិតទេ
        # (ខ្លីជាង 250 តួ ដើម្បីជៀសវាងច្រឡំជាមួយអត្ថបទដើមដែលចៃដន្យមាន "error" ក្នុងន័យផ្សេង)
        return False
    return True


def _translate_with_retries(translator, text: str, max_retries: int, delay_seconds: float):
    """ព្យាយាមបកប្រែម្តងមួយ engine ដោយ retry ជាច្រើនដង។ ត្រឡប់ None បើបរាជ័យទាំងអស់"""
    for attempt in range(max_retries + 1):
        try:
            result = translator.translate(text)
            if _is_valid_translation(result):
                return result
        except Exception:
            pass
        if attempt < max_retries:
            time.sleep(delay_seconds * (attempt + 1))
    return None


def translate_srt_file(in_path: str, out_path: str, target_lang: str = "km",
                        max_retries: int = 3, delay_seconds: float = 0.6,
                        progress_cb=None) -> str:
    """
    progress_cb: function(current_index, total_lines) ដែលហៅរាល់ពេលបន្ទាត់មួយចប់
    សម្រាប់ report ភាគរយត្រឡប់ទៅ caller (ឧ. Telegram bot)។
    """
    subs = parse_srt_file(in_path)
    total = len(subs)

    # --- ២ engine ដាច់ដោយឡែក, ប្រើជា fallback គ្នាទៅវិញទៅមក ---
    google_translator = GoogleTranslator(source="auto", target=target_lang)
    try:
        mymemory_translator = MyMemoryTranslator(source="auto", target=target_lang)
    except Exception:
        mymemory_translator = None  # បើ init បរាជ័យ (ឧ. mapping ភាសាមិនគាំទ្រ) រំលងវាទៅ

    new_subs = []
    for i, sub in enumerate(subs, start=1):
        original_text = sub.content.strip()

        if not original_text:
            translated_text = original_text
        else:
            # engine ទី ១: Google Translate
            translated_text = _translate_with_retries(
                google_translator, original_text, max_retries, delay_seconds
            )

            # engine ទី ២ (fallback): MyMemory បើ Google បរាជ័យទាំងស្រុង
            if translated_text is None and mymemory_translator is not None:
                translated_text = _translate_with_retries(
                    mymemory_translator, original_text, max_retries, delay_seconds
                )

            if translated_text is None:
                # ព្យាយាមអស់ engine ទាំង ២ ហើយនៅតែបរាជ័យ -> រក្សាអត្ថបទដើមវិញ
                # (ជៀសវាងកុំឲ្យ error text ចូល file)
                translated_text = original_text

            # ពន្យារពេលបន្តិចរវាងបន្ទាត់នីមួយៗ ជៀសវាង translator ទប់ស្កាត់
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

        if progress_cb:
            try:
                progress_cb(i, total)
            except Exception:
                pass  # error ក្នុង progress reporting មិនត្រូវធ្វើឲ្យ translate បរាជ័យទេ

    result = srt.compose(new_subs)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(result)

    return out_path
