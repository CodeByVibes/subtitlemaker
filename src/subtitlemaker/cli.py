"""Command line interface."""

import argparse
import dataclasses
import logging
import time
from pathlib import Path

from . import __version__
from .config import DEVICES, ConfigError, load_config
from .formats import DEFAULT_FORMAT, FORMATS, output_path, parse_formats
from .log import LOGGER_NAME, setup_logging
from .media import find_media, get_duration
from .progress import TranscriptionProgress, format_time
from .segmenter import build_subtitles

log = logging.getLogger(LOGGER_NAME)


@dataclasses.dataclass(frozen=True)
class _Options:
    """Everything that stays the same for every file in a run."""

    style: object
    model_config: object
    task: str
    languages: list
    language_hint: object
    multilingual: bool
    condition_on_previous_text: bool
    detect_segments: int
    detect_threshold: float
    quiet: bool


def _expand_inputs(inputs, recursive):
    """
    Turn the command line inputs into a list of media files.

    Folders contribute the media files in them (and in sub folders with
    `recursive`). Returns `(files, missing)`; duplicates are dropped.
    """

    files = []
    missing = []
    seen = set()

    for raw in inputs:

        path = Path(raw)

        if path.is_dir():
            found = find_media(path, recursive)

            if not found:
                log.warning("no media files found in %s", path)

        elif path.exists():
            found = [path]

        else:
            missing.append(path)
            continue

        for file in found:

            key = file.resolve()

            if key not in seen:
                seen.add(key)
                files.append(file)

    return files, missing


def _plan_outputs(input_file, args, formats):
    """The `{format: path}` files to write for one input."""

    if args.output:

        base = Path(args.output)

        # One format: the name is used exactly as given.
        if len(formats) == 1:
            return {formats[0]: base}

        return {name: output_path(base, name) for name in formats}

    folder = Path(args.output_dir) if args.output_dir else input_file.parent

    return {
        name: folder / f"{input_file.stem}.{FORMATS[name].extension}"
        for name in formats
    }


def _process_file(model, input_file, outputs, options, console):
    """Transcribe one file and write its outputs. Returns True on success."""

    if options.multilingual:

        if options.languages:
            language_display = (
                f"{', '.join(options.languages)} "
                f"(re-detected per segment)"
            )

        else:
            language_display = "auto-detect per segment"

    else:

        language_display = (
            options.languages[0] if options.languages else "auto-detect"
        )

    log.info("Input:          %s", input_file)
    log.info("Output:         %s", ", ".join(str(p) for p in outputs.values()))
    log.info("Language:       %s", language_display)
    log.info("Task:           %s", options.task)
    log.info(
        "Prompt history: %s",
        "on" if options.condition_on_previous_text else "off",
    )

    log.debug("Reading media information...")

    try:
        duration = get_duration(input_file)

    except Exception as e:
        log.warning("couldn't determine duration: %s", e)
        duration = 0.0

    if duration:
        log.info("Duration:       %s", format_time(duration))

    log.info("Transcribing...")

    transcription_start = time.monotonic()

    segments, info = model.transcribe(
        str(input_file),
        language=options.language_hint,
        task=options.task,
        vad_filter=options.model_config.vad_filter,
        word_timestamps=options.model_config.word_timestamps,
        multilingual=options.multilingual,
        condition_on_previous_text=options.condition_on_previous_text,
        language_detection_segments=options.detect_segments,
        language_detection_threshold=options.detect_threshold,
    )

    processed_segments = []

    with TranscriptionProgress(
        duration,
        console,
        enabled=not options.quiet,
    ) as progress:

        for segment in segments:

            processed_segments.append(segment)

            progress.update(float(segment.end))

        # Final progress
        progress.update(duration)

    elapsed = time.monotonic() - transcription_start

    log.info("Transcription complete in %s.", format_time(elapsed))

    if duration and elapsed > 0:
        log.info("Average speed: %.2fx realtime", duration / elapsed)

    if options.multilingual:

        log.info(
            "Initial language: %s (%.1f%%)",
            info.language,
            info.language_probability * 100,
        )

        log.info(
            "Languages were re-detected for every segment; "
            "the value above is only the first guess."
        )

    else:

        log.info(
            "Detected language: %s (%.1f%%)",
            info.language,
            info.language_probability * 100,
        )

    log.info("Formatting subtitles...")

    subtitles = build_subtitles(processed_segments, options.style)

    log.info("Generated %d subtitle cues.", len(subtitles))

    for name, path in outputs.items():

        log.info("Writing: %s", path)

        try:
            FORMATS[name].write(subtitles, path)

        except OSError as e:
            log.error("couldn't write %s: %s", path, e)
            return False

    return True


def main():

    # Imported here so --help and argument errors don't wait for the
    # heavy machine learning libraries to load.
    from .transcribe import (
        ModelError,
        load_model,
        parse_language_argument,
        resolve_model_config,
    )

    parser = argparse.ArgumentParser(
        prog="subtitlemaker",
        description=(
            "Generate subtitles (SRT, WebVTT or plain text) "
            "from audio and video files using Faster-Whisper."
        )
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "inputs",
        nargs="+",
        metavar="INPUT",
        help=(
            "Video/audio files, or folders to scan for them "
            "(see -r)"
        ),
    )

    parser.add_argument(
        "-f",
        "--format",
        metavar="FORMATS",
        help=(
            "Output format(s), comma separated: "
            f"{', '.join(FORMATS)} (default: {DEFAULT_FORMAT}). "
            "Each is written next to the input"
        ),
    )

    parser.add_argument(
        "-o",
        "--output",
        metavar="FILE",
        help=(
            "Output file, for a single input. With several "
            "formats it is a base name and the extension is "
            "replaced for each one"
        ),
    )

    parser.add_argument(
        "-d",
        "--output-dir",
        metavar="DIR",
        help="Write outputs here instead of next to each input",
    )

    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Also look in sub folders of folders given as input",
    )

    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help=(
            "Skip inputs whose output files all exist already "
            "(by default they are overwritten)"
        ),
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
        default="transcribe",
        help=(
            "transcribe = subtitles in the spoken language; "
            "translate = translate to English (default: transcribe)"
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

    model_group = parser.add_argument_group(
        "model",
        "Override the defaults and any config file values",
    )

    model_group.add_argument(
        "--model",
        metavar="NAME",
        help=(
            "Whisper model: tiny, base, small, medium, large-v3, "
            "turbo, ..., a Hugging Face repo id, or a local path "
            "(default: large-v3 on GPU, small on CPU). Models are "
            "downloaded on first use."
        ),
    )

    model_group.add_argument(
        "--device",
        choices=DEVICES,
        help=(
            "Where to run: auto uses the GPU if one is found and "
            "falls back to the CPU (default: auto)"
        ),
    )

    model_group.add_argument(
        "--compute-type",
        metavar="TYPE",
        help=(
            "Numeric precision, e.g. float16, int8_float16, int8, "
            "float32 (default: float16 on GPU, int8 on CPU)"
        ),
    )

    model_group.add_argument(
        "--word-timestamps",
        action=argparse.BooleanOptionalAction,
        default=None,
        help=(
            "Time cues from individual words, which splits long "
            "sentences accurately (default: on; --no-word-timestamps "
            "is faster but less precise)"
        ),
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

        # Command line option -> ModelConfig field
        model_overrides = {
            field: getattr(args, option)
            for option, field in (
                ("model", "name"),
                ("device", "device"),
                ("compute_type", "compute_type"),
                ("word_timestamps", "word_timestamps"),
            )
            if getattr(args, option) is not None
        }

        model_config = dataclasses.replace(model_config, **model_overrides)

    except ConfigError as e:
        parser.error(str(e))

    # --------------------------------------------------------
    # Output options
    # --------------------------------------------------------

    try:
        formats = parse_formats(args.format)

    except ValueError as e:
        parser.error(str(e))

    if args.output and args.output_dir:
        parser.error("-o/--output and -d/--output-dir cannot be combined")

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

    # --------------------------------------------------------
    # Inputs and where their outputs go
    # --------------------------------------------------------

    files, missing = _expand_inputs(args.inputs, args.recursive)

    for path in missing:
        log.error("input file does not exist: %s", path)

    if not files:

        if not missing:
            log.error("no media files to process")

        return 1

    if args.output and len(files) > 1:
        parser.error(
            "-o/--output can only be used with a single input file; "
            "use -d/--output-dir for several"
        )

    plan = {file: _plan_outputs(file, args, formats) for file in files}

    owners = {}

    for file, outputs in plan.items():

        for path in outputs.values():

            if path in owners:
                parser.error(
                    f"{owners[path]} and {file} would both write {path}; "
                    f"use separate output folders"
                )

            owners[path] = file

    failed = len(missing)
    skipped = 0
    todo = []

    for file in files:

        if args.skip_existing and all(p.exists() for p in plan[file].values()):
            log.info("Skipping %s (output exists)", file)
            skipped += 1

        else:
            todo.append(file)

    # --------------------------------------------------------
    # Model: resolved and loaded once, only if there is work
    # --------------------------------------------------------

    done = 0

    if todo:

        if args.output_dir:

            try:
                Path(args.output_dir).mkdir(parents=True, exist_ok=True)

            except OSError as e:
                log.error("couldn't create output folder %s: %s", args.output_dir, e)
                return 1

        # A GPU that turns out to be unusable only falls back to the CPU when
        # the device was left on auto.
        allow_cpu_fallback = model_config.device == "auto"

        try:
            model_config = resolve_model_config(model_config)

        except ModelError as e:
            log.error("%s", e)
            return 1

        log.info("Model:          %s", model_config.name)
        log.info("Device:         %s", model_config.device)
        log.info("Compute type:   %s", model_config.compute_type)

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

        log.info("Loading Whisper model...")

        try:
            model, model_config = load_model(
                model_config,
                allow_cpu_fallback=allow_cpu_fallback,
            )

        except ModelError as e:
            log.error("%s", e)
            return 1

        options = _Options(
            style=style,
            model_config=model_config,
            task=args.task,
            languages=languages,
            language_hint=language_hint,
            multilingual=multilingual,
            condition_on_previous_text=condition_on_previous_text,
            detect_segments=args.detect_segments,
            detect_threshold=args.detect_threshold,
            quiet=args.quiet,
        )

        for index, file in enumerate(todo, start=1):

            if len(todo) > 1:
                log.info("[%d/%d] %s", index, len(todo), file.name)

            try:
                ok = _process_file(model, file, plan[file], options, console)

            except Exception as e:
                # One bad file must not stop the rest of a batch.
                log.error("failed to process %s: %s", file, e)
                log.debug("details:", exc_info=True)
                ok = False

            if ok:
                done += 1

            else:
                failed += 1

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    if failed:

        log.warning(
            "%d done, %d skipped, %d failed",
            done,
            skipped,
            failed,
        )

        return 1

    if len(files) == 1 and done == 1:

        log.info("Done! 🎬")
        log.info(
            "Subtitle file: %s",
            ", ".join(str(p) for p in plan[files[0]].values()),
        )

    else:
        log.info("Done! 🎬 %d done, %d skipped", done, skipped)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
