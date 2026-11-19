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


# Read-only on purpose: the segmenter only reads these, so immutable objects
# (faster-whisper's own, and the recorded copies in `pipeline`) qualify too.
class WordLike(Protocol):
    @property
    def word(self) -> str: ...

    @property
    def start(self) -> float | None: ...

    @property
    def end(self) -> float | None: ...


class SegmentLike(Protocol):
    @property
    def text(self) -> str: ...

    @property
    def start(self) -> float: ...

    @property
    def end(self) -> float: ...

    @property
    def words(self) -> Sequence[WordLike] | None: ...


# A word of a segment: its text (with its own leading space) and, when
# Whisper gave word timestamps, its start and end.
Token = tuple[str, float | None, float | None]
