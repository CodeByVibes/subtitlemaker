"""Plain text transcript output: one cue per line, no timing."""


def write_txt(subtitles, path):
    """Write the text of each cue to `path`, one cue per line."""

    with open(path, "w", encoding="utf-8") as f:

        for subtitle in subtitles:
            f.write(subtitle["text"].replace("\n", " ") + "\n")
