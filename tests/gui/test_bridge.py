"""`RunnerBridge`: runner events arrive as Qt signals, in the Qt thread."""

import threading

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QObject, QThread  # noqa: E402

from subtitlemaker.gui.bridge import RunnerBridge  # noqa: E402
from subtitlemaker.pipeline import FileResult  # noqa: E402
from subtitlemaker.runner import Job  # noqa: E402
from subtitlemaker.settings import resolve_settings  # noqa: E402

WAIT = 5000  # ms


class Receiver(QObject):
    """A slot owner living in the Qt thread, like a widget would be."""

    def __init__(self):
        super().__init__()
        self.events = []
        self.threads = []

    def _note(self, *event):
        self.events.append(event)
        self.threads.append(QThread.currentThread())

    def on_started(self, job):
        self._note("started", job.input_file.name)

    def on_progress(self, job, position, duration):
        self._note("progress", position, duration)

    def on_finished(self, job, result):
        self._note("finished", job.input_file.name, result)

    def on_failed(self, job, message):
        self._note("failed", job.input_file.name, message)

    def on_cancelled(self, job):
        self._note("cancelled", job.input_file.name)

    def on_model_ready(self, model_config):
        self._note("model_ready", model_config.name)

    def on_queue_finished(self, done, failed, cancelled):
        self._note("queue_finished", done, failed, cancelled)


@pytest.fixture(autouse=True)
def known_duration(monkeypatch):
    monkeypatch.setattr("subtitlemaker.pipeline.get_duration", lambda path: 10.0)


@pytest.fixture
def bridge(qtbot, fake_model):
    bridge = RunnerBridge()
    yield bridge
    bridge.shutdown()


@pytest.fixture
def receiver(bridge):
    receiver = Receiver()
    bridge.file_started.connect(receiver.on_started)
    bridge.file_progress.connect(receiver.on_progress)
    bridge.file_finished.connect(receiver.on_finished)
    bridge.file_failed.connect(receiver.on_failed)
    bridge.file_cancelled.connect(receiver.on_cancelled)
    bridge.model_ready.connect(receiver.on_model_ready)
    bridge.queue_finished.connect(receiver.on_queue_finished)

    return receiver


def make_job(tmp_path, name="talk.mp3"):
    media = tmp_path / name
    media.write_bytes(b"")  # never decoded: the model is fake

    return Job(media, {"srt": tmp_path / f"{media.stem}.srt"})


@pytest.fixture
def settings():
    return resolve_settings(model={"name": "tiny"})


def test_events_arrive_as_signals_in_order(qtbot, bridge, receiver, settings, tmp_path):
    job = make_job(tmp_path)

    with qtbot.waitSignal(bridge.queue_finished, timeout=WAIT):
        bridge.submit(job, settings)

    kinds = [event[0] for event in receiver.events]

    assert kinds[0] == "started"
    assert "model_ready" in kinds
    assert kinds[-2:] == ["finished", "queue_finished"]
    assert receiver.events[-1] == ("queue_finished", 1, 0, 0)
    assert job.outputs["srt"].exists()


def test_slots_run_in_the_qt_thread_not_the_worker_thread(
    qtbot, bridge, receiver, settings, tmp_path
):
    with qtbot.waitSignal(bridge.queue_finished, timeout=WAIT):
        bridge.submit(make_job(tmp_path), settings)

    assert receiver.threads, "no event reached the receiver"
    assert set(receiver.threads) == {receiver.thread()}
    assert receiver.thread() == QThread.currentThread()
    assert threading.current_thread() is threading.main_thread()


def test_payloads_keep_their_python_types(qtbot, bridge, receiver, settings, tmp_path):
    job = make_job(tmp_path)

    with qtbot.waitSignal(bridge.queue_finished, timeout=WAIT):
        bridge.submit(job, settings)

    finished = next(e for e in receiver.events if e[0] == "finished")

    assert isinstance(finished[2], FileResult)
    assert finished[2].input_file == job.input_file
    assert len(finished[2].subtitles) == 1

    progress = [e[1:] for e in receiver.events if e[0] == "progress"]

    assert progress[0] == (0.0, 10.0)
    assert all(isinstance(value, float) for pair in progress for value in pair)


def test_a_failing_file_is_a_signal_not_a_crash(
    qtbot, bridge, receiver, settings, fake_model, tmp_path
):
    fake_model.fail["bad.mp3"] = ValueError("boom")

    with qtbot.waitSignal(bridge.queue_finished, timeout=WAIT):
        bridge.submit_many(
            [(make_job(tmp_path, "bad.mp3"), settings), (make_job(tmp_path, "ok.mp3"), settings)]
        )

    failed = next(e for e in receiver.events if e[0] == "failed")

    assert failed[1] == "bad.mp3"
    assert "boom" in failed[2]
    assert receiver.events[-1] == ("queue_finished", 1, 1, 0)


def test_cancelling_reaches_the_window_as_a_signal(qtbot, receiver, settings, tmp_path):
    gate = threading.Event()
    started = threading.Event()

    class Model:
        def transcribe(self, path, **kwargs):
            from types import SimpleNamespace

            from tests.conftest import make_segment

            def segments():
                yield make_segment(" One.", 0.0, 4.0)
                started.set()
                assert gate.wait(5)
                yield make_segment(" Two.", 5.0, 9.0)

            return segments(), SimpleNamespace(language="en", language_probability=1.0)

    bridge = RunnerBridge(load_model=lambda s: (Model(), s.model_config))
    bridge.file_cancelled.connect(receiver.on_cancelled)
    bridge.queue_finished.connect(receiver.on_queue_finished)

    try:
        bridge.submit(make_job(tmp_path), settings)
        assert started.wait(5)

        with qtbot.waitSignal(bridge.queue_finished, timeout=WAIT):
            bridge.cancel_current()
            gate.set()

    finally:
        bridge.shutdown()

    assert ("cancelled", "talk.mp3") in receiver.events
    assert receiver.events[-1] == ("queue_finished", 0, 0, 1)


def test_shutdown_stops_the_worker_thread(bridge, settings, tmp_path):
    bridge.submit(make_job(tmp_path), settings)
    bridge.shutdown()

    assert not any(t.name == "subtitlemaker-runner" for t in threading.enumerate())


def test_a_bridge_that_is_deleted_does_not_leave_its_worker_behind(
    qtbot, fake_model, settings, tmp_path
):
    import shiboken6

    bridge = RunnerBridge()
    bridge.submit(make_job(tmp_path), settings)
    qtbot.waitUntil(
        lambda: any(t.name == "subtitlemaker-runner" for t in threading.enumerate()), timeout=WAIT
    )

    shiboken6.delete(bridge)  # as when a window is destroyed without its close event

    qtbot.waitUntil(
        lambda: not any(t.name == "subtitlemaker-runner" for t in threading.enumerate()),
        timeout=WAIT,
    )
