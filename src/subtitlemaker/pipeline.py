"""Transcribe one file and write its subtitles.

This is the part of a run that does not depend on the command line, so the
command line and the desktop app both call `process_file`. It reports
progress through a callback, can be cancelled from another thread, and
returns what happened as a `FileResult`.
"""

import dataclasses
import logging
import threading
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from ._types import Cue, SegmentLike
from .config import ModelConfig, SubtitleStyle
from .formats import FORMATS
from .log import LOGGER_NAME
from .media import get_duration
from .progress import format_time
from .segmenter import build_subtitles, lacks_punctuation

log = logging.getLogger(LOGGER_NAME)

# Called as `on_progress(position, duration)`, both in seconds of media.
# `duration` is 0 when it could not be determined. The first call reports
# 0.0 (transcription is starting) and the last one reports `duration`.
ProgressCallback = Callable[[float, float], None]


class Cancelled(Exception):
    """Processing was stopped through the `cancel` event. Nothing was written."""


class OutputError(Exception):
    """An output file could not be written. The message is ready to show."""


@dataclasses.dataclass(frozen=True)
class Options:
    """Everything that stays the same for every file in a run."""

    style: SubtitleStyle
    model_config: ModelConfig
    task: str
    languages: list[str]
    language_hint: str | None
    multilingual: bool
    condition_on_previous_text: bool
    detect_segments: int
    detect_threshold: float


@dataclasses.dataclass(frozen=True)
class RecordedWord:
    """A word of a transcript: what the segmenter reads from faster-whisper's `Word`."""

    word: str
    start: float | None
    end: float | None


@dataclasses.dataclass(frozen=True)
class RecordedSegment:
    """A segment of a transcript: what the segmenter reads from faster-whisper's `Segment`."""

    text: str
    start: float
    end: float
    words: tuple[RecordedWord, ...] | None


def record_segments(segments: Iterable[SegmentLike]) -> list[RecordedSegment]:
    """
    Light copies of Whisper segments, holding only what `build_subtitles` reads.

    The originals carry token ids, probabilities and more, which is wasteful to
    keep for every file of a long queue; these are enough to build the same
    subtitles again, with other settings, without running the model.
    """

    return [
        RecordedSegment(
            text=segment.text,
            start=float(segment.start),
            end=float(segment.end),
            words=(
                None
                if segment.words is None
                else tuple(
                    RecordedWord(
                        word=word.word,
                        start=None if word.start is None else float(word.start),
                        end=None if word.end is None else float(word.end),
                    )
                    for word in segment.words
                )
            ),
        )
        for segment in segments
    ]


@dataclasses.dataclass(frozen=True)
class FileResult:
    """What `process_file` did for one file."""

    input_file: Path
    outputs: dict[str, Path]
    duration: float  # seconds of media, 0.0 if unknown
    elapsed: float  # seconds spent transcribing
    language: str
    language_probability: float
    segments: Sequence[RecordedSegment]  # the transcript, to build the cues again
    subtitles: list[Cue]
    warnings: list[str]
    style: SubtitleStyle  # the style `subtitles` were built with
    text_language: str | None  # the language the line breaking assumed (None: mixed or unknown)

    def rebuild(self, style: SubtitleStyle | None = None) -> list[Cue]:
        """The subtitles built again from the transcript, with `style` (default: the one used)."""

        return build_subtitles(self.segments, style or self.style, self.text_language)


def process_file(
    model: Any,
    input_file: Path,
    outputs: dict[str, Path],
    options: Options,
    on_progress: ProgressCallback | None = None,
    cancel: threading.Event | None = None,
) -> FileResult:
    """
    Transcribe one file and write its outputs.

    `cancel` is checked before work starts and after every segment; when it
    is set `Cancelled` is raised and nothing is written. Raises
    `OutputError` if a file cannot be written; any other exception comes
    from reading or decoding the input.
    """

    warnings: list[str] = []

    if options.multilingual:

        if options.languages:
            language_display = (
                f"auto-detect per segment "
                f"(listed: {', '.join(options.languages)}; "
                f"detection is not limited to these)"
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

    _check_cancelled(cancel)

    log.debug("Reading media information...")

    try:
        duration = get_duration(input_file)

    except Exception as e:
        message = f"couldn't determine duration: {e}"
        log.warning("%s", message)
        warnings.append(message)
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
        initial_prompt=options.model_config.initial_prompt or None,
        hallucination_silence_threshold=(
            options.model_config.hallucination_silence_threshold or None
        ),
        language_detection_segments=options.detect_segments,
        language_detection_threshold=options.detect_threshold,
    )

    processed_segments = []

    if on_progress is not None:
        on_progress(0.0, duration)

    for segment in segments:

        _check_cancelled(cancel)

        processed_segments.append(segment)

        if on_progress is not None:
            on_progress(float(segment.end), duration)

    # Final progress
    if on_progress is not None:
        on_progress(duration, duration)

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

    # The language of the subtitle text, for line breaking: English when
    # translating, unknown when it may change from segment to segment.
    if options.multilingual:
        text_language = None

    elif options.task == "translate":
        text_language = "en"

    else:
        text_language = info.language

    if lacks_punctuation(processed_segments, text_language):

        message = (
            f"Whisper wrote almost no punctuation for {input_file.name}, so "
            f"subtitles will end in the middle of sentences. This tends to "
            f"happen when a recording starts mid-sentence. Try again with a "
            f"sentence or two in the same language and style, e.g. "
            f"--prompt \"Hello, everyone. Let's begin.\""
        )

        log.warning("%s", message)
        warnings.append(message)

    recorded = record_segments(processed_segments)
    subtitles = build_subtitles(recorded, options.style, text_language)

    log.info("Generated %d subtitle cues.", len(subtitles))

    _check_cancelled(cancel)

    for name, path in outputs.items():

        log.info("Writing: %s", path)

        try:
            FORMATS[name].write(subtitles, path)

        except OSError as e:
            raise OutputError(f"couldn't write {path}: {e}") from e

    return FileResult(
        input_file=input_file,
        outputs=outputs,
        duration=duration,
        elapsed=elapsed,
        language=info.language,
        language_probability=info.language_probability,
        segments=recorded,
        subtitles=subtitles,
        warnings=warnings,
        style=options.style,
        text_language=text_language,
    )


def _check_cancelled(cancel: threading.Event | None) -> None:

    if cancel is not None and cancel.is_set():
        raise Cancelled()
