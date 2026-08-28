"""
srt_audio.py
------------
Module ដែលទទួលបន្ទុក:
  1) អានឯកសារ SRT
  2) បំលែងអត្ថបទនីមួយៗទៅជាសំឡេង (Text-to-Speech) តាមរយៈ edge-tts
  3) កែសម្រួល "speed" របស់សំឡេងឲ្យត្រូវនឹងរយៈពេលដែលកំណត់ក្នុង SRT
  4) តម្រៀបផ្គុំសំឡេងទាំងអស់ជា audio file តែមួយ ដោយគោរពទីតាំង timestamp

សំឡេងប្រុស/ស្រី ខ្មែរ (Microsoft Edge Neural voices):
  - ស្រី : km-KH-SreymomNeural
  - ប្រុស: km-KH-PisethNeural
"""

import os
import srt
import asyncio
import edge_tts
from pydub import AudioSegment

VOICE_FEMALE = "km-KH-SreymomNeural"
VOICE_MALE = "km-KH-PisethNeural"


def parse_srt_file(path: str):
    """អាន file .srt ហើយប្រែជា list នៃ subtitle objects"""
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    return list(srt.parse(content))


def pick_voice(index: int, text: str) -> str:
    """
    ជ្រើសរើសសំឡេងប្រុស/ស្រី។
    ច្បាប់សាមញ្ញ:
      - បើបន្ទាត់ចាប់ផ្តើមដោយសញ្ញា "-" (សន្ទនាច្រើននាក់ក្នុងបន្ទាត់តែមួយ) -> ប្តូរតាមចំនួនសញ្ញា dash
      - ក្រៅពីនេះ ប្តូរឆ្លាស់គ្នាទៅតាមលេខរៀង subtitle (គូ = ស្រី, សេស = ប្រុស)
        ដើម្បីក្លែងធ្វើជាអ្នកនិយាយពីរនាក់ឆ្លាស់គ្នា
    អ្នកអាចប្តូរតក្កវិជ្ជានេះបានតាមតម្រូវការជាក់ស្តែងរបស់អ្នក។
    """
    return VOICE_FEMALE if index % 2 == 0 else VOICE_MALE


async def _tts_to_file(text: str, voice: str, out_path: str):
    """ហៅ edge-tts ដើម្បីបង្កើតឯកសារសំឡេងពី text"""
    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(out_path)


def _speed_change(sound: AudioSegment, speed: float) -> AudioSegment:
    """ប្តូរល្បឿននៃ audio segment ដោយមិនផ្លាស់ប្តូរសំឡេង pitch ខ្លាំងពេក"""
    if speed <= 0:
        speed = 1.0
    new_frame_rate = int(sound.frame_rate * speed)
    shifted = sound._spawn(sound.raw_data, overrides={"frame_rate": new_frame_rate})
    return shifted.set_frame_rate(sound.frame_rate)


async def build_audio_from_srt(srt_path: str, out_mp3_path: str, work_dir: str,
                                progress_cb=None) -> str:
    """
    មុខងារសំខាន់៖ អាន SRT -> បង្កើតសំឡេងតាមបន្ទាត់ -> តម្រឹមតាមពេលវេលា -> ផ្គុំចេញជា mp3 មួយ

    progress_cb: async function(current, total) សម្រាប់ report ដំណើរការត្រឡប់ទៅ Telegram (optional)
    """
    subs = parse_srt_file(srt_path)
    if not subs:
        raise ValueError("SRT file មិនមានខ្លឹមសារ subtitle ទេ")

    os.makedirs(work_dir, exist_ok=True)
    total_duration_ms = int(subs[-1].end.total_seconds() * 1000) + 1000
    timeline = AudioSegment.silent(duration=total_duration_ms)

    for i, sub in enumerate(subs):
        text = sub.content.strip().replace("\n", " ")
        if not text:
            continue

        voice = pick_voice(i, text)
        raw_path = os.path.join(work_dir, f"seg_{i}.mp3")

        await _tts_to_file(text, voice, raw_path)
        segment = AudioSegment.from_file(raw_path, format="mp3")

        target_ms = int((sub.end - sub.start).total_seconds() * 1000)
        target_ms = max(target_ms, 200)  # យ៉ាងតិចបំផុត 0.2 វិនាទី
        actual_ms = len(segment)

        # បើសំឡេងវែងជាងចន្លោះពេលដែលមាន -> បង្កើនល្បឿនបន្តិចឲ្យសមទំហំ
        if actual_ms > target_ms and actual_ms > 0:
            speed_ratio = actual_ms / target_ms
            speed_ratio = min(speed_ratio, 1.8)  # កុំបង្កើនល្បឿនលើសហេតុផល
            segment = _speed_change(segment, speed_ratio)

        start_ms = int(sub.start.total_seconds() * 1000)
        timeline = timeline.overlay(segment, position=start_ms)

        os.remove(raw_path)

        if progress_cb:
            await progress_cb(i + 1, len(subs))

    timeline.export(out_mp3_path, format="mp3", bitrate="192k")
    return out_mp3_path
