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
import subprocess
import tempfile
import edge_tts
from pydub import AudioSegment

VOICE_FEMALE = "km-KH-SreymomNeural"
VOICE_MALE = "km-KH-PisethNeural"


def parse_srt_file(path: str):
    """អាន file .srt ហើយប្រែជា list នៃ subtitle objects"""
    with open(path, "r", encoding="utf-8-sig") as f:
        content = f.read()
    return list(srt.parse(content))


def pick_voice(index: int, text: str, voice_mode: str = "alternate") -> str:
    """
    ជ្រើសរើសសំឡេងតាមជម្រើសរបស់អ្នកប្រើ។

    voice_mode:
      - "male"      -> ប្រុសទាំងអស់
      - "female"    -> ស្រីទាំងអស់
      - "alternate" -> ឆ្លាស់គ្នា (គូ = ស្រី, សេស = ប្រុស) ដើម្បីក្លែងធ្វើជាអ្នកនិយាយពីរនាក់
    """
    if voice_mode == "male":
        return VOICE_MALE
    if voice_mode == "female":
        return VOICE_FEMALE
    # alternate (default)
    return VOICE_FEMALE if index % 2 == 0 else VOICE_MALE


async def _tts_to_file(text: str, voice: str, out_path: str):
    """ហៅ edge-tts ដើម្បីបង្កើតឯកសារសំឡេងពី text"""
    communicate = edge_tts.Communicate(text=text, voice=voice)
    await communicate.save(out_path)


def _speed_change(sound: AudioSegment, speed: float) -> AudioSegment:
    """
    ប្តូរល្បឿននៃ audio segment ដោយ *រក្សា pitch ដដែល* (មិនប្តូរឲ្យស្តាប់ទៅដូចក្មេង)
    ដោយប្រើ ffmpeg 'atempo' filter ជំនួសវិធីចាស់ (ប្តូរ frame_rate ដោយផ្ទាល់)
    ដែលធ្វើឲ្យ pitch ខ្ពស់ឡើងពេលបង្កើនល្បឿន (chipmunk effect)។

    'atempo' filter ត្រឹមត្រូវសម្រាប់តម្លៃចន្លោះ 0.5–2.0 ក្នុងការហៅតែម្តង
    ដែលគ្រប់គ្រាន់ស្រាប់ ព្រោះ speed_ratio ក្នុង build_audio_from_srt ត្រូវបាន
    កំណត់អតិបរមាតែ 1.8 ស្រាប់។
    """
    if speed <= 0 or abs(speed - 1.0) < 0.02:
        return sound

    speed = max(0.5, min(speed, 2.0))

    in_path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name
    out_path = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False).name

    try:
        sound.export(in_path, format="mp3")
        cmd = [
            "ffmpeg", "-y", "-i", in_path,
            "-filter:a", f"atempo={speed:.3f}",
            out_path,
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return AudioSegment.from_file(out_path, format="mp3")
    finally:
        for p in (in_path, out_path):
            if os.path.exists(p):
                os.remove(p)


async def build_audio_from_srt(srt_path: str, out_mp3_path: str, work_dir: str,
                                voice_mode: str = "alternate",
                                progress_cb=None) -> str:
    """
    មុខងារសំខាន់៖ អាន SRT -> បង្កើតសំឡេងតាមបន្ទាត់ -> តម្រឹមតាមពេលវេលា -> ផ្គុំចេញជា mp3 មួយ

    voice_mode: "male" | "female" | "alternate" (មើលអនុគមន៍ pick_voice)
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

        voice = pick_voice(i, text, voice_mode)
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
