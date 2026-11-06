"""Command line interface."""

import argparse
import time
from pathlib import Path

from ._cuda import reexec_with_cuda_libs
from .config import (
    COMPUTE_TYPE,
    CONDITION_ON_PREVIOUS_TEXT,
    DEVICE,
    MAX_CPS,
    MAX_DURATION,
    MAX_LINE_LENGTH,
    MAX_LINES,
    MIN_DURATION,
    MIN_GAP,
    MODEL,
    VAD_FILTER,
)
from .formats.srt import write_srt
from .media import get_duration
from .progress import format_time, show_progress
from .segmenter import build_subtitles


def main():

    # Must happen before anything imports CTranslate2.
    reexec_with_cuda_libs()

    from .transcribe import load_model, parse_language_argument

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

    model = load_model(
        MODEL,
        DEVICE,
        COMPUTE_TYPE,
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
        write_srt(
            subtitles,
            output_file,
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
