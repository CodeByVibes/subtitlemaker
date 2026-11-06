"""Time formatting and the live transcription progress display."""

from rich.progress import BarColumn, Progress, ProgressColumn, TaskProgressColumn, TextColumn
from rich.text import Text


def format_time(seconds):
    """Format seconds as HH:MM:SS."""

    seconds = max(0, int(seconds))

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60

    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class _PositionColumn(ProgressColumn):
    """Media position, e.g. `00:00:06 / 00:01:00`."""

    def render(self, task):
        return Text(f"{format_time(task.completed)} / {format_time(task.total)}")


class _SpeedColumn(ProgressColumn):
    """Media seconds processed per real second, e.g. ` 7.4x`."""

    def render(self, task):
        elapsed = task.elapsed or 0

        speed = task.completed / elapsed if elapsed > 0 else 0.0

        return Text(f"{speed:4.1f}x")


class _EtaColumn(ProgressColumn):
    """Estimated real time remaining, based on the average speed so far."""

    def render(self, task):
        elapsed = task.elapsed or 0

        speed = task.completed / elapsed if elapsed > 0 else 0.0

        if speed > 0 and task.total > task.completed:
            eta = (task.total - task.completed) / speed

        else:
            eta = 0

        return Text(f"ETA {format_time(eta)}")


class TranscriptionProgress:
    """
    Context manager showing transcription progress.

        with TranscriptionProgress(duration, console) as progress:
            progress.update(seconds_processed)

    With `enabled=False` (or an unknown duration) it does nothing.
    """

    def __init__(self, total, console, enabled=True):
        self._total = float(total)
        self._enabled = bool(enabled and total)

        self._progress = Progress(
            TextColumn("Transcribing"),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            _PositionColumn(),
            _SpeedColumn(),
            _EtaColumn(),
            console=console,
            disable=not self._enabled,
        )

        self._task = None

    def __enter__(self):
        self._progress.start()
        self._task = self._progress.add_task("", total=self._total)

        return self

    def __exit__(self, exc_type, exc, tb):
        self._progress.stop()

    def update(self, processed):
        """Report that `processed` seconds of media are done."""

        if self._enabled:
            self._progress.update(
                self._task,
                completed=min(float(processed), self._total),
            )
