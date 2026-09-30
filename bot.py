import os
import re
import logging
import tempfile
import asyncio
import subprocess
import shutil

import srt
import edge_tts
from pydub import AudioSegment

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# ENVIRONMENT
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN environment variable is missing."
    )


# ============================================================
# VOICES
# ============================================================

VOICES = {
    "male": "km-KH-PisethNeural",
    "female": "km-KH-SreymomNeural",
}


# ============================================================
# USER FILES
# ============================================================

user_files: dict[int, str] = {}


# ============================================================
# TTS SETTINGS
# ============================================================

MAX_TEMPO = 4.0
MIN_TEMPO = 0.75

TTS_MAX_ATTEMPTS = 4
TTS_RETRY_DELAY_SEC = 1.2
TTS_INTER_REQUEST_DELAY_SEC = 0.25

MIN_MS_PER_WORD = 120


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "សួស្តី! 👋\n\n"
        "ខ្ញុំជា Bot បំលែង SRT ទៅជាសំឡេង MP3។\n\n"
        "📌 របៀបប្រើ៖\n\n"
        "1️⃣ ផ្ញើ file .srt មកខ្ញុំ\n"
        "2️⃣ ជ្រើសរើសសំឡេង ប្រុស ឬ ស្រី\n"
        "3️⃣ រង់ចាំ MP3\n\n"
        "🎧 សំឡេងនឹង sync តាម timestamp របស់ SRT។"
    )


# ============================================================
# HANDLE SRT UPLOAD
# ============================================================

async def handle_document(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message:
        return

    doc = update.message.document

    if not doc:
        return

    filename = doc.file_name or ""

    if not filename.lower().endswith(".srt"):

        await update.message.reply_text(
            "⚠️ សូមផ្ញើ file .srt ប៉ុណ្ណោះ។"
        )

        return

    status_msg = await update.message.reply_text(
        "⬇️ កំពុងទាញយក SRT..."
    )

    tmp_dir = tempfile.mkdtemp(
        prefix="srtbot_"
    )

    srt_path = os.path.join(
        tmp_dir,
        filename
    )

    try:

        tg_file = await doc.get_file()

        await tg_file.download_to_drive(
            srt_path
        )

        # Save file path
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
            "✅ ទទួលបាន SRT ហើយ!\n\n"
            "សូមជ្រើសរើសសំឡេង៖",
            reply_markup=keyboard
        )

    except Exception as e:

        logger.exception(
            "SRT upload error"
        )

        await status_msg.edit_text(
            "❌ មិនអាចទាញយក SRT បានទេ។\n\n"
            f"Error: `{str(e)}`"
        )


# ============================================================
# VOICE BUTTON
# ============================================================

async def handle_voice_choice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if not query:
        return

    await query.answer()

    chat_id = query.message.chat_id

    voice_key = query.data

    voice_name = VOICES.get(
        voice_key
    )

    # --------------------------------------------------------
    # Check voice
    # --------------------------------------------------------

    if not voice_name:

        await query.edit_message_text(
            "❌ Voice មិនត្រឹមត្រូវទេ។"
        )

        return

    # --------------------------------------------------------
    # Check SRT
    # --------------------------------------------------------

    srt_path = user_files.get(
        chat_id
    )

    if not srt_path:

        await query.edit_message_text(
            "❌ រកមិនឃើញ SRT ទេ។\n"
            "សូម upload SRT ម្តងទៀត។"
        )

        return

    if not os.path.exists(
        srt_path
    ):

        await query.edit_message_text(
            "❌ SRT file ត្រូវបានបាត់ពី server។\n"
            "សូម upload ម្តងទៀត។"
        )

        user_files.pop(
            chat_id,
            None
        )

        return

    label = (
        "ប្រុស (Piseth)"
        if voice_key == "male"
        else
        "ស្រី (Sreymom)"
    )

    await query.edit_message_text(
        f"🎙️ Voice: {label}\n\n"
        "⏳ កំពុងបង្កើត MP3...\n"
        "សូមរង់ចាំ..."
    )

    output_path = None

    try:

        # ----------------------------------------------------
        # BUILD AUDIO
        # ----------------------------------------------------

        output_path, failed_lines = (
            await build_audio_from_srt(
                srt_path,
                voice_name
            )
        )

        # ----------------------------------------------------
        # VERIFY OUTPUT
        # ----------------------------------------------------

        if not output_path:

            raise RuntimeError(
                "build_audio_from_srt() "
                "មិនបាន return MP3 file ទេ។"
            )

        if not os.path.exists(
            output_path
        ):

            raise RuntimeError(
                "MP3 file មិនត្រូវបានបង្កើតទេ។"
            )

        file_size = os.path.getsize(
            output_path
        )

        if file_size <= 0:

            raise RuntimeError(
                "MP3 file មានទំហំ 0 bytes។"
            )

        logger.info(
            "MP3 created: %s (%d bytes)",
            output_path,
            file_size
        )

        # ----------------------------------------------------
        # SEND STATUS
        # ----------------------------------------------------

        await query.edit_message_text(
            "✅ MP3 បង្កើតរួចហើយ!\n"
            "📤 កំពុងផ្ញើ file..."
        )

        # ----------------------------------------------------
        # SEND MP3
        # ----------------------------------------------------

        with open(
            output_path,
            "rb"
        ) as audio_file:

            await context.bot.send_audio(
                chat_id=chat_id,
                audio=audio_file,
                filename="voice_output.mp3",
                title="SRT Voice",
                performer="SRT TTS Bot",
                caption=(
                    "🎧 MP3 រួចរាល់!\n"
                    f"🎙️ សំឡេង: {label}\n"
                    "⏱️ Sync តាម SRT"
                ),
            )

        # ----------------------------------------------------
        # FAILED LINES
        # ----------------------------------------------------

        if failed_lines:

            lines_text = "\n".join(
                f"• #{number} "
                f"({timestamp}): "
                f"{preview}..."
                for (
                    number,
                    timestamp,
                    preview
                )
                in failed_lines[:20]
            )

            if len(failed_lines) > 20:

                more = (
                    "\n... និង "
                    f"{len(failed_lines) - 20} "
                    "បន្ទាត់ទៀត"
                )

            else:

                more = ""

            await context.bot.send_message(
                chat_id=chat_id,
                text=(
                    "⚠️ មាន subtitle ខ្លះ "
                    "មិនអាចបង្កើតសំឡេងបាន៖\n\n"
                    f"{lines_text}"
                    f"{more}"
                )
            )

    except Exception as e:

        logger.exception(
            "BUILD MP3 ERROR"
        )

        error_text = str(e)

        if len(error_text) > 1500:

            error_text = (
                error_text[:1500]
                + "..."
            )

        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ មិនអាចបង្កើត MP3 បានទេ។\n\n"
                "Error:\n"
                f"{error_text}"
            )
        )

    finally:

        # Remove user file reference
        user_files.pop(
            chat_id,
            None
        )


# ============================================================
# PARSE SRT
# ============================================================

def parse_srt(
    path: str
):

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
        "Parsed %d subtitles",
        len(subs)
    )

    return subs


# ============================================================
# REMOVE SRT TAGS
# ============================================================

def strip_tags(
    text: str
):

    # HTML tags
    text = re.sub(
        r"<[^>]+>",
        "",
        text
    )

    # ASS tags
    text = re.sub(
        r"\{\\[^}]*\}",
        "",
        text
    )

    # Newlines
    text = (
        text
        .replace("\r", " ")
        .replace("\n", " ")
    )

    # Multiple spaces
    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# FFMPEG CHECK
# ============================================================

def check_ffmpeg():

    try:

        result = subprocess.run(
            [
                "ffmpeg",
                "-version"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        if result.returncode != 0:

            raise RuntimeError(
                "ffmpeg is not working."
            )

        logger.info(
            "FFmpeg detected."
        )

    except FileNotFoundError:

        raise RuntimeError(
            "ffmpeg មិនមាននៅក្នុង server។ "
            "សូមពិនិត្យ Dockerfile។"
        )


# ============================================================
# FFMPEG ATEMPO
# ============================================================

def _atempo_chain(
    factor: float
):

    filters = []

    remaining = factor

    # FFmpeg atempo supports 0.5 - 2.0
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

    return ",".join(
        filters
    )


# ============================================================
# TIME STRETCH
# ============================================================

def time_stretch(
    seg: AudioSegment,
    factor: float
):

    if len(seg) == 0:

        return seg

    if abs(
        factor - 1.0
    ) < 0.02:

        return seg

    tmp_dir = tempfile.mkdtemp(
        prefix="stretch_"
    )

    in_path = os.path.join(
        tmp_dir,
        "input.wav"
    )

    out_path = os.path.join(
        tmp_dir,
        "output.wav"
    )

    try:

        seg.export(
            in_path,
            format="wav"
        )

        filter_chain = _atempo_chain(
            factor
        )

        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                in_path,
                "-filter:a",
                filter_chain,
                out_path,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:

            raise RuntimeError(
                "FFmpeg atempo failed:\n"
                + result.stderr[-2000:]
            )

        if not os.path.exists(
            out_path
        ):

            raise RuntimeError(
                "FFmpeg did not create output."
            )

        return AudioSegment.from_file(
            out_path,
            format="wav"
        )

    finally:

        shutil.rmtree(
            tmp_dir,
            ignore_errors=True
        )


# ============================================================
# EDGE TTS
# ============================================================

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
        word_count
        * MIN_MS_PER_WORD
    )

    last_error = None

    for attempt in range(
        1,
        TTS_MAX_ATTEMPTS + 1
    ):

        try:

            # Remove old file if exists
            if os.path.exists(
                out_path
            ):

                os.remove(
                    out_path
                )

            communicate = (
                edge_tts.Communicate(
                    text,
                    voice
                )
            )

            await communicate.save(
                out_path
            )

            # Check file
            if (
                os.path.exists(
                    out_path
                )
                and
                os.path.getsize(
                    out_path
                ) > 0
            ):

                audio = (
                    AudioSegment.from_file(
                        out_path
                    )
                )

                duration_ms = len(
                    audio
                )

                # Avoid false empty/invalid files
                if (
                    duration_ms
                    >=
                    expected_min_ms * 0.5
                ):

                    return

                last_error = RuntimeError(
                    "TTS audio is too short: "
                    f"{duration_ms}ms"
                )

            else:

                last_error = RuntimeError(
                    "edge-tts returned empty file."
                )

        except Exception as e:

            last_error = e

        logger.warning(
            "TTS attempt %d/%d failed: %s",
            attempt,
            TTS_MAX_ATTEMPTS,
            last_error
        )

        if attempt < TTS_MAX_ATTEMPTS:

            await asyncio.sleep(
                TTS_RETRY_DELAY_SEC
                * attempt
            )

    raise RuntimeError(
        "TTS failed after "
        f"{TTS_MAX_ATTEMPTS} attempts: "
        f"{last_error}"
    )


# ============================================================
# BUILD AUDIO FROM SRT
# ============================================================

async def build_audio_from_srt(
    srt_path: str,
    voice: str
):

    check_ffmpeg()

    subs = parse_srt(
        srt_path
    )

    if not subs:

        raise RuntimeError(
            "រកមិនឃើញ subtitle ក្នុង SRT ទេ។"
        )

    tmp_dir = tempfile.mkdtemp(
        prefix="srt_audio_"
    )

    segments = []

    total_duration_ms = 0

    failed_lines = []

    try:

        # ====================================================
        # GENERATE EACH SUBTITLE
        # ====================================================

        for i, sub in enumerate(
            subs
        ):

            # ------------------------------------------------
            # Exact SRT timestamps
            # ------------------------------------------------

            start_ms = int(
                sub.start.total_seconds()
                * 1000
            )

            end_ms = int(
                sub.end.total_seconds()
                * 1000
            )

            slot_duration_ms = (
                end_ms - start_ms
            )

            if slot_duration_ms <= 0:

                continue

            clean_text = strip_tags(
                sub.content
            )

            # ------------------------------------------------
            # Empty subtitle
            # ------------------------------------------------

            if not clean_text:

                seg_audio = (
                    AudioSegment.silent(
                        duration=slot_duration_ms
                    )
                )

            else:

                seg_path = os.path.join(
                    tmp_dir,
                    f"segment_{i}.mp3"
                )

                try:

                    # ----------------------------------------
                    # Generate TTS
                    # ----------------------------------------

                    await tts_to_file(
                        clean_text,
                        voice,
                        seg_path
                    )

                    seg_audio = (
                        AudioSegment.from_file(
                            seg_path
                        )
                    )

                    # ----------------------------------------
                    # Calculate speed
                    # ----------------------------------------

                    if len(seg_audio) > 0:

                        # Example:
                        #
                        # audio = 6000ms
                        # slot  = 3000ms
                        #
                        # factor = 2.0
                        #
                        # speech becomes ~3000ms

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

                        if abs(
                            factor - 1.0
                        ) >= 0.02:

                            seg_audio = (
                                time_stretch(
                                    seg_audio,
                                    factor
                                )
                            )

                    # ----------------------------------------
                    # HARD LIMIT
                    # ----------------------------------------

                    if (
                        len(seg_audio)
                        >
                        slot_duration_ms
                    ):

                        seg_audio = (
                            seg_audio[
                                :slot_duration_ms
                            ]
                        )

                    # ----------------------------------------
                    # Fill remaining slot
                    # ----------------------------------------

                    elif (
                        len(seg_audio)
                        <
                        slot_duration_ms
                    ):

                        silence = (
                            AudioSegment.silent(
                                duration=(
                                    slot_duration_ms
                                    -
                                    len(seg_audio)
                                )
                            )
                        )

                        seg_audio += silence

                except Exception as e:

                    logger.exception(
                        "TTS failed at subtitle %d",
                        i + 1
                    )

                    failed_lines.append(
                        (
                            i + 1,
                            str(sub.start),
                            clean_text[:80]
                        )
                    )

                    # Silence if TTS fails
                    seg_audio = (
                        AudioSegment.silent(
                            duration=slot_duration_ms
                        )
                    )

                await asyncio.sleep(
                    TTS_INTER_REQUEST_DELAY_SEC
                )

            # ------------------------------------------------
            # Save segment with exact position
            # ------------------------------------------------

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

        # ====================================================
        # CREATE COMPLETE TIMELINE
        # ====================================================

        timeline = (
            AudioSegment.silent(
                duration=total_duration_ms
            )
        )

        # ====================================================
        # PLACE AUDIO AT EXACT SRT TIME
        # ====================================================

        for (
            start_ms,
            end_ms,
            seg_audio
        ) in segments:

            allowed_duration = (
                end_ms - start_ms
            )

            # Final safety
            if (
                len(seg_audio)
                >
                allowed_duration
            ):

                seg_audio = (
                    seg_audio[
                        :allowed_duration
                    ]
                )

            # IMPORTANT:
            # Do not concatenate.
            # Put audio at exact timestamp.
            timeline = timeline.overlay(
                seg_audio,
                position=start_ms
            )

        # ====================================================
        # EXPORT MP3
        # ====================================================

        output_path = os.path.join(
            tmp_dir,
            "voice_output.mp3"
        )

        timeline.export(
            output_path,
            format="mp3",
            bitrate="192k"
        )

        if not os.path.exists(
            output_path
        ):

            raise RuntimeError(
                "MP3 output was not created."
            )

        if os.path.getsize(
            output_path
        ) <= 0:

            raise RuntimeError(
                "MP3 output is empty."
            )

        logger.info(
            "Finished MP3: %s",
            output_path
        )

        return (
            output_path,
            failed_lines
        )

    except Exception:

        # Keep log for Render
        logger.exception(
            "build_audio_from_srt failed"
        )

        raise


# ============================================================
# ERROR HANDLER
# ============================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    logger.exception(
        "Unhandled exception:",
        exc_info=context.error
    )


# ============================================================
# MAIN
# ============================================================

def main():

    logger.info(
        "Starting SRT TTS Bot..."
    )

    # Check ffmpeg immediately
    check_ffmpeg()

    app = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    # /start
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # SRT upload
    app.add_handler(
        MessageHandler(
            filters.Document.ALL,
            handle_document
        )
    )

    # Voice buttons
    app.add_handler(
        CallbackQueryHandler(
            handle_voice_choice,
            pattern="^(male|female)$"
        )
    )

    # Error handler
    app.add_error_handler(
        error_handler
    )

    # --------------------------------------------------------
    # Render
    # --------------------------------------------------------

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    render_url = os.environ.get(
        "RENDER_EXTERNAL_URL"
    )

    if render_url:

        logger.info(
            "Render URL: %s",
            render_url
        )

        logger.info(
            "Starting Telegram webhook..."
        )

        app.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=BOT_TOKEN,
            webhook_url=(
                f"{render_url}/{BOT_TOKEN}"
            ),
            drop_pending_updates=True,
        )

    else:

        logger.info(
            "Starting Telegram polling..."
        )

        app.run_polling(
            drop_pending_updates=True
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
