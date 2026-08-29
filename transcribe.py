"""
transcribe.py
-------------
Transcribe MP3 / MP4 ទៅជា text និង SRT ដោយប្រើ faster-whisper (រត់លើ CPU ក៏បាន)។

សម្គាល់៖ លើកដំបូងដែលហៅ WhisperModel() វានឹង download model ដោយស្វ័យប្រវត្តិ
(ត្រូវការ internet លើកដំបូងតែប៉ុណ្ណោះ, ក្រោយមកនឹង cache ទុក)។
"""

import os
import subprocess
import srt
import datetime
from faster_whisper import WhisperModel

_MODEL_CACHE = {}


def get_model(model_size: str = "medium"):
    """Cache model ក្នុង memory ដើម្បីកុំបង្ខំ load ឡើងវិញរាល់ request"""
    if model_size not in _MODEL_CACHE:
        # compute_type="int8" ដើម្បីលឿន និងស៊ូជាមួយ CPU
        # cpu_threads=0 -> faster-whisper ស្វែងរកចំនួន core ដោយស្វ័យប្រវត្តិ ហើយប្រើអស់
        _MODEL_CACHE[model_size] = WhisperModel(
            model_size, device="cpu", compute_type="int8", cpu_threads=0
        )
    return _MODEL_CACHE[model_size]


def extract_audio_if_video(input_path: str, work_dir: str) -> str:
    """បើ file ជា mp4/video សូមទាញយក audio track ចេញជា wav ជាមុនសិន (ត្រូវការ ffmpeg)"""
    ext = os.path.splitext(input_path)[1].lower()
    if ext in (".mp3", ".wav", ".m4a", ".ogg"):
        return input_path

    out_wav = os.path.join(work_dir, "extracted_audio.wav")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-vn", "-ac", "1", "-ar", "16000", out_wav
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_wav


def transcribe_to_srt(input_path: str, out_srt_path: str, work_dir: str,
                       language: str = None, model_size: str = "medium",
                       progress_cb=None) -> str:
    """
    Transcribe audio/video ទៅជា SRT file។
    language=None -> ស្វែងរកភាសាដោយស្វ័យប្រវត្តិ

    progress_cb: function(current_seconds, total_seconds) ដែលហៅរាល់ពេលដំណើរការ
    segment មួយចប់ សម្រាប់ report ភាគរយត្រឡប់ទៅ caller (ឧ. Telegram bot)។
    ចំណាំ: function នេះនឹងត្រូវហៅពី background thread ដូច្នេះត្រូវធ្វើឲ្យវា
    thread-safe នៅខាង caller (ឧ. គ្រាន់តែសរសេរចូល dict/variable ធម្មតា)។
    """
    audio_path = extract_audio_if_video(input_path, work_dir)
    model = get_model(model_size)

    # --- ប៉ារ៉ាម៉ែត្រសម្រាប់បង្កើនល្បឿន (សំខាន់ខ្លាំងលើ Render free tier ដែល CPU ខ្សោយ) ---
    # beam_size=1 -> ប្រើ greedy decoding ជំនួស beam search (លឿនជាង 3-5 ដង, ភាពត្រឹមត្រូវថយចុះបន្តិច)
    # vad_filter=True -> រំលងចន្លោះស្ងាត់ (silence) មិនចំណាយពេលដំណើរការចំណុចទាំងនោះ
    # condition_on_previous_text=False -> កាត់បន្ថយហានិភ័យនៃ loop ធ្វើឲ្យយឺត ហើយលឿនជាងបន្តិច
    segments, info = model.transcribe(
        audio_path,
        language=language,
        beam_size=1,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
        condition_on_previous_text=False,
    )
    total_duration = getattr(info, "duration", None)

    subs = []
    for i, seg in enumerate(segments, start=1):
        subs.append(
            srt.Subtitle(
                index=i,
                start=datetime.timedelta(seconds=seg.start),
                end=datetime.timedelta(seconds=seg.end),
                content=seg.text.strip(),
            )
        )
        if progress_cb and total_duration:
            try:
                progress_cb(seg.end, total_duration)
            except Exception:
                pass  # error ក្នុង progress reporting មិនត្រូវធ្វើឲ្យ transcribe បរាជ័យទេ

    result = srt.compose(subs)
    with open(out_srt_path, "w", encoding="utf-8") as f:
        f.write(result)

    return out_srt_path
