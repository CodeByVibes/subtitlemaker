#!/usr/bin/env python3

import os
import sys

# CTranslate2 needs CUDA 12 libs (cuBLAS/cuDNN) from the pip nvidia-* packages.
# The loader reads LD_LIBRARY_PATH only at process start, so re-exec once.
if sys.platform.startswith("linux") and not os.environ.get("_CUDA_REEXEC"):
    try:
        import nvidia.cublas.lib
        import nvidia.cudnn.lib

        _libs = [list(m.__path__)[0] for m in (nvidia.cublas.lib, nvidia.cudnn.lib)]
        os.environ["LD_LIBRARY_PATH"] = ":".join(
            _libs + [p for p in [os.environ.get("LD_LIBRARY_PATH")] if p]
        )
        os.environ["_CUDA_REEXEC"] = "1"
        os.execv(sys.executable, [sys.executable] + sys.argv)
    except ImportError:
        pass

import argparse
import re
import time
from pathlib import Path

import av
from faster_whisper import WhisperModel

try:
    from faster_whisper.tokenizer import _LANGUAGE_CODES
except ImportError:
    _LANGUAGE_CODES = None


# ============================================================
# CONFIGURATION
# ============================================================

# Whisper model
MODEL = "large-v3"
DEVICE = "cuda"
COMPUTE_TYPE = "float16"

# Subtitle layout
MAX_LINE_LENGTH = 42       # Maximum characters per line
MAX_LINES = 2              # Maximum number of lines

# Subtitle readability
MAX_CPS = 20               # Maximum characters per second
MIN_DURATION = 1.0         # Minimum subtitle duration
MAX_DURATION = 7.0         # Maximum subtitle duration
MIN_GAP = 0.05             # Minimum gap between subtitles

# Whisper
VAD_FILTER = True
CONDITION_ON_PREVIOUS_TEXT = True


# ============================================================
# TIME FORMATTING
# ============================================================

def format_time(seconds):
    """Format seconds as HH:MM:SS."""

    seconds = max(0, int(seconds))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_srt_time(seconds):
    """Convert seconds to SRT timestamp."""

    milliseconds = int(round(seconds * 1000))

    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000

    minutes = milliseconds // 60_000
    milliseconds %= 60_000

    seconds = milliseconds // 1000
    milliseconds %= 1000

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:02d},"
        f"{milliseconds:03d}"
    )


# ============================================================
# TEXT CLEANUP
# ============================================================

def clean_text(text):
    """Clean up Whisper text."""

    text = text.strip()

    # Collapse multiple whitespace characters
    text = re.sub(r"\s+", " ", text)

    # Remove spaces before punctuation
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)

    # Clean brackets
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]])", r"\1", text)

    return text.strip()


# ============================================================
# LINE BREAKING
# ============================================================

def split_into_lines(text):
    """
    Split subtitle into a maximum of MAX_LINES lines.

    Attempts to:
    - keep lines below MAX_LINE_LENGTH
    - balance line lengths
    - prefer punctuation boundaries
    """

    words = text.split()

    if not words:
        return []

    # Fits on one line
    if len(text) <= MAX_LINE_LENGTH:
        return [text]

    # Find the best two-line split
    best_split = None
    best_score = float("inf")

    for i in range(1, len(words)):
        left = " ".join(words[:i])
        right = " ".join(words[i:])

        if len(left) > MAX_LINE_LENGTH:
            continue

        if len(right) > MAX_LINE_LENGTH:
            continue

        # Prefer balanced lines
        score = abs(len(left) - len(right))

        # Prefer punctuation at the end of line 1
        if left.endswith((".", ",", "!", "?", ";", ":")):
            score -= 15

        if score < best_score:
            best_score = score
            best_split = (left, right)

    if best_split:
        return list(best_split)

    # Fallback: split approximately in half.
    midpoint = len(words) // 2

    return [
        " ".join(words[:midpoint]),
        " ".join(words[midpoint:]),
    ]


# ============================================================
# TIMING
# ============================================================

def adjust_timing(start, end, text):
    """
    Adjust subtitle duration according to reading speed.

    The subtitle is never made shorter than MIN_DURATION
    and never longer than MAX_DURATION.
    """

    duration = end - start

    # Required duration based on CPS
    required_duration = len(text) / MAX_CPS

    duration = max(
        duration,
        required_duration,
        MIN_DURATION,
    )

    duration = min(
        duration,
        MAX_DURATION,
    )

    return start, start + duration


# ============================================================
# SUBTITLE GENERATION
# ============================================================

def build_subtitles(segments):
    """Convert Whisper segments into formatted subtitles."""

    subtitles = []
    previous_end = 0.0

    for segment in segments:

        text = clean_text(segment.text)

        if not text:
            continue

        start = float(segment.start)
        end = float(segment.end)

        # Maximum characters allowed in one subtitle cue
        max_chars = MAX_LINE_LENGTH * MAX_LINES

        # Split long Whisper segments
        if len(text) <= max_chars:
            chunks = [text]

        else:
            words = text.split()
            chunks = []
            current = ""

            for word in words:

                candidate = f"{current} {word}".strip()

                if len(candidate) <= max_chars:
                    current = candidate

                else:
                    if current:
                        chunks.append(current)

                    current = word

            if current:
                chunks.append(current)

        # Distribute the original segment duration
        # proportionally between chunks.
        total_chars = sum(len(chunk) for chunk in chunks)

        current_start = start

        for chunk in chunks:

            proportion = len(chunk) / total_chars

            chunk_duration = (
                (end - start) * proportion
            )

            chunk_end = (
                current_start + chunk_duration
            )

            lines = split_into_lines(chunk)

            if not lines:
                continue

            display_text = "\n".join(lines)

            plain_text = display_text.replace(
                "\n",
                " ",
            )

            adjusted_start, adjusted_end = (
                adjust_timing(
                    current_start,
                    chunk_end,
                    plain_text,
                )
            )

            # Prevent overlap
            adjusted_start = max(
                adjusted_start,
                previous_end + MIN_GAP,
            )

            # Safety
            if adjusted_end <= adjusted_start:
                adjusted_end = (
                    adjusted_start + MIN_DURATION
                )

            subtitles.append(
                {
                    "start": adjusted_start,
                    "end": adjusted_end,
                    "text": display_text,
                }
            )

            previous_end = adjusted_end
            current_start = chunk_end

    return subtitles


# ============================================================
# MEDIA INFORMATION
# ============================================================

def get_duration(filename):
    """Get media duration using PyAV."""

    container = av.open(filename)

    try:

        if container.duration is not None:
            return container.duration / av.time_base

        # Fallback
        for stream in container.streams:

            if (
                stream.duration is not None
                and stream.time_base is not None
            ):
                return float(
                    stream.duration
                    * stream.time_base
                )

        return 0.0

    finally:
        container.close()


# ============================================================
# PROGRESS / ETA
# ============================================================

def show_progress(
    processed,
    total,
    start_time,
):
    """Display live transcription progress."""

    elapsed = (
        time.monotonic()
        - start_time
    )

    if total > 0:
        progress = min(
            processed / total,
            1.0,
        )
    else:
        progress = 0.0

    percent = progress * 100

    # Video seconds processed per real second
    if elapsed > 0:
        speed = processed / elapsed
    else:
        speed = 0.0

    # ETA in real seconds
    if speed > 0 and total > processed:
        eta = (
            total - processed
        ) / speed
    else:
        eta = 0

    # Progress bar
    bar_width = 30

    filled = int(
        bar_width * progress
    )

    if filled >= bar_width:
        bar = "━" * bar_width

    else:
        bar = (
            "━" * filled
            + "╸"
            + "━" * (
                bar_width
                - filled
                - 1
            )
        )

    print(
        f"\rTranscribing "
        f"━{bar} "
        f"{percent:5.1f}% | "
        f"{format_time(processed)} / "
        f"{format_time(total)} | "
        f"{speed:4.1f}x | "
        f"ETA {format_time(eta)}",
        end="",
        flush=True,
    )


# ============================================================
# LANGUAGE HANDLING
# ============================================================

def parse_language_argument(value):
    """
    Parse the -l/--language argument.

    Accepts a single language code ("he") or a comma or
    space separated list of codes ("he,en") for audio that
    contains more than one language.

    Returns (languages, multilingual), where `multilingual`
    is True when more than one code was given.
    """

    if not value:
        return [], False

    languages = []

    for code in re.split(r"[,\s]+", value.strip()):

        code = code.lower()

        if not code:
            continue

        if code not in languages:
            languages.append(code)

    if _LANGUAGE_CODES is not None:

        unknown = [
            code
            for code in languages
            if code not in _LANGUAGE_CODES
        ]

        if unknown:
            raise ValueError(
                f"unknown language code(s): "
                f"{', '.join(unknown)}"
            )

    return languages, len(languages) > 1


# ============================================================
# MAIN
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Generate SRT subtitles "
            "using Faster-Whisper."
        )
    )

    parser.add_argument(
        "input",
        help="Input video/audio file",
    )

    parser.add_argument(
        "-o",
        "--output",
        help="Output SRT file",
    )

    parser.add_argument(
        "-l",
        "--language",
        help=(
            "Source language. Several "
            "comma-separated codes are "
            "allowed for mixed-language "
            "audio (e.g. en, sv, he,en)"
        ),
    )

    parser.add_argument(
        "-m",
        "--multilingual",
        action="store_true",
        help=(
            "Audio contains more than one "
            "language: re-detect the language "
            "before every segment instead of "
            "using one language for the whole "
            "file"
        ),
    )

    parser.add_argument(
        "-t",
        "--task",
        choices=[
            "transcribe",
            "translate",
        ],
        default="translate",
        help=(
            "transcribe = keep original "
            "language; translate = English"
        ),
    )

    parser.add_argument(
        "--detect-segments",
        type=int,
        default=1,
        metavar="N",
        help=(
            "Segments sampled for the initial "
            "language detection (default: 1)"
        ),
    )

    parser.add_argument(
        "--detect-threshold",
        type=float,
        default=0.5,
        metavar="P",
        help=(
            "Confidence needed to accept the "
            "initial language detection "
            "(default: 0.5)"
        ),
    )

    parser.add_argument(
        "--condition-on-previous-text",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Use previous text as a prompt for "
            "the next segment "
            "(default: off for multilingual, "
            "on otherwise)"
        ),
    )

    args = parser.parse_args()

    # --------------------------------------------------------
    # Language options
    # --------------------------------------------------------

    try:
        languages, listed_multilingual = (
            parse_language_argument(
                args.language
            )
        )

    except ValueError as e:
        parser.error(str(e))

    if args.detect_segments < 1:
        parser.error(
            "--detect-segments must be at least 1"
        )

    if not 0.0 < args.detect_threshold <= 1.0:
        parser.error(
            "--detect-threshold must be "
            "greater than 0 and at most 1"
        )

    # More than one language code, or -m/--multilingual,
    # means the language has to be decided again for every
    # segment instead of once for the whole file.
    multilingual = (
        args.multilingual or listed_multilingual
    )

    # Whisper holds a single language token per decode, so a
    # hint is only used when the language is fixed for the
    # whole file. Leaving it unset also keeps the initial
    # detection available for the report.
    language_hint = (
        None
        if multilingual
        else (languages[0] if languages else None)
    )

    if args.condition_on_previous_text is not None:

        condition_on_previous_text = (
            args.condition_on_previous_text
        )

    else:

        # Text from the previous segment pulls the next one
        # back towards the language it was written in, which
        # fights per-segment language detection.
        condition_on_previous_text = (
            CONDITION_ON_PREVIOUS_TEXT
            and not multilingual
        )

    input_file = Path(args.input)

    if not input_file.exists():
        print(
            f"Error: input file does not exist: "
            f"{input_file}"
        )
        return 1

    # Default output name
    if args.output:
        output_file = Path(args.output)

    else:
        output_file = (
            input_file.with_suffix(".srt")
        )

    # --------------------------------------------------------
    # Information
    # --------------------------------------------------------

    if multilingual:

        if languages:
            language_display = (
                f"{', '.join(languages)} "
                f"(re-detected per segment)"
            )

        else:
            language_display = (
                "auto-detect per segment"
            )

    else:

        language_display = (
            languages[0] if languages else "auto-detect"
        )

    print(f"Input:          {input_file}")
    print(f"Output:         {output_file}")
    print(f"Language:       {language_display}")
    print(f"Task:           {args.task}")
    print(f"Model:          {MODEL}")
    print(f"Device:         {DEVICE}")
    print(f"Compute type:   {COMPUTE_TYPE}")
    print(
        f"Prompt history: "
        f"{'on' if condition_on_previous_text else 'off'}"
    )
    print()

    if multilingual and args.task == "translate":
        print(
            "Note: task=translate turns every "
            "segment into English."
        )
        print()

    print("Subtitle configuration:")
    print(
        f"  Max line length:  {MAX_LINE_LENGTH}"
    )
    print(
        f"  Max lines:        {MAX_LINES}"
    )
    print(
        f"  Max CPS:          {MAX_CPS}"
    )
    print(
        f"  Min duration:     {MIN_DURATION}s"
    )
    print(
        f"  Max duration:     {MAX_DURATION}s"
    )
    print(
        f"  Minimum gap:      {MIN_GAP}s"
    )
    print()

    # --------------------------------------------------------
    # Duration
    # --------------------------------------------------------

    print("Reading media information...")

    try:
        duration = get_duration(
            input_file
        )

    except Exception as e:
        print(
            f"Warning: couldn't determine "
            f"duration: {e}"
        )
        duration = 0.0

    if duration:
        print(
            f"Duration:       "
            f"{format_time(duration)}"
        )

    print()

    # --------------------------------------------------------
    # Load Whisper
    # --------------------------------------------------------

    print("Loading Whisper model...")

    model = WhisperModel(
        MODEL,
        device=DEVICE,
        compute_type=COMPUTE_TYPE,
    )

    print("Transcribing...")
    print()

    transcription_start = (
        time.monotonic()
    )

    segments, info = model.transcribe(
        str(input_file),
        language=language_hint,
        task=args.task,
        vad_filter=VAD_FILTER,
        multilingual=multilingual,
        condition_on_previous_text=(
            condition_on_previous_text
        ),
        language_detection_segments=(
            args.detect_segments
        ),
        language_detection_threshold=(
            args.detect_threshold
        ),
    )

    # --------------------------------------------------------
    # Consume generator
    # --------------------------------------------------------

    processed_segments = []

    for segment in segments:

        processed_segments.append(
            segment
        )

        if duration:
            show_progress(
                float(segment.end),
                duration,
                transcription_start,
            )

    # Final progress
    if duration:
        show_progress(
            duration,
            duration,
            transcription_start,
        )

    print()
    print()

    elapsed = (
        time.monotonic()
        - transcription_start
    )

    print(
        f"Transcription complete in "
        f"{format_time(elapsed)}."
    )

    if duration and elapsed > 0:

        print(
            f"Average speed: "
            f"{duration / elapsed:.2f}x realtime"
        )

    if multilingual:

        print(
            f"Initial language: "
            f"{info.language} "
            f"({info.language_probability * 100:.1f}%)"
        )

        print(
            "Languages were re-detected for "
            "every segment; the value above "
            "is only the first guess."
        )

    else:

        print(
            f"Detected language: "
            f"{info.language} "
            f"({info.language_probability * 100:.1f}%)"
        )

    # --------------------------------------------------------
    # Subtitle formatting
    # --------------------------------------------------------

    print("Formatting subtitles...")

    subtitles = build_subtitles(
        processed_segments
    )

    print(
        f"Generated {len(subtitles)} "
        f"subtitle cues."
    )

    # --------------------------------------------------------
    # Write SRT
    # --------------------------------------------------------

    print(
        f"Writing: {output_file}"
    )

    try:
        with open(
            output_file,
            "w",
            encoding="utf-8",
        ) as f:

            for index, subtitle in enumerate(
                subtitles,
                start=1,
            ):

                f.write(
                    f"{index}\n"
                )

                f.write(
                    f"{format_srt_time(subtitle['start'])} "
                    f"--> "
                    f"{format_srt_time(subtitle['end'])}\n"
                )

                f.write(
                    f"{subtitle['text']}\n\n"
                )

    except OSError as e:
        print(
            f"Error: couldn't write "
            f"{output_file}: {e}"
        )
        return 1

    print()
    print("Done! 🎬")
    print(
        f"Subtitle file: {output_file}"
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
