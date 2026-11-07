"""SubRip (.srt) output."""

from collections.abc import Sequence
from pathlib import Path

from .._types import Cue
from ._atomic import atomic_open
from ._timestamp import format_timestamp


def format_srt_time(seconds: float) -> str:
    """Convert seconds to an SRT timestamp (`HH:MM:SS,mmm`)."""

    return format_timestamp(seconds, ",")


def write_srt(subtitles: Sequence[Cue], path: str | Path) -> None:
    """Write subtitle cues to `path` as SRT."""

    with atomic_open(path) as f:

        for index, subtitle in enumerate(subtitles, start=1):

            f.write(f"{index}\n")

            f.write(
                f"{format_srt_time(subtitle['start'])} "
                f"--> "
                f"{format_srt_time(subtitle['end'])}\n"
            )

            f.write(f"{subtitle['text']}\n\n")
