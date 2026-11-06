"""Time formatting and live transcription progress."""

import time


def format_time(seconds):
    """Format seconds as HH:MM:SS."""

    seconds = max(0, int(seconds))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def show_progress(
    processed,
    total,
    start_time,
):
    """Display live transcription progress."""

    elapsed = (
        time.monotonic()
        - start_time
    )

    if total > 0:
        progress = min(
            processed / total,
            1.0,
        )
    else:
        progress = 0.0

    percent = progress * 100

    # Video seconds processed per real second
    if elapsed > 0:
        speed = processed / elapsed
    else:
        speed = 0.0

    # ETA in real seconds
    if speed > 0 and total > processed:
        eta = (
            total - processed
        ) / speed
    else:
        eta = 0

    # Progress bar
    bar_width = 30

    filled = int(
        bar_width * progress
    )

    if filled >= bar_width:
        bar = "━" * bar_width

    else:
        bar = (
            "━" * filled
            + "╸"
            + "━" * (
                bar_width
                - filled
                - 1
            )
        )

    print(
        f"\rTranscribing "
        f"━{bar} "
        f"{percent:5.1f}% | "
        f"{format_time(processed)} / "
        f"{format_time(total)} | "
        f"{speed:4.1f}x | "
        f"ETA {format_time(eta)}",
        end="",
        flush=True,
    )
