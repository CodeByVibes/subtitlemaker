"""A background worker that transcribes a queue of files.

Built for the desktop app, and free of any user interface toolkit: the work
runs on one worker thread and everything that happens is reported through
the methods of a `RunnerEvents` object. Those methods are called **on the
worker thread**, so an interface must hand them over to its own thread (in
Qt, by emitting signals).

- One model is kept loaded and reused for as long as the settings that
  select it (name, device, compute type) stay the same; when they change,
  the old model is dropped before the new one loads, so both never need
  GPU memory at once.
- Each job carries the `Settings` it was submitted with, so changing the
  settings in the interface only affects files queued afterwards.
- One bad file never stops the queue.
"""

import gc
import logging
import queue
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import ModelConfig
from .log import LOGGER_NAME
from .pipeline import Cancelled, FileResult, OutputError, process_file
from .settings import Settings

log = logging.getLogger(LOGGER_NAME)

# Loads the model for a run: `(settings) -> (model, config_used)`. Raises
# `transcribe.ModelError` with a message ready to show.
ModelLoader = Callable[[Settings], tuple[Any, ModelConfig]]


@dataclass(frozen=True)
class Job:
    """One file to transcribe and where its subtitles go (`{format: path}`)."""

    input_file: Path
    outputs: dict[str, Path]


class RunnerEvents:
    """
    What a `JobRunner` reports. Override the methods you care about.

    Called on the worker thread, one at a time and in order. An exception
    raised by a method is logged and otherwise ignored.
    """

    def model_loading(self, model_config: ModelConfig) -> None:
        """A model is about to be loaded (`model_config` as requested)."""

    def model_ready(self, model_config: ModelConfig) -> None:
        """The model is loaded (`model_config` as used: name and device resolved)."""

    def model_failed(self, model_config: ModelConfig, message: str) -> None:
        """The model could not be loaded. Each queued file that needs it also fails."""

    def file_started(self, job: Job) -> None:
        """Work on `job` has begun."""

    def file_progress(self, job: Job, position: float, duration: float) -> None:
        """`position` of `duration` seconds of media are done (`duration` 0 if unknown)."""

    def file_finished(self, job: Job, result: FileResult) -> None:
        """`job` succeeded; its files are written."""

    def file_failed(self, job: Job, message: str) -> None:
        """`job` failed. `message` is ready to show."""

    def file_cancelled(self, job: Job) -> None:
        """`job` was cancelled, before or during its work. Nothing was written."""

    def queue_finished(self, done: int, failed: int, cancelled: int) -> None:
        """The queue ran empty. The counts are for everything since it last did."""


@dataclass
class _Entry:
    job: Job
    settings: Settings
    generation: int
    cancel: threading.Event = field(default_factory=threading.Event)


class JobRunner:
    """
    Transcribes submitted jobs one after another on a background thread.

        runner = JobRunner(MyEvents())
        runner.submit(Job(path, outputs), settings)
        ...
        runner.shutdown()

    The thread starts with the first `submit` and ends with `shutdown`.
    """

    def __init__(
        self,
        events: RunnerEvents | None = None,
        load_model: ModelLoader | None = None,
    ) -> None:
        self._events = events or RunnerEvents()
        self._load_model = load_model or _load_for_settings

        self._queue: queue.Queue[_Entry | None] = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._generation = 0
        self._current: _Entry | None = None
        self._closed = False

        # Only touched by the worker thread.
        self._model: Any = None
        self._model_key: tuple[str, str, str] | None = None
        self._model_config: ModelConfig | None = None
        self._failed_key: tuple[str, str, str] | None = None
        self._failed_message = ""
        self._done = self._failed = self._cancelled = 0

    # --- called from any thread ---------------------------------------------

    def submit(self, job: Job, settings: Settings) -> None:
        """Queue `job`, to be run with `settings`."""

        self.submit_many([(job, settings)])

    def submit_many(self, items: Sequence[tuple[Job, Settings]]) -> None:
        """
        Queue several `(job, settings)` pairs at once.

        They count as one batch: `queue_finished` cannot fire between them,
        however quickly the first one is done. (The lock is held until all
        of them are queued, and the worker takes it before starting each
        file, so it never starts on a batch that is only half queued.)
        """

        with self._lock:

            if self._closed:
                raise RuntimeError("the runner has been shut down")

            for job, settings in items:
                self._queue.put(_Entry(job, settings, self._generation))

            if self._thread is None and items:
                self._thread = threading.Thread(
                    target=self._work, name="subtitlemaker-runner", daemon=True
                )
                self._thread.start()

    def cancel_current(self) -> None:
        """Stop the file being worked on (after its current segment); the queue goes on."""

        with self._lock:

            if self._current is not None:
                self._current.cancel.set()

    def cancel_all(self) -> None:
        """Stop the current file and drop everything queued so far."""

        with self._lock:

            # Anything submitted before this moment is cancelled when the
            # worker reaches it; anything submitted after runs normally.
            self._generation += 1

            if self._current is not None:
                self._current.cancel.set()

    def join(self, timeout: float | None = None) -> bool:
        """Wait until the queue is empty and idle. False if `timeout` ran out first."""

        done = threading.Event()

        def wait() -> None:
            self._queue.join()
            done.set()

        threading.Thread(target=wait, daemon=True).start()

        return done.wait(timeout)

    def shutdown(self, wait: bool = True) -> None:
        """
        Cancel everything and stop the worker thread.

        With `wait`, returns when the thread has ended (a model that is
        loading cannot be interrupted, so that can take a moment).
        """

        with self._lock:

            if self._closed:
                return

            self._closed = True
            self._generation += 1

            if self._current is not None:
                self._current.cancel.set()

            thread = self._thread

        self._queue.put(None)

        if wait and thread is not None:
            thread.join()

    # --- the worker thread ---------------------------------------------------

    def _work(self) -> None:

        while True:

            entry = self._queue.get()

            try:

                if entry is None:
                    return

                try:
                    self._handle(entry)

                finally:
                    with self._lock:
                        self._current = None

                if self._queue.empty():
                    self._finish_batch()

            finally:
                self._queue.task_done()

    def _handle(self, entry: _Entry) -> None:

        job = entry.job

        with self._lock:
            stale = entry.generation != self._generation
            self._current = None if stale else entry

        if stale or entry.cancel.is_set():
            self._cancelled += 1
            self._emit("file_cancelled", job)
            return

        self._emit("file_started", job)

        try:
            model, model_config = self._model_for(entry.settings)

        except Exception as e:
            self._failed += 1
            self._emit("file_failed", job, str(e))
            return

        try:

            for path in job.outputs.values():
                path.parent.mkdir(parents=True, exist_ok=True)

        except OSError as e:
            self._failed += 1
            self._emit("file_failed", job, f"couldn't create the output folder: {e}")
            return

        try:

            result = process_file(
                model,
                job.input_file,
                job.outputs,
                entry.settings.options(model_config),
                on_progress=lambda position, duration: self._emit(
                    "file_progress", job, position, duration
                ),
                cancel=entry.cancel,
            )

        except Cancelled:
            self._cancelled += 1
            self._emit("file_cancelled", job)

        except OutputError as e:
            self._failed += 1
            self._emit("file_failed", job, str(e))

        except Exception as e:
            # Not only the types we know: the real decoder raises its own
            # OSError subclass for a corrupt file, and anything else must
            # still leave the queue running.
            log.debug("details:", exc_info=True)
            self._failed += 1
            self._emit("file_failed", job, f"failed to process {job.input_file}: {e}")

        else:
            self._done += 1
            self._emit("file_finished", job, result)

    def _model_for(self, settings: Settings) -> tuple[Any, ModelConfig]:
        """The loaded model for `settings`, loading (or reloading) it if needed."""

        requested = settings.model_config
        key = (requested.name, requested.device, requested.compute_type)

        if key == self._failed_key:
            raise RuntimeError(self._failed_message)

        if key == self._model_key:
            assert self._model_config is not None
            return self._model, self._model_config

        # Free the old model first: two large models never fit in VRAM together.
        self._model = self._model_config = self._model_key = None
        gc.collect()

        self._emit("model_loading", requested)

        try:
            model, used = self._load_model(settings)

        except Exception as e:
            self._failed_key = key
            self._failed_message = str(e)
            self._emit("model_failed", requested, str(e))
            raise

        self._model, self._model_config, self._model_key = model, used, key
        self._emit("model_ready", used)

        return model, used

    def _finish_batch(self) -> None:

        counts = (self._done, self._failed, self._cancelled)
        self._done = self._failed = self._cancelled = 0

        # A model that failed to load may work next time (network back,
        # settings fixed), so a new batch tries again.
        self._failed_key = None

        self._emit("queue_finished", *counts)

    def _emit(self, name: str, *args: Any) -> None:

        try:
            getattr(self._events, name)(*args)

        except Exception:
            log.error("error in the %s handler", name, exc_info=True)


def _load_for_settings(settings: Settings) -> tuple[Any, ModelConfig]:
    """The default model loader (imported late: the machine learning libraries are slow)."""

    from .transcribe import load_for_run

    return load_for_run(
        settings.model_config, settings.multilingual, settings.task, settings.style
    )
