"""`JobRunner`: the background queue behind the desktop app, tested without any UI."""

import gc
import logging
import threading
import time
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest

from subtitlemaker.runner import Job, JobRunner, RunnerEvents
from subtitlemaker.settings import resolve_settings
from subtitlemaker.transcribe import ModelError
from tests.conftest import make_segment, make_word

WAIT = 5  # seconds; every wait in these tests is bounded so a bug fails instead of hanging


class Recorder(RunnerEvents):
    """Records every event as `(name, ...)`, and on which thread it arrived."""

    def __init__(self):
        self.events = []
        self.threads = set()
        self.raise_in = set()

    def _record(self, name, *args):
        self.threads.add(threading.current_thread().name)
        self.events.append((name, *args))

        if name in self.raise_in:
            raise RuntimeError(f"broken {name} handler")

    def model_loading(self, model_config):
        self._record("model_loading", model_config)

    def model_ready(self, model_config):
        self._record("model_ready", model_config)

    def model_failed(self, model_config, message):
        self._record("model_failed", message)

    def file_started(self, job):
        self._record("file_started", job.input_file.name)

    def file_progress(self, job, position, duration):
        self._record("file_progress", job.input_file.name, position, duration)

    def file_finished(self, job, result):
        self._record("file_finished", job.input_file.name, result)

    def file_failed(self, job, message):
        self._record("file_failed", job.input_file.name, message)

    def file_cancelled(self, job):
        self._record("file_cancelled", job.input_file.name)

    def queue_finished(self, done, failed, cancelled):
        self._record("queue_finished", done, failed, cancelled)

    def names(self):
        """The event names only, without progress (which varies in length)."""

        return [e[0] for e in self.events if e[0] != "file_progress"]

    def of(self, name):
        return [e for e in self.events if e[0] == name]


class GateModel:
    """A model whose transcription pauses between segments until released."""

    def __init__(self):
        self.calls = []
        self.first_segment_done = threading.Event()
        self.release = threading.Event()

    def transcribe(self, path, **kwargs):
        self.calls.append(Path(path).name)

        def segments():
            yield make_segment(" One.", 0.0, 4.0, [make_word(" One.", 1.0, 1.5)])
            self.first_segment_done.set()
            assert self.release.wait(WAIT), "the test never released the model"
            yield make_segment(" Two.", 5.0, 9.0, [make_word(" Two.", 6.0, 6.5)])

        return segments(), SimpleNamespace(language="en", language_probability=0.99)


@pytest.fixture(autouse=True)
def known_duration(monkeypatch):
    monkeypatch.setattr("subtitlemaker.pipeline.get_duration", lambda path: 10.0)


@pytest.fixture
def events():
    return Recorder()


@pytest.fixture
def runner(events, fake_model):
    """A runner using the default loader, with the fake model behind it."""

    runner = JobRunner(events)
    yield runner
    runner.shutdown()


@pytest.fixture
def settings():
    return resolve_settings(model={"name": "tiny"})


def make_job(tmp_path, name="talk.mp3", folder=None):
    media = tmp_path / name
    media.write_bytes(b"")  # never decoded: the model is fake
    out = (folder or tmp_path) / f"{Path(name).stem}.srt"

    return Job(media, {"srt": out})


def finish(runner):
    assert runner.join(WAIT), "the runner did not go idle"


# --- the happy path ---------------------------------------------------------------


def test_files_are_processed_in_order_and_written(runner, events, settings, tmp_path):
    jobs = [make_job(tmp_path, "a.mp3"), make_job(tmp_path, "b.mp3")]

    runner.submit_many([(job, settings) for job in jobs])
    finish(runner)

    # The first file is "started" while the model loads, so a window can show why it waits.
    assert events.names() == [
        "file_started",
        "model_loading",
        "model_ready",
        "file_finished",
        "file_started",
        "file_finished",
        "queue_finished",
    ]
    assert [e[1] for e in events.of("file_finished")] == ["a.mp3", "b.mp3"]
    assert events.of("queue_finished") == [("queue_finished", 2, 0, 0)]
    assert all(job.outputs["srt"].exists() for job in jobs)


def test_the_result_is_handed_over(runner, events, settings, tmp_path):
    runner.submit(make_job(tmp_path), settings)
    finish(runner)

    result = events.of("file_finished")[0][2]

    assert result.language == "en"
    assert len(result.subtitles) == 1


def test_progress_is_reported_for_the_file(runner, events, settings, tmp_path):
    runner.submit(make_job(tmp_path), settings)
    finish(runner)

    progress = [e[2:] for e in events.of("file_progress")]

    assert progress[0] == (0.0, 10.0)
    assert progress[-1] == (10.0, 10.0)


def test_events_arrive_on_the_worker_thread_not_the_callers(runner, events, settings, tmp_path):
    runner.submit(make_job(tmp_path), settings)
    finish(runner)

    assert events.threads == {"subtitlemaker-runner"}


def test_a_missing_output_folder_is_created(runner, events, settings, tmp_path):
    job = make_job(tmp_path, folder=tmp_path / "new" / "folder")

    runner.submit(job, settings)
    finish(runner)

    assert job.outputs["srt"].exists()


# --- the model is loaded once, and reloaded only when it must be ------------------


def test_one_model_serves_the_whole_queue(runner, settings, fake_model, tmp_path):
    for name in ("a.mp3", "b.mp3", "c.mp3"):
        runner.submit(make_job(tmp_path, name), settings)

    finish(runner)

    assert fake_model.loads == 1


def test_the_model_survives_between_batches(runner, settings, fake_model, tmp_path):
    runner.submit(make_job(tmp_path, "a.mp3"), settings)
    finish(runner)
    runner.submit(make_job(tmp_path, "b.mp3"), settings)
    finish(runner)

    assert fake_model.loads == 1


def test_changing_the_model_reloads_it(runner, events, fake_model, tmp_path):
    runner.submit(make_job(tmp_path, "a.mp3"), resolve_settings(model={"name": "tiny"}))
    runner.submit(make_job(tmp_path, "b.mp3"), resolve_settings(model={"name": "base"}))
    finish(runner)

    assert fake_model.loads == 2
    assert [e[1].name for e in events.of("model_loading")] == ["tiny", "base"]


def test_changing_only_the_compute_type_reloads_the_model(runner, fake_model, tmp_path):
    runner.submit(make_job(tmp_path, "a.mp3"), resolve_settings(model={"name": "tiny"}))
    runner.submit(
        make_job(tmp_path, "b.mp3"),
        resolve_settings(model={"name": "tiny", "compute_type": "float32"}),
    )
    finish(runner)

    assert fake_model.loads == 2


def test_changing_only_the_device_reloads_the_model(runner, fake_model, tmp_path):
    runner.submit(make_job(tmp_path, "a.mp3"), resolve_settings(model={"name": "tiny"}))
    runner.submit(
        make_job(tmp_path, "b.mp3"),
        resolve_settings(model={"name": "tiny", "device": "cpu"}),
    )
    finish(runner)

    assert fake_model.loads == 2


@pytest.mark.parametrize(
    "change",
    [
        {"style": {"max_line_length": 30}},
        {"formats": "vtt"},
        {"task": "translate"},
        {"language": "sv"},
        {"model": {"name": "tiny", "initial_prompt": "Hello, there."}},
        {"model": {"name": "tiny", "word_timestamps": False}},
    ],
)
def test_settings_that_do_not_select_the_model_do_not_reload_it(
    runner, fake_model, tmp_path, change
):
    runner.submit(make_job(tmp_path, "a.mp3"), resolve_settings(model={"name": "tiny"}))
    runner.submit(
        make_job(tmp_path, "b.mp3"), resolve_settings(**{"model": {"name": "tiny"}, **change})
    )
    finish(runner)

    assert fake_model.loads == 1


def test_the_old_model_is_freed_before_the_new_one_loads(events, settings, tmp_path):
    seen = {}
    previous = []

    class Model:
        def transcribe(self, path, **kwargs):
            return iter([make_segment(" Hi.", 0.0, 1.0)]), SimpleNamespace(
                language="en", language_probability=1.0
            )

    def load(s):
        if previous:
            gc.collect()
            seen["old_still_alive"] = previous[0]() is not None

        model = Model()
        previous.append(weakref.ref(model))

        return model, s.model_config

    runner = JobRunner(events, load_model=load)

    try:
        runner.submit(make_job(tmp_path, "a.mp3"), resolve_settings(model={"name": "tiny"}))
        runner.submit(make_job(tmp_path, "b.mp3"), resolve_settings(model={"name": "base"}))
        finish(runner)

    finally:
        runner.shutdown()

    assert seen == {"old_still_alive": False}  # two big models never need VRAM together


def test_each_job_runs_with_the_settings_it_was_submitted_with(
    runner, fake_model, settings, tmp_path
):
    runner.submit(make_job(tmp_path, "a.mp3"), resolve_settings(model={"name": "tiny"}))
    runner.submit(
        make_job(tmp_path, "b.mp3"), resolve_settings(model={"name": "tiny"}, task="translate")
    )
    finish(runner)

    assert [call["task"] for call in fake_model.calls] == ["transcribe", "translate"]


def test_a_batch_submitted_together_finishes_once(runner, events, settings, tmp_path, monkeypatch):
    # Dropping 50 files on the window must not report "queue finished" in the
    # middle, however fast the first file is done. Enqueueing is slowed down
    # so the worker really does finish file 1 before file 3 is queued; it has
    # to be running already (a fresh runner starts its thread after queueing).
    runner.submit(make_job(tmp_path, "warm-up.mp3"), settings)
    finish(runner)
    events.events.clear()

    real_put = runner._queue.put

    def slow_put(item):
        real_put(item)
        time.sleep(0.05)

    monkeypatch.setattr(runner._queue, "put", slow_put)

    jobs = [make_job(tmp_path, f"{name}.mp3") for name in "abc"]
    runner.submit_many([(job, settings) for job in jobs])
    finish(runner)

    assert events.of("queue_finished") == [("queue_finished", 3, 0, 0)]


def test_submitting_nothing_starts_nothing(runner, events):
    runner.submit_many([])

    assert runner.join(WAIT)
    assert events.events == []


# --- a bad file never stops the queue ---------------------------------------------


def test_a_failing_file_does_not_stop_the_queue(runner, events, settings, fake_model, tmp_path):
    fake_model.fail["bad.mp3"] = ValueError("boom")

    runner.submit_many([(make_job(tmp_path, n), settings) for n in ("a.mp3", "bad.mp3", "c.mp3")])
    finish(runner)

    assert [e[1] for e in events.of("file_finished")] == ["a.mp3", "c.mp3"]
    assert events.of("file_failed")[0][1] == "bad.mp3"
    assert "boom" in events.of("file_failed")[0][2]
    assert events.of("queue_finished") == [("queue_finished", 2, 1, 0)]


def test_a_corrupt_file_is_not_mistaken_for_a_write_error(
    runner, events, settings, fake_model, tmp_path
):
    # The real decoder raises an OSError subclass for a corrupt file.
    fake_model.fail["corrupt.mp3"] = OSError("Invalid data found when processing input")

    runner.submit(make_job(tmp_path, "corrupt.mp3"), settings)
    runner.submit(make_job(tmp_path, "ok.mp3"), settings)
    finish(runner)

    message = events.of("file_failed")[0][2]

    assert message.startswith("failed to process")
    assert "Invalid data" in message
    assert [e[1] for e in events.of("file_finished")] == ["ok.mp3"]


def test_an_output_that_cannot_be_written_fails_only_that_file(runner, events, settings, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a folder is needed")

    runner.submit(make_job(tmp_path, "a.mp3", folder=blocker / "sub"), settings)
    runner.submit(make_job(tmp_path, "b.mp3"), settings)
    finish(runner)

    assert "couldn't create the output folder" in events.of("file_failed")[0][2]
    assert [e[1] for e in events.of("file_finished")] == ["b.mp3"]


def test_a_failing_event_handler_does_not_kill_the_worker(
    runner, events, settings, tmp_path, caplog
):
    events.raise_in = {"file_started"}

    runner.submit(make_job(tmp_path, "a.mp3"), settings)
    runner.submit(make_job(tmp_path, "b.mp3"), settings)
    finish(runner)

    assert [e[1] for e in events.of("file_finished")] == ["a.mp3", "b.mp3"]
    assert "error in the file_started handler" in caplog.text


# --- a model that cannot be loaded ------------------------------------------------


def test_a_model_that_cannot_load_fails_the_files_that_need_it(events, settings, tmp_path):
    attempts = []
    both_queued = threading.Event()

    def load(s):
        attempts.append(1)
        # Fail only once both files are queued, so they belong to one batch.
        assert both_queued.wait(WAIT)
        raise ModelError("couldn't load model 'tiny': no network")

    runner = JobRunner(events, load_model=load)

    try:
        runner.submit(make_job(tmp_path, "a.mp3"), settings)
        runner.submit(make_job(tmp_path, "b.mp3"), settings)
        both_queued.set()
        finish(runner)

        assert len(events.of("model_failed")) == 1
        assert [e[2] for e in events.of("file_failed")] == [
            "couldn't load model 'tiny': no network"
        ] * 2
        assert len(attempts) == 1  # the second file did not retry a slow, failing load
        assert events.of("queue_finished") == [("queue_finished", 0, 2, 0)]

        # A later batch tries again: the network may be back.
        runner.submit(make_job(tmp_path, "c.mp3"), settings)
        finish(runner)

        assert len(attempts) == 2

    finally:
        runner.shutdown()


def test_a_different_model_after_a_failure_is_tried(events, tmp_path):
    def load(s):
        if s.model_config.name == "broken":
            raise ModelError("nope")

        return SimpleNamespace(
            transcribe=lambda path, **kw: (
                iter([make_segment(" Hi.", 0.0, 1.0)]),
                SimpleNamespace(language="en", language_probability=1.0),
            )
        ), s.model_config

    runner = JobRunner(events, load_model=load)

    try:
        runner.submit(make_job(tmp_path, "a.mp3"), resolve_settings(model={"name": "broken"}))
        runner.submit(make_job(tmp_path, "b.mp3"), resolve_settings(model={"name": "tiny"}))
        finish(runner)

    finally:
        runner.shutdown()

    # The queue may empty between the two submits (the first fails instantly),
    # so look at what happened to each file, not at how it was batched.
    assert [e[1] for e in events.of("file_failed")] == ["a.mp3"]
    assert [e[1] for e in events.of("file_finished")] == ["b.mp3"]


# --- cancelling -------------------------------------------------------------------


def gate_runner(events, gate):
    return JobRunner(events, load_model=lambda s: (gate, s.model_config))


def test_cancel_current_stops_that_file_and_the_queue_goes_on(events, settings, tmp_path):
    gate = GateModel()
    runner = gate_runner(events, gate)
    first, second = make_job(tmp_path, "a.mp3"), make_job(tmp_path, "b.mp3")

    try:
        runner.submit(first, settings)
        runner.submit(second, settings)

        assert gate.first_segment_done.wait(WAIT)

        runner.cancel_current()
        gate.release.set()
        finish(runner)

    finally:
        runner.shutdown()

    assert events.of("file_cancelled") == [("file_cancelled", "a.mp3")]
    assert [e[1] for e in events.of("file_finished")] == ["b.mp3"]
    assert not first.outputs["srt"].exists()  # a cancelled file writes nothing
    assert second.outputs["srt"].exists()
    assert events.of("queue_finished") == [("queue_finished", 1, 0, 1)]


def test_cancel_all_stops_the_current_file_and_drops_the_queue(events, settings, tmp_path):
    gate = GateModel()
    runner = gate_runner(events, gate)
    jobs = [make_job(tmp_path, name) for name in ("a.mp3", "b.mp3", "c.mp3")]

    try:
        for job in jobs:
            runner.submit(job, settings)

        assert gate.first_segment_done.wait(WAIT)

        runner.cancel_all()
        gate.release.set()
        finish(runner)

    finally:
        runner.shutdown()

    assert [e[1] for e in events.of("file_cancelled")] == ["a.mp3", "b.mp3", "c.mp3"]
    assert events.of("file_finished") == []
    assert gate.calls == ["a.mp3"]  # b and c never reached the model
    assert events.of("queue_finished") == [("queue_finished", 0, 0, 3)]
    assert not any(job.outputs["srt"].exists() for job in jobs)


def test_files_submitted_after_cancel_all_run_normally(events, settings, tmp_path):
    gate = GateModel()
    runner = gate_runner(events, gate)

    try:
        runner.submit(make_job(tmp_path, "a.mp3"), settings)
        assert gate.first_segment_done.wait(WAIT)

        runner.cancel_all()
        runner.submit(make_job(tmp_path, "b.mp3"), settings)
        gate.release.set()
        finish(runner)

    finally:
        runner.shutdown()

    assert [e[1] for e in events.of("file_cancelled")] == ["a.mp3"]
    assert [e[1] for e in events.of("file_finished")] == ["b.mp3"]


def test_cancelling_while_the_model_loads_cancels_the_file_after_the_load(
    events, settings, tmp_path
):
    loading = threading.Event()
    go = threading.Event()
    model = GateModel()
    model.release.set()

    def slow_load(s):
        loading.set()
        assert go.wait(WAIT)

        return model, s.model_config

    runner = JobRunner(events, load_model=slow_load)

    try:
        runner.submit(make_job(tmp_path, "a.mp3"), settings)
        assert loading.wait(WAIT)

        runner.cancel_current()  # a load cannot be interrupted, but the file is dropped
        go.set()
        finish(runner)

    finally:
        runner.shutdown()

    assert events.of("file_cancelled") == [("file_cancelled", "a.mp3")]
    assert model.calls == []


# --- shutting down ----------------------------------------------------------------


def test_shutdown_cancels_what_is_running_and_stops_the_thread(events, settings, tmp_path):
    gate = GateModel()
    runner = gate_runner(events, gate)

    runner.submit(make_job(tmp_path, "a.mp3"), settings)
    runner.submit(make_job(tmp_path, "b.mp3"), settings)
    assert gate.first_segment_done.wait(WAIT)

    gate.release.set()
    runner.shutdown()

    assert not any(t.name == "subtitlemaker-runner" for t in threading.enumerate())
    assert events.of("file_finished") == []
    assert [e[1] for e in events.of("file_cancelled")] == ["a.mp3", "b.mp3"]


def test_submitting_after_shutdown_is_an_error(events, settings, tmp_path):
    runner = JobRunner(events)
    runner.shutdown()
    runner.shutdown()  # harmless to repeat

    with pytest.raises(RuntimeError, match="shut down"):
        runner.submit(make_job(tmp_path), settings)


def test_join_times_out_while_work_is_blocked(events, settings, tmp_path):
    gate = GateModel()
    runner = gate_runner(events, gate)

    try:
        runner.submit(make_job(tmp_path), settings)
        assert gate.first_segment_done.wait(WAIT)

        assert runner.join(timeout=0.05) is False

    finally:
        gate.release.set()
        runner.shutdown()


def test_a_runner_with_nothing_queued_is_idle(events):
    runner = JobRunner(events)

    assert runner.join(timeout=WAIT) is True
    runner.shutdown()


# --- the log: what the command line prints, the runner logs too -------------------------------


def test_a_failed_file_is_logged_as_an_error(runner, settings, fake_model, tmp_path, caplog):
    fake_model.fail["bad.mp3"] = ValueError("boom")

    with caplog.at_level(logging.INFO, logger="subtitlemaker"):
        runner.submit_many(
            [(make_job(tmp_path, "bad.mp3"), settings), (make_job(tmp_path, "ok.mp3"), settings)]
        )
        finish(runner)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]

    assert len(errors) == 1  # once, not once per place it is reported
    assert "failed to process" in errors[0].getMessage() and "boom" in errors[0].getMessage()


def test_a_model_that_cannot_load_is_logged_for_each_file_that_needs_it(
    events, settings, tmp_path, caplog
):
    both_queued = threading.Event()

    def load(s):
        assert both_queued.wait(WAIT)
        raise ModelError("couldn't load model 'tiny': no network")

    runner = JobRunner(events, load_model=load)

    try:
        with caplog.at_level(logging.INFO, logger="subtitlemaker"):
            runner.submit_many(
                [(make_job(tmp_path, "a.mp3"), settings), (make_job(tmp_path, "b.mp3"), settings)]
            )
            both_queued.set()
            finish(runner)

    finally:
        runner.shutdown()

    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]

    assert messages == ["couldn't load model 'tiny': no network"] * 2


def test_an_output_that_cannot_be_written_is_logged(runner, settings, tmp_path, caplog):
    blocker = tmp_path / "blocker"
    blocker.write_text("a file where a folder is needed")

    with caplog.at_level(logging.INFO, logger="subtitlemaker"):
        runner.submit(make_job(tmp_path, "a.mp3", folder=blocker / "sub"), settings)
        finish(runner)

    assert any("couldn't create the output folder" in r.getMessage() for r in caplog.records)


def test_a_cancelled_file_is_logged(events, settings, tmp_path, caplog):
    gate = GateModel()
    runner = gate_runner(events, gate)

    try:
        with caplog.at_level(logging.INFO, logger="subtitlemaker"):
            runner.submit(make_job(tmp_path, "a.mp3"), settings)
            assert gate.first_segment_done.wait(WAIT)

            runner.cancel_current()
            gate.release.set()
            finish(runner)

    finally:
        runner.shutdown()

    assert "Cancelled a.mp3" in [r.getMessage() for r in caplog.records]


def test_a_file_dropped_before_it_started_is_logged_as_cancelled(
    events, settings, tmp_path, caplog
):
    gate = GateModel()
    runner = gate_runner(events, gate)

    try:
        with caplog.at_level(logging.INFO, logger="subtitlemaker"):
            runner.submit_many(
                [(make_job(tmp_path, n), settings) for n in ("a.mp3", "b.mp3", "c.mp3")]
            )
            assert gate.first_segment_done.wait(WAIT)

            runner.cancel_all()
            gate.release.set()
            finish(runner)

    finally:
        runner.shutdown()

    cancelled = [r.getMessage() for r in caplog.records if r.getMessage().startswith("Cancelled")]

    assert cancelled == ["Cancelled a.mp3", "Cancelled b.mp3", "Cancelled c.mp3"]


@pytest.mark.parametrize(
    ("fail", "expected"),
    [
        ((), "Finished: 2 done."),
        (("b.mp3",), "Finished: 1 done, 1 failed."),
    ],
)
def test_the_end_of_a_queue_is_summed_up_in_the_log(
    runner, settings, fake_model, tmp_path, caplog, fail, expected
):
    for name in fail:
        fake_model.fail[name] = ValueError("boom")

    with caplog.at_level(logging.INFO, logger="subtitlemaker"):
        runner.submit_many([(make_job(tmp_path, n), settings) for n in ("a.mp3", "b.mp3")])
        finish(runner)

    assert expected in [r.getMessage() for r in caplog.records]


def test_cancelled_files_are_part_of_the_summary(events, settings, tmp_path, caplog):
    gate = GateModel()
    runner = gate_runner(events, gate)

    try:
        with caplog.at_level(logging.INFO, logger="subtitlemaker"):
            runner.submit_many([(make_job(tmp_path, n), settings) for n in ("a.mp3", "b.mp3")])
            assert gate.first_segment_done.wait(WAIT)

            runner.cancel_all()
            gate.release.set()
            finish(runner)

    finally:
        runner.shutdown()

    assert "Finished: 0 done, 2 cancelled." in [r.getMessage() for r in caplog.records]
