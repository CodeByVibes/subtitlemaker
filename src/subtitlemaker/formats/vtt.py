"""WebVTT (.vtt) output."""

from ._atomic import atomic_open
from ._timestamp import format_timestamp


def format_vtt_time(seconds):
    """Convert seconds to a WebVTT timestamp (`HH:MM:SS.mmm`)."""

    return format_timestamp(seconds, ".")


def _escape(text):
    # In WebVTT cue text, & < > are markup. Escaping > also keeps a literal
    # "-->" from being read as the start of a timing line.
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_vtt(subtitles, path):
    """Write subtitle cues to `path` as WebVTT."""

    with atomic_open(path) as f:

        f.write("WEBVTT\n\n")

        for subtitle in subtitles:

            f.write(
                f"{format_vtt_time(subtitle['start'])} "
                f"--> "
                f"{format_vtt_time(subtitle['end'])}\n"
            )

            f.write(f"{_escape(subtitle['text'])}\n\n")
