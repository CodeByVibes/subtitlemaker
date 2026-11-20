"""Command line interface."""

import argparse
import dataclasses
import logging
from pathlib import Path
from typing import Any

from rich.console import Console

from . import __version__
from .config import DEVICES, ConfigError, ModelConfig, SubtitleStyle
from .formats import DEFAULT_FORMAT, FORMATS
from .log import LOGGER_NAME, setup_logging
from .pipeline import OutputError, process_file
from .planning import expand_inputs, plan_all_outputs
from .progress import TranscriptionProgress
from .settings import (
    DEFAULT_DETECT_SEGMENTS,
    DEFAULT_DETECT_THRESHOLD,
    DEFAULT_TASK,
    TASKS,
    Settings,
    resolve_settings,
)

log = logging.getLogger(LOGGER_NAME)


class _ProgressBar:
    """
    Shows `process_file` progress as a Rich bar.

    The bar starts with the first report (just before the first segment is
    decoded) and stops with the last one, so log lines around transcription
    are not drawn over a live bar. Call `close` in a `finally` in case the
    last report never comes.
    """

    def __init__(self, console: Console, enabled: bool) -> None:
        self._console = console
        self._enabled = enabled
        self._bar: TranscriptionProgress | None = None
        self._finished = False

    def __call__(self, position: float, duration: float) -> None:

        if not self._enabled or not duration or self._finished:
            return

        if self._bar is None:
            self._bar = TranscriptionProgress(duration, self._console, enabled=True)
            self._bar.__enter__()

        self._bar.update(position)

        if position >= duration:
            self.close()

    def close(self) -> None:

        self._finished = True

        if self._bar is not None:
            self._bar.__exit__(None, None, None)
            self._bar = None


def main() -> int:
    """Entry point: run the command line and return the exit code."""

    try:
        return _run()

    except KeyboardInterrupt:
        # Nothing is half-written: outputs are written after transcription.
        log.error("interrupted")
        return 130


def option_help() -> dict[str, str]:
    """The help text of every option, by its name in `argparse` (e.g. `max_lines`)."""

    return {
        action.dest: action.help
        for action in _build_parser()._actions
        if action.help and action.help != argparse.SUPPRESS
    }


def _build_parser() -> argparse.ArgumentParser:
    """The argument parser. Building it does no work and imports nothing heavy."""

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
            "Source language (e.g. sv). Several "
            "comma-separated codes (e.g. he,en) "
            "switch on per-segment language "
            "detection, like -m; the list does "
            "not limit which languages can be "
            "detected"
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
        choices=TASKS,
        default=DEFAULT_TASK,
        help=(
            "transcribe = subtitles in the spoken language; "
            "translate = translate to English (default: transcribe)"
        ),
    )

    parser.add_argument(
        "--detect-segments",
        type=int,
        default=DEFAULT_DETECT_SEGMENTS,
        metavar="N",
        help=(
            "Segments sampled for the initial "
            "language detection (default: 1)"
        ),
    )

    parser.add_argument(
        "--detect-threshold",
        type=float,
        default=DEFAULT_DETECT_THRESHOLD,
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
        "--prompt",
        metavar="TEXT",
        help=(
            "Text for Whisper to continue from, in the style you want; "
            "a punctuated sentence or two brings back missing "
            "punctuation (default: none)"
        ),
    )

    parser.add_argument(
        "--hallucination-silence-threshold",
        type=float,
        metavar="SEC",
        help=(
            "Skip silences longer than this where Whisper seems to "
            "invent text, e.g. 2; needs word timestamps "
            "(default: 0, off)"
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
        "--max-pause",
        type=float,
        metavar="SEC",
        help=(
            "Start a new subtitle when there is at least this much "
            "silence between two words (default: 1.0)"
        ),
    )

    style_group.add_argument(
        "--min-gap",
        type=float,
        metavar="SEC",
        help="Minimum gap between subtitles (default: 0.05)",
    )

    style_group.add_argument(
        "--linger",
        type=float,
        metavar="SEC",
        help=(
            "Keep a subtitle up this long after its speech ends, "
            "if the time is free; 0 turns it off (default: 0.5)"
        ),
    )

    style_group.add_argument(
        "--close-gap",
        type=float,
        metavar="SEC",
        help=(
            "Close a gap between two subtitles that is shorter than "
            "this, so text does not flicker; 0 turns it off (default: 0.5)"
        ),
    )

    style_group.add_argument(
        "--start-offset",
        type=float,
        metavar="SEC",
        help=(
            "Move every subtitle this much later (negative: earlier). Whisper's word "
            "times run early, so cues otherwise appear before the voice; 0 turns "
            "it off; between -30 and 30 (default: 0.15)"
        ),
    )

    return parser


def _resolve_settings(args: argparse.Namespace, parser: argparse.ArgumentParser) -> Settings:
    """
    Combine defaults, the config file and the command line.

    Precedence: defaults < config file < command line. Invalid values end
    the program through `parser.error` (a usage error, exit code 2).
    """

    # These two are about the flags themselves, so the message names them.
    if args.detect_segments < 1:
        parser.error("--detect-segments must be at least 1")

    if not 0.0 < args.detect_threshold <= 1.0:
        parser.error("--detect-threshold must be greater than 0 and at most 1")

    if args.output and args.output_dir:
        parser.error("-o/--output and -d/--output-dir cannot be combined")

    try:
        return resolve_settings(
            config=args.config,
            style={
                field.name: getattr(args, field.name)
                for field in dataclasses.fields(SubtitleStyle)
            },
            # Command line option -> ModelConfig field
            model={
                field: getattr(args, option)
                for option, field in (
                    ("model", "name"),
                    ("device", "device"),
                    ("compute_type", "compute_type"),
                    ("word_timestamps", "word_timestamps"),
                    ("prompt", "initial_prompt"),
                    ("hallucination_silence_threshold", "hallucination_silence_threshold"),
                )
            },
            formats=args.format,
            task=args.task,
            language=args.language,
            multilingual=args.multilingual,
            condition_on_previous_text=args.condition_on_previous_text,
            detect_segments=args.detect_segments,
            detect_threshold=args.detect_threshold,
        )

    except ConfigError as e:
        parser.error(str(e))


def _load_model_for_run(
    model_config: ModelConfig, multilingual: bool, task: str, style: SubtitleStyle
) -> tuple[Any, ModelConfig] | None:
    """
    Resolve and load the model, logging what is used.

    Returns `(model, config_used)`, or `None` after logging an error.
    """

    # Imported only now: loading the machine learning libraries is slow,
    # and --help, --version and argument errors don't need them.
    from .transcribe import ModelError, load_for_run

    try:
        return load_for_run(model_config, multilingual, task, style)

    except ModelError as e:
        log.error("%s", e)
        return None


def _run() -> int:

    parser = _build_parser()

    args = parser.parse_args()

    console = setup_logging(
        quiet=args.quiet,
        verbose=args.verbose,
    )

    settings = _resolve_settings(args, parser)

    # --------------------------------------------------------
    # Inputs and where their outputs go
    # --------------------------------------------------------

    files, problems = expand_inputs(args.inputs, args.recursive)

    for problem in problems:
        log.error("%s", problem)

    if not files:

        if not problems:
            log.error("no media files to process")

        return 1

    try:
        plan = plan_all_outputs(files, settings.formats, args.output, args.output_dir)

    except ValueError as e:
        parser.error(str(e))

    failed = len(problems)
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

        loaded = _load_model_for_run(
            settings.model_config,
            settings.multilingual,
            settings.task,
            settings.style,
        )

        if loaded is None:
            return 1

        model, model_config = loaded

        options = settings.options(model_config)

        for index, file in enumerate(todo, start=1):

            if len(todo) > 1:
                log.info("[%d/%d] %s", index, len(todo), file.name)

            progress = _ProgressBar(console, enabled=not args.quiet)

            try:
                process_file(
                    model, file, plan[file], options, on_progress=progress
                )
                ok = True

            except OutputError as e:
                log.error("%s", e)
                ok = False

            except Exception as e:
                # One bad file must not stop the rest of a batch.
                log.error("failed to process %s: %s", file, e)
                log.debug("details:", exc_info=True)
                ok = False

            finally:
                progress.close()

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
