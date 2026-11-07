"""Plain text transcript output: one cue per line, no timing."""

from ._atomic import atomic_open


def write_txt(subtitles, path):
    """Write the text of each cue to `path`, one cue per line."""

    with atomic_open(path) as f:

        for subtitle in subtitles:
            f.write(subtitle["text"].replace("\n", " ") + "\n")
