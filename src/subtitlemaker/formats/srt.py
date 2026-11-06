"""SubRip (.srt) output."""


def format_srt_time(seconds):
    """Convert seconds to SRT timestamp."""

    milliseconds = int(round(seconds * 1000))

    hours = milliseconds // 3_600_000
    milliseconds %= 3_600_000

    minutes = milliseconds // 60_000
    milliseconds %= 60_000

    seconds = milliseconds // 1000
    milliseconds %= 1000

    return (
        f"{hours:02d}:"
        f"{minutes:02d}:"
        f"{seconds:02d},"
        f"{milliseconds:03d}"
    )


def write_srt(subtitles, path):
    """Write subtitle cues to `path` as SRT."""

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:

        for index, subtitle in enumerate(
            subtitles,
            start=1,
        ):

            f.write(
                f"{index}\n"
            )

            f.write(
                f"{format_srt_time(subtitle['start'])} "
                f"--> "
                f"{format_srt_time(subtitle['end'])}\n"
            )

            f.write(
                f"{subtitle['text']}\n\n"
            )
