"""Finds out how long files are without freezing the window.

Opening a file to read its length can be slow (a network share, a sleeping
disk), so it happens on a small pool of threads and the answer comes back as
a signal.
"""

from collections.abc import Iterable
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from ..media import get_duration


class _Answers(QObject):
    """Carries answers from the pool threads to the Qt thread."""

    answer = Signal(object, float)


class _Probe(QRunnable):

    def __init__(self, path: Path, answers: _Answers) -> None:
        super().__init__()
        self._path = path
        self._answers = answers

    def run(self) -> None:

        try:
            duration = get_duration(self._path)

        except Exception:
            # Unreadable now; the real run will report why.
            duration = 0.0

        self._answers.answer.emit(self._path, float(duration))


class DurationProber(QObject):
    """Probes file lengths in the background."""

    # (path, seconds); 0.0 when the length could not be read
    duration_ready = Signal(object, float)

    def __init__(self, parent: QObject | None = None, threads: int = 2) -> None:
        super().__init__(parent)

        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(threads)

        self._answers = _Answers(self)
        self._answers.answer.connect(self._forward)

    def probe(self, paths: Iterable[Path]) -> None:
        """Start probing `paths`; each answer arrives as `duration_ready`."""

        for path in paths:
            self._pool.start(_Probe(path, self._answers))

    def shutdown(self) -> None:
        """Wait for the probes already running (queued ones are dropped)."""

        self._pool.clear()
        self._pool.waitForDone()

    @Slot(object, float)
    def _forward(self, path: Path, duration: float) -> None:
        self.duration_ready.emit(path, duration)
