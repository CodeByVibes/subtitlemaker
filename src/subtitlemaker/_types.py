"""Shapes passed between modules.

`Cue` is what the segmenter produces and the format writers consume. The
`SegmentLike` and `WordLike` protocols describe the parts of a faster-whisper
`Segment` and `Word` that the segmenter reads, so tests can pass simple fakes.
"""

from collections.abc import Sequence
from typing import Protocol, TypedDict


class Cue(TypedDict):
    """One subtitle: start and end in seconds, text with lines joined by newlines."""

    start: float
    end: float
    text: str


class WordLike(Protocol):
    word: str
    start: float | None
    end: float | None


class SegmentLike(Protocol):
    text: str
    start: float
    end: float
    words: Sequence[WordLike] | None


# A word of a segment: its text (with its own leading space) and, when
# Whisper gave word timestamps, its start and end.
Token = tuple[str, float | None, float | None]
