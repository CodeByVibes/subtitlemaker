"""The file queue screen, driven like a user would: through its buttons and a real runner."""

import threading
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl  # noqa: E402
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402

from subtitlemaker.config import ConfigError  # noqa: E402
from subtitlemaker.gui.bridge import RunnerBridge  # noqa: E402
from subtitlemaker.gui.queue_model import (  # noqa: E402
    COL_DURATION,
    COL_STATUS,
    Status,
)
from subtitlemaker.settings import resolve_settings  # noqa: E402
from tests.conftest import make_segment  # noqa: E402
from tests.gui.helpers import media  # noqa: E402

WAIT = 5000  # ms


@pytest.fixture(autouse=True)
def known_duration(monkeypatch):
    monkeypatch.setattr("subtitlemaker.pipeline.get_duration", lambda path: 10.0)
    monkeypatch.setattr("subtitlemaker.gui.probe.get_duration", lambda path: 10.0)


@pytest.fixture
def ui(qtbot, fake_model, make_window, warnings):
    """The main window on a real runner with a fake model."""

    window = make_window()

    return SimpleNamespace(
        window=window,
        panel=window.panel,
        model=window.panel.model,
        view=window.panel.view,
        warnings=warnings,
        fake_model=fake_model,
        qtbot=qtbot,
    )


def statuses(ui):
    return [item.status for item in ui.model.items()]


def wait_until_finished(ui, text="done"):
    """Wait for the runner to report the end of the queue in the status line."""

    ui.qtbot.waitUntil(
        lambda: not ui.panel.is_busy() and text in ui.panel.detail.text(), timeout=WAIT
    )


# --- adding files -----------------------------------------------------------------------------


def test_files_are_added_with_the_file_dialog(ui, tmp_path, monkeypatch):
    paths = media(tmp_path, "a.mp3", "b.mp3")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        staticmethod(lambda *a, **k: ([str(p) for p in paths], "")),
    )

    ui.panel.add_files_button.click()

    assert [i.path for i in ui.model.items()] == paths
    assert ui.panel.detail.text() == "Added 2 files."


def test_cancelling_the_file_dialog_adds_nothing(ui, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([], "")))

    ui.panel.add_files_button.click()

    assert ui.model.count() == 0


def test_a_folder_is_added_with_the_folder_dialog(ui, tmp_path, monkeypatch):
    media(tmp_path / "talks", "a.mp3")
    media(tmp_path / "talks" / "deeper", "b.mp3")
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path / "talks"))
    )

    ui.panel.add_folder_button.click()
    assert ui.model.count() == 1  # sub folders only when asked

    ui.panel.recursive_check.setChecked(True)
    ui.panel.add_folder_button.click()
    assert ui.model.count() == 2
    assert "1 already in the list" in ui.panel.detail.text()


def test_cancelling_the_folder_dialog_adds_nothing(ui, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: ""))

    ui.panel.add_folder_button.click()

    assert ui.model.count() == 0


def test_an_empty_folder_says_so(ui, tmp_path):
    (tmp_path / "empty").mkdir()

    ui.panel.add_paths([tmp_path / "empty"])

    assert ui.panel.detail.text() == "No media files found."


def test_inputs_that_do_not_exist_are_reported_once_in_one_message(ui, tmp_path):
    (good,) = media(tmp_path, "a.mp3")
    missing = [tmp_path / f"gone{i}.mp3" for i in range(8)]

    ui.panel.add_paths([good, *missing])

    assert ui.model.count() == 1
    assert len(ui.warnings) == 1
    title, text = ui.warnings[0]
    assert title == "Some files could not be added"
    assert text.count("does not exist") == 5  # the first five ...
    assert "and 3 more" in text  # ... then a count


def _drop(view, mime):
    event = QDropEvent(
        QPointF(5, 5),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    view.dropEvent(event)

    return event


def test_files_dropped_from_the_file_manager_are_added(ui, tmp_path):
    paths = media(tmp_path, "a.mp3", "b.mp4")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])

    event = _drop(ui.view, mime)

    assert event.isAccepted()
    assert [i.path for i in ui.model.items()] == paths


def test_a_dropped_folder_is_scanned(ui, tmp_path):
    media(tmp_path / "talks", "a.mp3", "notes.txt")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "talks"))])

    _drop(ui.view, mime)

    assert [i.path.name for i in ui.model.items()] == ["a.mp3"]


def test_a_drop_without_files_is_refused(ui):
    mime = QMimeData()
    mime.setText("just some text")

    event = _drop(ui.view, mime)

    assert not event.isAccepted()
    assert ui.model.count() == 0


def test_web_links_are_not_files(ui):
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/talk.mp3")])

    event = _drop(ui.view, mime)

    assert not event.isAccepted()
    assert ui.model.count() == 0


@pytest.mark.filterwarnings("ignore::DeprecationWarning")  # PySide6 deprecates this constructor
def test_the_view_only_welcomes_drags_that_carry_files(ui, tmp_path):
    def enter(mime):
        event = QDragEnterEvent(
            QPoint(5, 5),
            Qt.DropAction.CopyAction,
            mime,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        ui.view.dragEnterEvent(event)

        return event.isAccepted()

    files = QMimeData()
    files.setUrls([QUrl.fromLocalFile(str(tmp_path))])
    text = QMimeData()
    text.setText("hello")

    assert enter(files) is True
    assert enter(text) is False


def test_lengths_are_filled_in_by_the_background_probe(ui, tmp_path, monkeypatch):
    monkeypatch.setattr("subtitlemaker.gui.probe.get_duration", lambda path: 125.0)

    ui.panel.add_paths(media(tmp_path, "a.mp3"))

    ui.qtbot.waitUntil(
        lambda: ui.model.index(0, COL_DURATION).data() == "2:05",
        timeout=WAIT,
    )


def test_an_unreadable_file_just_has_no_length(ui, tmp_path, monkeypatch):
    def broken(path):
        raise OSError("Invalid data")

    monkeypatch.setattr("subtitlemaker.gui.probe.get_duration", broken)
    ui.panel.add_paths(media(tmp_path, "a.mp3"))

    ui.window.prober.shutdown()  # wait for the probe to finish
    ui.qtbot.wait(50)

    assert ui.model.index(0, COL_DURATION).data() == ""
    assert statuses(ui) == [Status.QUEUED]  # the real run reports the problem, not the probe


# --- running ----------------------------------------------------------------------------------


def test_start_transcribes_every_file_and_writes_the_subtitles(ui, tmp_path):
    paths = media(tmp_path, "a.mp3", "b.mp3")
    ui.panel.add_paths(paths)

    ui.panel.start_button.click()
    wait_until_finished(ui)

    assert statuses(ui) == [Status.DONE, Status.DONE]
    assert (tmp_path / "a.srt").exists() and (tmp_path / "b.srt").exists()
    assert ui.panel.detail.text() == "2 done."
    assert ui.warnings == []


def test_start_does_nothing_without_files(ui):
    assert not ui.panel.start_button.isEnabled()

    ui.panel.start()

    assert ui.fake_model.calls == []


def test_a_failing_file_is_marked_and_the_rest_go_on(ui, tmp_path):
    ui.fake_model.fail["bad.mp3"] = ValueError("boom")
    ui.panel.add_paths(media(tmp_path, "a.mp3", "bad.mp3", "c.mp3"))

    ui.panel.start_button.click()
    wait_until_finished(ui, "failed")

    assert statuses(ui) == [Status.DONE, Status.FAILED, Status.DONE]
    assert "boom" in ui.model.index(1, COL_STATUS).data(Qt.ItemDataRole.ToolTipRole)
    assert ui.panel.detail.text().startswith("2 done, 1 failed. ")
    assert "boom" in ui.panel.detail.text()


def test_the_summary_says_why_files_failed(ui, tmp_path):
    ui.fake_model.fail["bad.mp3"] = ValueError("boom")
    ui.fake_model.fail["worse.mp3"] = ValueError("kaboom")
    ui.panel.add_paths(media(tmp_path, "ok.mp3", "bad.mp3", "worse.mp3"))

    ui.panel.start_button.click()
    wait_until_finished(ui, "failed")

    text = ui.panel.detail.text()

    assert text.startswith("1 done, 2 failed.")
    assert "boom" in text and "kaboom" not in text  # the first reason, not a wall of text
    assert ui.panel.detail.toolTip() == text


def test_the_reason_for_a_failed_model_load_reaches_the_summary(
    make_window, warnings, qtbot, tmp_path
):
    from subtitlemaker.transcribe import ModelError

    def cannot_load(settings):
        raise ModelError("couldn't load model 'tiny': no network")

    window = make_window(bridge=RunnerBridge(load_model=cannot_load))
    window.panel.add_paths(media(tmp_path, "a.mp3", "b.mp3"))

    window.panel.start_button.click()
    qtbot.waitUntil(lambda: "failed" in window.panel.detail.text(), timeout=WAIT)

    assert "0 done, 2 failed. couldn't load model 'tiny': no network" == window.panel.detail.text()


def test_an_old_failure_is_not_repeated_in_the_next_summary(ui, tmp_path):
    ui.fake_model.fail["bad.mp3"] = ValueError("boom")
    ui.panel.add_paths(media(tmp_path, "bad.mp3"))
    ui.panel.start_button.click()
    wait_until_finished(ui, "failed")

    ui.panel.add_paths(media(tmp_path, "ok.mp3"))
    ui.panel.start_button.click()
    ui.qtbot.waitUntil(lambda: ui.panel.detail.text() == "1 done.", timeout=WAIT)


def test_a_warning_from_the_run_marks_the_row(ui, tmp_path):
    # Twelve long segments without any punctuation: Whisper's "lost its punctuation" case.
    ui.fake_model.segments = [
        make_segment(
            " mikey what's going on what's going on in there are you okay now i get it",
            i * 5.0,
            i * 5.0 + 4.0,
        )
        for i in range(12)
    ]
    ui.panel.add_paths(media(tmp_path, "a.mp3"))

    ui.panel.start_button.click()
    wait_until_finished(ui)

    assert ui.model.index(0, COL_STATUS).data() == "Done (warning)"
    assert "almost no punctuation" in ui.model.index(0, COL_STATUS).data(
        Qt.ItemDataRole.ToolTipRole
    )


@pytest.fixture
def gated(make_window):
    """A window whose model stops after its first segment until released."""

    gate = threading.Event()
    reached = threading.Event()

    class Slow:
        def transcribe(self, path, **kwargs):
            def segments():
                yield make_segment(" One.", 0.0, 4.0)
                reached.set()
                assert gate.wait(5)
                yield make_segment(" Two.", 5.0, 9.0)

            return segments(), SimpleNamespace(language="en", language_probability=1.0)

    bridge = RunnerBridge(load_model=lambda s: (Slow(), s.model_config))
    window = make_window(bridge=bridge, settings_provider=lambda: resolve_settings())

    yield SimpleNamespace(window=window, panel=window.panel, gate=gate, reached=reached)

    gate.set()  # never leave a worker waiting on a test that stopped early


def test_progress_and_speed_show_while_a_file_runs(ui, gated, tmp_path):
    panel = gated.panel
    panel.add_paths(media(tmp_path, "a.mp3"))
    panel.start_button.click()

    assert gated.reached.wait(5)
    ui.qtbot.waitUntil(lambda: panel.model.item(0).position >= 4.0, timeout=WAIT)

    assert panel.model.item(0).status is Status.RUNNING
    assert "00:00:04 / 00:00:10" in panel.detail.text()
    assert panel.model.index(0, 3).data(Qt.ItemDataRole.DisplayRole) == "40%"
    assert panel.view.viewport().grab().width() > 0  # the progress bar delegate paints

    gated.gate.set()
    ui.qtbot.waitUntil(lambda: "1 done" in panel.detail.text(), timeout=WAIT)


def test_files_added_while_running_wait_for_the_next_start(ui, tmp_path):
    ui.panel.add_paths(media(tmp_path, "a.mp3"))
    ui.panel.start_button.click()
    ui.panel.add_paths(media(tmp_path, "later.mp3"))

    wait_until_finished(ui)

    assert statuses(ui) == [Status.DONE, Status.QUEUED]
    assert ui.panel.start_button.isEnabled()

    ui.panel.start_button.click()
    ui.qtbot.waitUntil(lambda: statuses(ui) == [Status.DONE, Status.DONE], timeout=WAIT)


def test_a_finished_file_can_be_run_again(ui, tmp_path):
    (a,) = media(tmp_path, "a.mp3")
    ui.panel.add_paths([a])
    ui.panel.start_button.click()
    wait_until_finished(ui)
    a.with_suffix(".srt").unlink()

    ui.view.selectRow(0)
    assert ui.panel.requeue_button.isEnabled()
    ui.panel.requeue_button.click()
    assert statuses(ui) == [Status.QUEUED]

    ui.panel.detail.setText("")
    ui.panel.start_button.click()
    wait_until_finished(ui)

    assert a.with_suffix(".srt").exists()


# --- cancelling -------------------------------------------------------------------------------


def test_cancel_stops_the_running_file_and_the_waiting_ones(ui, gated, tmp_path):
    paths = media(tmp_path, "a.mp3", "b.mp3", "c.mp3")
    gated.panel.add_paths(paths)
    gated.panel.start_button.click()
    assert gated.reached.wait(5)

    assert gated.panel.cancel_button.isEnabled()
    gated.panel.cancel_button.click()
    gated.gate.set()

    ui.qtbot.waitUntil(lambda: "cancelled" in gated.panel.detail.text(), timeout=WAIT)

    assert [i.status for i in gated.panel.model.items()] == [Status.CANCELLED] * 3
    assert gated.panel.detail.text() == "0 done, 3 cancelled."
    assert not any(p.with_suffix(".srt").exists() for p in paths)
    assert not gated.panel.cancel_button.isEnabled()
    assert gated.panel.start_button.isEnabled()  # Cancel, then Start, picks them up again


def test_start_after_cancel_runs_the_cancelled_files(ui, gated, tmp_path):
    paths = media(tmp_path, "a.mp3", "b.mp3")
    gated.panel.add_paths(paths)
    gated.panel.start_button.click()
    assert gated.reached.wait(5)
    gated.panel.cancel_button.click()
    gated.gate.set()
    ui.qtbot.waitUntil(lambda: "cancelled" in gated.panel.detail.text(), timeout=WAIT)
    assert [i.status for i in gated.panel.model.items()] == [Status.CANCELLED] * 2

    gated.panel.detail.setText("")
    gated.panel.start_button.click()
    ui.qtbot.waitUntil(lambda: "2 done" in gated.panel.detail.text(), timeout=WAIT)

    assert [i.status for i in gated.panel.model.items()] == [Status.DONE] * 2
    assert all(p.with_suffix(".srt").exists() for p in paths)


def test_start_leaves_finished_and_failed_files_alone(ui, tmp_path):
    ui.fake_model.fail["bad.mp3"] = ValueError("boom")
    ui.panel.add_paths(media(tmp_path, "ok.mp3", "bad.mp3"))
    ui.panel.start_button.click()
    wait_until_finished(ui, "failed")
    calls_before = len(ui.fake_model.calls)

    assert not ui.panel.start_button.isEnabled()  # nothing left to start
    ui.panel.start()

    assert len(ui.fake_model.calls) == calls_before  # neither file ran again


def test_files_the_runner_has_cannot_be_edited_while_it_works(ui, gated, tmp_path):
    gated.panel.add_paths(media(tmp_path, "a.mp3", "b.mp3"))
    gated.panel.start_button.click()
    assert gated.reached.wait(5)

    gated.panel.view.selectAll()

    assert not gated.panel.remove_button.isEnabled()
    assert not gated.panel.clear_button.isEnabled()
    assert gated.panel.model.remove_rows([0, 1]) == 0

    gated.panel.cancel_button.click()
    gated.gate.set()
    ui.qtbot.waitUntil(lambda: not gated.panel.is_busy(), timeout=WAIT)


# --- where the subtitles go -------------------------------------------------------------------


def test_subtitles_can_go_to_another_folder(ui, tmp_path):
    (a,) = media(tmp_path / "in", "a.mp3")
    out = tmp_path / "out" / "nested"
    ui.panel.add_paths([a])
    ui.panel.folder_edit.setText(str(out))
    ui.panel.folder_radio.setChecked(True)

    assert ui.panel.output_dir() == out

    ui.panel.start_button.click()
    wait_until_finished(ui)

    assert (out / "a.srt").exists()  # the folder was created
    assert not (tmp_path / "in" / "a.srt").exists()


def test_the_browse_button_picks_the_folder_and_switches_to_it(ui, tmp_path, monkeypatch):
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(tmp_path / "chosen"))
    )

    ui.panel.folder_button.click()

    assert ui.panel.folder_radio.isChecked()
    assert ui.panel.output_dir() == tmp_path / "chosen"


def test_the_folder_field_is_only_live_when_that_choice_is_on(ui):
    assert ui.panel.next_to_radio.isChecked()
    assert not ui.panel.folder_edit.isEnabled()
    assert ui.panel.folder_button.isEnabled()  # Browse switches to the folder choice itself
    assert ui.panel.output_dir() is None

    ui.panel.folder_radio.setChecked(True)

    assert ui.panel.folder_edit.isEnabled()


def test_choosing_a_folder_but_not_picking_one_stops_before_starting(ui, tmp_path):
    ui.panel.add_paths(media(tmp_path, "a.mp3"))
    ui.panel.folder_radio.setChecked(True)

    ui.panel.start_button.click()

    assert ui.warnings == [("Can't start", "Choose the folder for the subtitles first.")]
    assert statuses(ui) == [Status.QUEUED]
    assert ui.fake_model.calls == []


def test_two_files_that_would_write_the_same_subtitles_are_refused(ui, tmp_path):
    ui.panel.add_paths(media(tmp_path / "x", "talk.mp3") + media(tmp_path / "y", "talk.mp3"))
    ui.panel.folder_edit.setText(str(tmp_path / "out"))
    ui.panel.folder_radio.setChecked(True)

    ui.panel.start_button.click()

    assert len(ui.warnings) == 1
    assert "would both write" in ui.warnings[0][1]
    assert statuses(ui) == [Status.QUEUED, Status.QUEUED]  # nothing was started
    assert ui.fake_model.calls == []


def test_subtitles_never_overwrite_their_own_input(ui, tmp_path):
    # An .srt can be added by hand; its subtitles would land on itself.
    (srt,) = media(tmp_path, "talk.srt")
    ui.panel.add_paths([srt])

    ui.panel.start_button.click()

    assert len(ui.warnings) == 1
    assert "would be overwritten" in ui.warnings[0][1]
    assert statuses(ui) == [Status.QUEUED]
    assert ui.fake_model.calls == []


def test_files_with_subtitles_already_are_skipped_when_asked(ui, tmp_path):
    a, b = media(tmp_path, "a.mp3", "b.mp3")
    a.with_suffix(".srt").write_text("existing")
    ui.panel.add_paths([a, b])
    ui.panel.skip_existing_check.setChecked(True)

    ui.panel.start_button.click()
    wait_until_finished(ui)

    assert statuses(ui) == [Status.SKIPPED, Status.DONE]
    assert a.with_suffix(".srt").read_text() == "existing"  # untouched
    assert [c["name"] for c in ui.fake_model.calls] == ["b.mp3"]


def test_without_that_option_existing_subtitles_are_overwritten(ui, tmp_path):
    (a,) = media(tmp_path, "a.mp3")
    a.with_suffix(".srt").write_text("old")
    ui.panel.add_paths([a])

    ui.panel.start_button.click()
    wait_until_finished(ui)

    assert a.with_suffix(".srt").read_text() != "old"


def test_when_everything_is_skipped_nothing_runs_and_it_says_so(ui, tmp_path):
    a, b = media(tmp_path, "a.mp3", "b.mp3")
    for path in (a, b):
        path.with_suffix(".srt").write_text("x")
    ui.panel.add_paths([a, b])
    ui.panel.skip_existing_check.setChecked(True)

    ui.panel.start_button.click()

    assert statuses(ui) == [Status.SKIPPED, Status.SKIPPED]
    assert ui.panel.detail.text() == "Nothing to do: all 2 already have subtitles."
    assert ui.fake_model.calls == []
    assert not ui.panel.is_busy()


def test_a_settings_problem_is_shown_instead_of_starting(
    make_window, warnings, fake_model, tmp_path
):
    def broken():
        raise ConfigError("/home/me/.config/subtitlemaker/config.toml: invalid TOML")

    window = make_window(settings_provider=broken)
    window.panel.add_paths(media(tmp_path, "a.mp3"))

    window.panel.start_button.click()

    assert warnings == [("Settings", "/home/me/.config/subtitlemaker/config.toml: invalid TOML")]
    assert [i.status for i in window.panel.model.items()] == [Status.QUEUED]
    assert fake_model.calls == []


# --- the list buttons -------------------------------------------------------------------------


def test_the_buttons_follow_the_selection(ui, tmp_path):
    panel = ui.panel

    assert not any(
        b.isEnabled()
        for b in (
            panel.start_button,
            panel.cancel_button,
            panel.remove_button,
            panel.clear_button,
            panel.up_button,
            panel.down_button,
            panel.requeue_button,
        )
    )

    panel.add_paths(media(tmp_path, "a.mp3", "b.mp3", "c.mp3"))

    assert panel.start_button.isEnabled() and panel.clear_button.isEnabled()
    assert not panel.remove_button.isEnabled()  # nothing selected

    ui.view.selectRow(0)
    assert panel.remove_button.isEnabled()
    assert not panel.up_button.isEnabled() and panel.down_button.isEnabled()

    ui.view.selectRow(2)
    assert panel.up_button.isEnabled() and not panel.down_button.isEnabled()

    ui.view.selectAll()
    assert not panel.up_button.isEnabled() and not panel.down_button.isEnabled()  # one at a time


def test_remove_takes_out_the_selected_files(ui, tmp_path):
    ui.panel.add_paths(media(tmp_path, "a.mp3", "b.mp3", "c.mp3"))
    ui.view.selectRow(1)

    ui.panel.remove_button.click()

    assert [i.path.name for i in ui.model.items()] == ["a.mp3", "c.mp3"]


def test_clear_empties_the_list(ui, tmp_path):
    ui.panel.add_paths(media(tmp_path, "a.mp3", "b.mp3"))

    ui.panel.clear_button.click()

    assert ui.model.count() == 0
    assert not ui.panel.start_button.isEnabled()


def test_move_up_and_down_keep_the_file_selected(ui, tmp_path):
    ui.panel.add_paths(media(tmp_path, "a.mp3", "b.mp3", "c.mp3"))
    ui.view.selectRow(0)

    ui.panel.down_button.click()
    ui.panel.down_button.click()

    assert [i.path.name for i in ui.model.items()] == ["b.mp3", "c.mp3", "a.mp3"]
    assert ui.view.selected_rows() == [2]

    ui.panel.up_button.click()

    assert [i.path.name for i in ui.model.items()] == ["b.mp3", "a.mp3", "c.mp3"]
    assert ui.view.selected_rows() == [1]


def test_files_run_in_the_order_of_the_list(ui, tmp_path):
    ui.panel.add_paths(media(tmp_path, "a.mp3", "b.mp3", "c.mp3"))
    ui.view.selectRow(2)
    ui.panel.up_button.click()
    ui.panel.up_button.click()  # c first

    ui.panel.start_button.click()
    wait_until_finished(ui)

    assert [c["name"] for c in ui.fake_model.calls] == ["c.mp3", "a.mp3", "b.mp3"]


# --- the context menu actions -----------------------------------------------------------------


def test_the_output_folder_can_be_opened(ui, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True)
    )
    (a,) = media(tmp_path / "in", "a.mp3")
    ui.panel.add_paths([a])
    ui.panel.folder_edit.setText(str(tmp_path / "out"))
    ui.panel.folder_radio.setChecked(True)
    ui.panel.start_button.click()
    wait_until_finished(ui)

    assert ui.panel.open_output_folder(0) is True

    assert [u.toLocalFile() for u in opened] == [str(tmp_path / "out")]


def test_a_file_without_output_has_no_folder_to_open(ui, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(
        QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url) or True)
    )
    ui.panel.add_paths(media(tmp_path, "a.mp3"))

    assert ui.panel.open_output_folder(0) is False
    assert opened == []


# --- closing the window -----------------------------------------------------------------------


def test_closing_an_idle_window_stops_the_worker(ui, tmp_path):
    ui.panel.add_paths(media(tmp_path, "a.mp3"))
    ui.panel.start_button.click()
    wait_until_finished(ui)

    ui.window.close()

    assert not ui.window.isVisible()
    assert not any(t.name == "subtitlemaker-runner" for t in threading.enumerate())


def test_closing_while_working_asks_first(ui, gated, tmp_path, monkeypatch):
    asked = []
    answers = iter([QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda parent, title, text, *a, **k: asked.append(title) or next(answers)),
    )
    gated.window.show()
    gated.panel.add_paths(media(tmp_path, "a.mp3", "b.mp3"))
    gated.panel.start_button.click()
    assert gated.reached.wait(5)

    gated.window.close()  # the answer is "No"
    assert gated.window.isVisible()
    assert gated.panel.is_busy()

    gated.gate.set()  # let the file reach its next segment, where the cancel takes effect
    gated.window.close()  # the answer is "Yes"

    assert asked == ["Quit SubtitleMaker?", "Quit SubtitleMaker?"]
    assert not gated.window.isVisible()
    assert not any(t.name == "subtitlemaker-runner" for t in threading.enumerate())
    assert not any(p.with_suffix(".srt").exists() for p in tmp_path.iterdir())


def test_the_panel_shows_how_far_a_model_download_is(ui):
    ui.panel._bridge.model_download.emit("small", 231 * 1024 * 1024, 462 * 1024 * 1024)

    assert (
        ui.panel.detail.text()
        == "Downloading the small model (first use only): 231 of 462 MB (50%)"
    )
