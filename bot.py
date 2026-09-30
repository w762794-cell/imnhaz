import os
import re
import logging
import tempfile
import asyncio
import subprocess

import srt
import edge_tts
from pydub import AudioSegment
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ["BOT_TOKEN"]

# Edge-TTS Khmer neural voices
VOICES = {
    "male": "km-KH-PisethNeural",
    "female": "km-KH-SreymomNeural",
}

# In-memory map: chat_id -> path of the uploaded .srt file
user_files: dict[int, str] = {}

# Maximum/minimum speed adjustment
MAX_TEMPO = 4.0
MIN_TEMPO = 0.75

TTS_MAX_ATTEMPTS = 4
TTS_RETRY_DELAY_SEC = 1.2
TTS_INTER_REQUEST_DELAY_SEC = 0.25
MIN_MS_PER_WORD = 120


# --------------------------------------------------------------------------
# Telegram handlers
# --------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "សួស្តី! 👋\n\n"
        "ខ្ញុំជា Bot បំលែងឯកសារ SRT ទៅជាសំឡេងនិយាយ (Text-to-Speech)។\n\n"
        "📌 របៀបប្រើ៖\n"
        "1️⃣ ផ្ញើឯកសារ .srt មកខ្ញុំ\n"
        "2️⃣ ជ្រើសរើសសំឡេង ប្រុស (Piseth) ឬ ស្រី (Sreymom)\n"
        "3️⃣ រង់ចាំ ខ្ញុំនឹងផ្ញើឯកសារសំឡេង (.mp3) ត្រឡប់មកវិញ ដែលត្រូវតាមពេលវេលានៃ SRT"
    )


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document

    if not doc.file_name.lower().endswith(".srt"):
        await update.message.reply_text(
            "⚠️ សូមផ្ញើតែឯកសារ .srt ប៉ុណ្ណោះ។"
        )
        return

    status_msg = await update.message.reply_text(
        "⬇️ កំពុងទាញយកឯកសារ..."
    )

    tmp_dir = tempfile.mkdtemp()
    srt_path = os.path.join(
        tmp_dir,
        doc.file_name
    )

    tg_file = await doc.get_file()
    await tg_file.download_to_drive(
        srt_path
    )

    user_files[
        update.effective_chat.id
    ] = srt_path

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "👨 ប្រុស (Piseth)",
                    callback_data="male"
                ),
                InlineKeyboardButton(
                    "👩 ស្រី (Sreymom)",
                    callback_data="female"
                ),
            ]
        ]
    )

    await status_msg.edit_text(
        "✅ ទទួលឯកសារបានហើយ។ សូមជ្រើសរើសសំឡេង៖",
        reply_markup=keyboard
    )


async def handle_voice_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    voice_key = query.data
    voice_name = VOICES.get(voice_key)

    srt_path = user_files.get(chat_id)

    if not srt_path or not os.path.exists(srt_path):
        await query.edit_message_text(
            "⚠️ រកមិនឃើញឯកសារ SRT ទេ សូមផ្ញើម្តងទៀត។"
        )
        return

    label = (
        "ប្រុស (Piseth)"
        if voice_key == "male"
        else "ស្រី (Sreymom)"
    )

    await query.edit_message_text(
        f"🎙️ កំពុងបំលែងជាសំឡេង {label}...\n"
        "សូមរង់ចាំបន្តិច ⏳"
    )

    try:

        output_path, failed_lines = (
            await build_audio_from_srt(
                srt_path,
                voice_name
            )
        )

        with open(
            output_path,
            "rb"
        ) as audio_file:

            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                filename="voice_output.mp3",
                caption=(
                    f"✅ បំលែងបានជោគជ័យ! "
                    f"(សំឡេង៖ {label})"
                ),
            )

        if failed_lines:

            lines_text = "\n".join(
                f"• បន្ទាត់ #{n} ({ts}): {preview}..."
                for n, ts, preview
                in failed_lines[:20]
            )

            more = (
                f"\n... និងច្រើនទៀត "
                f"({len(failed_lines) - 20})"
                if len(failed_lines) > 20
                else ""
            )

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    f"⚠️ បន្ទាត់ចំនួន "
                    f"{len(failed_lines)} "
                    "មិនអាចបំលែងជាសំឡេងបានទេ "
                    "(ដាក់ជាស្ងាត់ជំនួសវិញ)៖\n"
                    f"{lines_text}{more}"
                ),
            )

    except Exception as e:

        logger.exception(
            "Error while building audio"
        )

        await context.bot.send_message(
            chat_id=chat_id,
            text=f"❌ មានបញ្ហា៖ {e}"
        )

    finally:

        user_files.pop(
            chat_id,
            None
        )


# --------------------------------------------------------------------------
# SRT -> timed audio logic
# --------------------------------------------------------------------------

def parse_srt(path: str):

    with open(
        path,
        "r",
        encoding="utf-8-sig"
    ) as f:

        content = f.read()

    subs = list(
        srt.parse(
            content,
            ignore_errors=True
        )
    )

    logger.info(
        "Parsed %d subtitle entries from %s",
        len(subs),
        path
    )

    return subs


def strip_tags(text: str) -> str:

    text = re.sub(
        r"</?\s*(i|b|u|font)[^>]*>",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\{\\[^}]*\}",
        "",
        text
    )

    text = (
        text
        .replace("\r", " ")
        .replace("\n", " ")
    )

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# --------------------------------------------------------------------------
# FFmpeg atempo
# --------------------------------------------------------------------------

def _atempo_chain(factor: float) -> str:

    filters = []
    remaining = factor

    while remaining > 2.0:

        filters.append(
            "atempo=2.0"
        )

        remaining /= 2.0

    while remaining < 0.5:

        filters.append(
            "atempo=0.5"
        )

        remaining /= 0.5

    filters.append(
        f"atempo={remaining:.6f}"
    )

    return ",".join(filters)


def time_stretch(
    seg: AudioSegment,
    factor: float
) -> AudioSegment:

    if abs(factor - 1.0) < 0.02:
        return seg

    tmp_dir = tempfile.mkdtemp()

    in_path = os.path.join(
        tmp_dir,
        "in.wav"
    )

    out_path = os.path.join(
        tmp_dir,
        "out.wav"
    )

    seg.export(
        in_path,
        format="wav"
    )

    filter_chain = _atempo_chain(
        factor
    )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            in_path,
            "-filter:a",
            filter_chain,
            out_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    return AudioSegment.from_file(
        out_path,
        format="wav"
    )


# --------------------------------------------------------------------------
# Edge TTS
# --------------------------------------------------------------------------

async def tts_to_file(
    text: str,
    voice: str,
    out_path: str
):

    word_count = max(
        len(text.split()),
        1
    )

    expected_min_ms = (
        word_count *
        MIN_MS_PER_WORD
    )

    last_err = None

    for attempt in range(
        1,
        TTS_MAX_ATTEMPTS + 1
    ):

        try:

            communicate = edge_tts.Communicate(
                text,
                voice
            )

            await communicate.save(
                out_path
            )

            if (
                os.path.exists(out_path)
                and
                os.path.getsize(out_path) > 0
            ):

                duration_ms = len(
                    AudioSegment.from_file(
                        out_path
                    )
                )

                if (
                    duration_ms
                    >=
                    expected_min_ms * 0.5
                ):

                    return

                last_err = RuntimeError(
                    f"suspiciously short audio "
                    f"({duration_ms}ms for "
                    f"{word_count} words)"
                )

            else:

                last_err = RuntimeError(
                    "edge-tts returned an empty file"
                )

        except Exception as e:

            last_err = e

        logger.warning(
            "TTS attempt %d/%d failed for %r: %s",
            attempt,
            TTS_MAX_ATTEMPTS,
            text[:60],
            last_err,
        )

        if attempt < TTS_MAX_ATTEMPTS:

            await asyncio.sleep(
                TTS_RETRY_DELAY_SEC
            )

    raise RuntimeError(
        f"TTS failed after "
        f"{TTS_MAX_ATTEMPTS} attempts: "
        f"{last_err}"
    )


# --------------------------------------------------------------------------
# IMPORTANT:
# Build audio using EXACT SRT timestamps
# --------------------------------------------------------------------------

async def build_audio_from_srt(
    srt_path: str,
    voice: str
):

    subs = parse_srt(
        srt_path
    )

    if not subs:
        raise RuntimeError(
            "រកមិនឃើញ subtitle ក្នុង SRT ទេ។"
        )

    tmp_dir = tempfile.mkdtemp()

    # Each item:
    # (start_ms, end_ms, audio)
    segments = []

    total_duration_ms = 0

    failed_lines = []

    # ==============================================================
    # FIRST PASS
    # Generate every subtitle's audio
    # ==============================================================
    for i, sub in enumerate(
        subs
    ):

        # Exact SRT timestamp
        start_ms = int(
            sub.start.total_seconds()
            * 1000
        )

        end_ms = int(
            sub.end.total_seconds()
            * 1000
        )

        # Duration allowed by SRT
        slot_duration_ms = (
            end_ms - start_ms
        )

        if slot_duration_ms < 200:
            slot_duration_ms = 200

        clean_text = strip_tags(
            sub.content
        )

        # ----------------------------------------------------------
        # Empty subtitle
        # ----------------------------------------------------------

        if not clean_text:

            seg_audio = AudioSegment.silent(
                duration=slot_duration_ms
            )

        else:

            seg_path = os.path.join(
                tmp_dir,
                f"seg_{i}.mp3"
            )

            try:

                # --------------------------------------------------
                # TTS
                # --------------------------------------------------

                await tts_to_file(
                    clean_text,
                    voice,
                    seg_path
                )

                seg_audio = AudioSegment.from_file(
                    seg_path
                )

                # --------------------------------------------------
                # Calculate EXACT speed needed
                #
                # Example:
                #
                # speech = 5000ms
                # SRT slot = 3000ms
                #
                # factor = 5000 / 3000
                #        = 1.6667
                #
                # speech becomes approximately 3000ms
                # --------------------------------------------------

                if (
                    len(seg_audio) > 0
                    and
                    slot_duration_ms > 0
                ):

                    factor = (
                        len(seg_audio)
                        /
                        slot_duration_ms
                    )

                    factor = max(
                        MIN_TEMPO,
                        min(
                            factor,
                            MAX_TEMPO
                        )
                    )

                    seg_audio = time_stretch(
                        seg_audio,
                        factor
                    )

                # --------------------------------------------------
                # HARD LIMIT
                #
                # NEVER allow speech to pass the
                # subtitle's END timestamp.
                # --------------------------------------------------

                if (
                    len(seg_audio)
                    >
                    slot_duration_ms
                ):

                    seg_audio = seg_audio[
                        :slot_duration_ms
                    ]

                # --------------------------------------------------
                # Fill remaining slot with silence
                # --------------------------------------------------

                elif (
                    len(seg_audio)
                    <
                    slot_duration_ms
                ):

                    seg_audio += (
                        AudioSegment.silent(
                            duration=(
                                slot_duration_ms
                                -
                                len(seg_audio)
                            )
                        )
                    )

            except Exception as e:

                logger.error(
                    "Giving up on line %d (%r): %s",
                    i + 1,
                    clean_text[:60],
                    e,
                )

                failed_lines.append(
                    (
                        i + 1,
                        str(sub.start),
                        clean_text[:60]
                    )
                )

                seg_audio = (
                    AudioSegment.silent(
                        duration=slot_duration_ms
                    )
                )

            await asyncio.sleep(
                TTS_INTER_REQUEST_DELAY_SEC
            )

        # ----------------------------------------------------------
        # Save exact SRT position
        # ----------------------------------------------------------

        segments.append(
            (
                start_ms,
                end_ms,
                seg_audio
            )
        )

        total_duration_ms = max(
            total_duration_ms,
            end_ms
        )

    # ==============================================================
    # SECOND PASS
    # Create complete timeline
    # ==============================================================

    timeline = AudioSegment.silent(
        duration=total_duration_ms
    )

    # ==============================================================
    # PLACE EACH AUDIO AT ITS EXACT SRT START
    # ==============================================================

    for (
        start_ms,
        end_ms,
        seg_audio
    ) in segments:

        allowed_duration = (
            end_ms - start_ms
        )

        # Final safety check
        if len(seg_audio) > allowed_duration:

            seg_audio = seg_audio[
                :allowed_duration
            ]

        # IMPORTANT:
        # Do NOT concatenate.
        # Put audio at exact SRT timestamp.
        timeline = timeline.overlay(
            seg_audio,
            position=start_ms
        )

    # ==============================================================
    # EXPORT
    # ==============================================================

    output_path = os.path.join(
        tmp_dir,
        "output.mp3"
    )

    timeline.export(
        output_path,
        format="mp3",
        bitrate="192k"
    )

    return (
        output_path,
        failed_lines
    )


# --------------------------------------------------------------------------
# App entrypoint
# --------------------------------------------------------------------------

def main():

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_document
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            handle_voice_choice
        )
    )

    # Render PORT
    port = int(
        os.environ.get(
            "PORT",
            8080
        )
    )

    # Render automatically provides this
    render_url = os.environ.get(
        "RENDER_EXTERNAL_URL"
    )

    if render_url:

        logger.info(
            "Starting in WEBHOOK mode on %s",
            render_url
        )

        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=(
                f"{render_url}/{BOT_TOKEN}"
            ),
        )

    else:

        logger.info(
            "Starting in POLLING mode (local dev)"
        )

        app.run_polling()


if __name__ == "__main__":

    main()
