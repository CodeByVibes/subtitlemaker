"""Hands `JobRunner` events over to the Qt thread.

`JobRunner` calls its events on a worker thread, and widgets may only be
touched from the Qt thread. `RunnerBridge` re-emits every event as a Qt
signal: when the receiver lives in the Qt thread, Qt queues the call there.

Connect signals to methods of QObjects (such as a widget). A plain function
or lambda has no thread of its own, so PySide6 would run it on the worker
thread, which is exactly what this class exists to avoid.
"""

from collections.abc import Sequence
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..config import ModelConfig
from ..pipeline import FileResult
from ..runner import Job, JobRunner, ModelLoader, RunnerEvents
from ..settings import Settings


class RunnerBridge(QObject):
    """A `JobRunner` whose events are Qt signals."""

    model_loading = Signal(ModelConfig)
    model_ready = Signal(ModelConfig)
    model_failed = Signal(ModelConfig, str)
    file_started = Signal(Job)
    file_progress = Signal(Job, float, float)  # job, position, duration (seconds)
    file_finished = Signal(Job, FileResult)
    file_failed = Signal(Job, str)
    file_cancelled = Signal(Job)
    queue_finished = Signal(int, int, int)  # done, failed, cancelled

    def __init__(self, parent: QObject | None = None, load_model: ModelLoader | None = None):
        super().__init__(parent)

        self._runner = JobRunner(_EmitSignals(self), load_model)

    def submit(self, job: Job, settings: Settings) -> None:
        self._runner.submit(job, settings)

    def submit_many(self, items: Sequence[tuple[Job, Settings]]) -> None:
        self._runner.submit_many(items)

    def cancel_current(self) -> None:
        self._runner.cancel_current()

    def cancel_all(self) -> None:
        self._runner.cancel_all()

    def shutdown(self, wait: bool = True) -> None:
        self._runner.shutdown(wait)


class _EmitSignals(RunnerEvents):
    """Turns each runner event into the bridge's signal of the same name."""

    def __init__(self, bridge: RunnerBridge) -> None:
        self._bridge = bridge

    def _emit(self, name: str, *args: Any) -> None:
        getattr(self._bridge, name).emit(*args)

    def model_loading(self, model_config: ModelConfig) -> None:
        self._emit("model_loading", model_config)

    def model_ready(self, model_config: ModelConfig) -> None:
        self._emit("model_ready", model_config)

    def model_failed(self, model_config: ModelConfig, message: str) -> None:
        self._emit("model_failed", model_config, message)

    def file_started(self, job: Job) -> None:
        self._emit("file_started", job)

    def file_progress(self, job: Job, position: float, duration: float) -> None:
        self._emit("file_progress", job, position, duration)

    def file_finished(self, job: Job, result: FileResult) -> None:
        self._emit("file_finished", job, result)

    def file_failed(self, job: Job, message: str) -> None:
        self._emit("file_failed", job, message)

    def file_cancelled(self, job: Job) -> None:
        self._emit("file_cancelled", job)

    def queue_finished(self, done: int, failed: int, cancelled: int) -> None:
        self._emit("queue_finished", done, failed, cancelled)
