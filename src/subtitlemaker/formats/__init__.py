"""Subtitle output formats.

A format is a name, a file extension and a function
`write(cues, path)`, where each cue is a dict with `start` and `end` in
seconds and `text` (lines separated by newlines).

To add a format: write a module like `vtt.py` and register it below.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .._types import Cue
from .srt import write_srt
from .txt import write_txt
from .vtt import write_vtt

DEFAULT_FORMAT = "srt"


@dataclass(frozen=True)
class OutputFormat:
    name: str
    extension: str
    write: Callable[[Sequence[Cue], str | Path], None]


FORMATS = {
    f.name: f
    for f in (
        OutputFormat("srt", "srt", write_srt),
        OutputFormat("vtt", "vtt", write_vtt),
        OutputFormat("txt", "txt", write_txt),
    )
}


def parse_formats(value: str | None) -> list[str]:
    """
    Parse a comma or space separated list of format names.

    Returns the names in order without duplicates; an empty value gives the
    default format. Raises ValueError for unknown names.
    """

    names = []

    for name in re.split(r"[,\s]+", (value or "").strip().lower()):

        if name and name not in names:
            names.append(name)

    unknown = [name for name in names if name not in FORMATS]

    if unknown:
        raise ValueError(
            f"unknown output format(s): {', '.join(unknown)} "
            f"(choose from: {', '.join(FORMATS)})"
        )

    return names or [DEFAULT_FORMAT]


def output_path(base: str | Path, name: str) -> Path:
    """
    The file to write format `name` to, derived from `base`.

    A known format extension on `base` is replaced; anything else (such as
    the dots in `show.s01e01`) is kept and the extension is appended.
    """

    base = Path(base)
    known = {"." + f.extension for f in FORMATS.values()}
    extension = "." + FORMATS[name].extension

    if base.suffix.lower() in known:
        return base.with_suffix(extension)

    return base.with_name(base.name + extension)
