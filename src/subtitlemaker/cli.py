"""Command line interface."""

import argparse
import dataclasses
import logging
import time
from pathlib import Path

from .config import ConfigError, load_config
from .formats.srt import write_srt
from .log import LOGGER_NAME, setup_logging
from .media import get_duration
from .progress import TranscriptionProgress, format_time
from .segmenter import build_subtitles

log = logging.getLogger(LOGGER_NAME)


def main():

    # Imported here so --help and argument errors don't wait for the
    # heavy machine learning libraries to load.
    from .transcribe import load_model, parse_language_argument

    parser = argparse.ArgumentParser(
        prog="subtitlemaker",
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

    parser.add_argument(
        "--config",
        metavar="FILE",
        help=(
            "TOML config file (default: "
            "~/.config/subtitlemaker/config.toml "
            "if it exists)"
        ),
    )

    verbosity = parser.add_mutually_exclusive_group()

    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Only show warnings and errors (no progress bar)",
    )

    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show debug output",
    )

    style_group = parser.add_argument_group(
        "subtitle style",
        "Override the defaults and any config file values",
    )

    style_group.add_argument(
        "--max-line-length",
        type=int,
        metavar="N",
        help="Maximum characters per line (default: 42)",
    )

    style_group.add_argument(
        "--max-lines",
        type=int,
        metavar="N",
        help="Maximum lines per subtitle (default: 2)",
    )

    style_group.add_argument(
        "--max-cps",
        type=float,
        metavar="N",
        help="Maximum characters per second (default: 20)",
    )

    style_group.add_argument(
        "--min-duration",
        type=float,
        metavar="SEC",
        help="Minimum subtitle duration (default: 1.0)",
    )

    style_group.add_argument(
        "--max-duration",
        type=float,
        metavar="SEC",
        help="Maximum subtitle duration (default: 7.0)",
    )

    style_group.add_argument(
        "--min-gap",
        type=float,
        metavar="SEC",
        help="Minimum gap between subtitles (default: 0.05)",
    )

    args = parser.parse_args()

    console = setup_logging(
        quiet=args.quiet,
        verbose=args.verbose,
    )

    # --------------------------------------------------------
    # Settings: defaults < config file < command line
    # --------------------------------------------------------

    try:
        style, model_config = load_config(args.config)

        overrides = {
            field.name: getattr(args, field.name)
            for field in dataclasses.fields(style)
            if getattr(args, field.name) is not None
        }

        style = dataclasses.replace(style, **overrides)

    except ConfigError as e:
        parser.error(str(e))

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
            model_config.condition_on_previous_text
            and not multilingual
        )

    input_file = Path(args.input)

    if not input_file.exists():
        log.error("input file does not exist: %s", input_file)
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

    log.info("Input:          %s", input_file)
    log.info("Output:         %s", output_file)
    log.info("Language:       %s", language_display)
    log.info("Task:           %s", args.task)
    log.info("Model:          %s", model_config.name)
    log.info("Device:         %s", model_config.device)
    log.info("Compute type:   %s", model_config.compute_type)
    log.info(
        "Prompt history: %s",
        "on" if condition_on_previous_text else "off",
    )

    if multilingual and args.task == "translate":
        log.warning(
            "task=translate turns every segment into English."
        )

    log.debug("Subtitle configuration:")
    log.debug("  Max line length:  %s", style.max_line_length)
    log.debug("  Max lines:        %s", style.max_lines)
    log.debug("  Max CPS:          %g", style.max_cps)
    log.debug("  Min duration:     %ss", style.min_duration)
    log.debug("  Max duration:     %ss", style.max_duration)
    log.debug("  Minimum gap:      %ss", style.min_gap)

    # --------------------------------------------------------
    # Duration
    # --------------------------------------------------------

    log.debug("Reading media information...")

    try:
        duration = get_duration(
            input_file
        )

    except Exception as e:
        log.warning("couldn't determine duration: %s", e)
        duration = 0.0

    if duration:
        log.info("Duration:       %s", format_time(duration))

    # --------------------------------------------------------
    # Load Whisper
    # --------------------------------------------------------

    log.info("Loading Whisper model...")

    model = load_model(
        model_config.name,
        model_config.device,
        model_config.compute_type,
    )

    log.info("Transcribing...")

    transcription_start = (
        time.monotonic()
    )

    segments, info = model.transcribe(
        str(input_file),
        language=language_hint,
        task=args.task,
        vad_filter=model_config.vad_filter,
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

    with TranscriptionProgress(
        duration,
        console,
        enabled=not args.quiet,
    ) as progress:

        for segment in segments:

            processed_segments.append(
                segment
            )

            progress.update(float(segment.end))

        # Final progress
        progress.update(duration)

    elapsed = (
        time.monotonic()
        - transcription_start
    )

    log.info(
        "Transcription complete in %s.",
        format_time(elapsed),
    )

    if duration and elapsed > 0:

        log.info(
            "Average speed: %.2fx realtime",
            duration / elapsed,
        )

    if multilingual:

        log.info(
            "Initial language: %s (%.1f%%)",
            info.language,
            info.language_probability * 100,
        )

        log.info(
            "Languages were re-detected for "
            "every segment; the value above "
            "is only the first guess."
        )

    else:

        log.info(
            "Detected language: %s (%.1f%%)",
            info.language,
            info.language_probability * 100,
        )

    # --------------------------------------------------------
    # Subtitle formatting
    # --------------------------------------------------------

    log.info("Formatting subtitles...")

    subtitles = build_subtitles(
        processed_segments,
        style,
    )

    log.info("Generated %d subtitle cues.", len(subtitles))

    # --------------------------------------------------------
    # Write SRT
    # --------------------------------------------------------

    log.info("Writing: %s", output_file)

    try:
        write_srt(
            subtitles,
            output_file,
        )

    except OSError as e:
        log.error("couldn't write %s: %s", output_file, e)
        return 1

    log.info("Done! 🎬")
    log.info("Subtitle file: %s", output_file)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
