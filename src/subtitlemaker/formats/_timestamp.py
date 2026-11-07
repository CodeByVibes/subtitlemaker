"""Timestamp formatting shared by the subtitle formats."""


def format_timestamp(seconds, decimal):
    """
    Format seconds as `HH:MM:SS<decimal>mmm`.

    SubRip uses a comma as the decimal separator and WebVTT a dot. Hours
    are not capped at 23.
    """

    milliseconds = int(round(seconds * 1000))

    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    secs, milliseconds = divmod(milliseconds, 1000)

    return f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal}{milliseconds:03d}"
