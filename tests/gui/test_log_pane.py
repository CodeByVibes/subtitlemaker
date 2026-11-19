"""The log tab: what the library says while it works, shown as it happens."""

import logging
import threading

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

from subtitlemaker.gui.log_pane import MAX_LINES, LogPane, QtLogHandler  # noqa: E402
from subtitlemaker.log import LOGGER_NAME  # noqa: E402
from tests.conftest import make_segment  # noqa: E402
from tests.gui.helpers import media  # noqa: E402

WAIT = 5000  # ms

log = logging.getLogger(LOGGER_NAME)


@pytest.fixture
def pane(qtbot):
    pane = LogPane()
    qtbot.addWidget(pane)
    pane.attach()

    yield pane

    pane.detach()


def handlers():
    return [h for h in log.handlers if isinstance(h, QtLogHandler)]


# --- showing messages -------------------------------------------------------------------------


def test_messages_from_the_library_appear(pane):
    log.info("Transcribing talk.mp3")

    assert "Transcribing talk.mp3" in pane.plain_text()


def test_warnings_and_errors_read_as_they_do_on_the_command_line(pane):
    log.warning("couldn't determine duration: x")
    log.error("failed to process a.mp3: boom")

    assert "Warning: couldn't determine duration: x" in pane.plain_text()
    assert "Error: failed to process a.mp3: boom" in pane.plain_text()


def test_each_message_is_a_line_of_its_own(pane):
    log.info("one")
    log.info("two")
    log.info("three")

    assert pane.plain_text().splitlines() == ["one", "two", "three"]


def test_warnings_and_errors_are_coloured_and_plain_messages_are_not(pane):
    log.info("plain")
    log.warning("careful")
    log.error("broken")

    html = pane.text.document().toHtml()

    assert "#d97706" in html and "careful" in html  # amber
    assert "#ef4444" in html and "broken" in html  # red
    assert html.count("#d97706") == 1 and html.count("#ef4444") == 1  # only those two


def test_text_that_looks_like_markup_is_shown_as_text(pane):
    log.info("Input: /videos/<b>Show</b> & [Friends] :tada:.mkv")

    assert "Input: /videos/<b>Show</b> & [Friends] :tada:.mkv" in pane.plain_text()


def test_spacing_is_kept_exactly(pane):
    # The command line aligns its columns with spaces, and a file name can have two in a row.
    log.info("Model:          tiny")
    log.info("Input:          /videos/My  Show - 1x01.mkv")
    log.info("  indented")

    assert pane.plain_text().splitlines() == [
        "Model:          tiny",
        "Input:          /videos/My  Show - 1x01.mkv",
        "  indented",
    ]


def test_a_message_of_several_lines_stays_together(pane):
    log.info("first\nsecond\nthird")
    log.info("next message")

    assert pane.plain_text().splitlines() == ["first", "second", "third", "next message"]


def test_the_view_follows_new_lines_until_the_user_scrolls_up(pane):
    pane.resize(500, 200)
    pane.show()

    for i in range(200):
        log.info("line %d", i)

    bar = pane.text.verticalScrollBar()
    assert bar.value() == bar.maximum()  # following the newest line

    bar.setValue(0)  # the user scrolls up to read
    log.info("a new line arrives")

    assert bar.value() == 0  # and is not pulled away

    bar.setValue(bar.maximum())  # back at the bottom
    log.info("another")

    assert bar.value() == bar.maximum()  # following again


def test_tracebacks_are_kept(pane):
    try:
        raise ValueError("kaboom")

    except ValueError:
        log.error("it failed", exc_info=True)

    assert "Traceback" in pane.plain_text() and "kaboom" in pane.plain_text()


def test_only_the_libraries_own_messages_appear(pane):
    logging.getLogger("something_else").warning("not ours")
    logging.getLogger(LOGGER_NAME + ".transcribe").warning("ours, from a sub module")

    assert "not ours" not in pane.plain_text()
    assert "ours, from a sub module" in pane.plain_text()


def test_the_log_keeps_the_most_recent_lines(pane):
    for i in range(MAX_LINES + 50):
        log.info("line %d", i)

    lines = pane.plain_text().splitlines()

    assert len(lines) == MAX_LINES
    assert lines[-1] == f"line {MAX_LINES + 49}"
    assert lines[0] == "line 50"  # the oldest were dropped


def test_messages_from_another_thread_arrive_in_the_qt_thread(pane, qtbot):
    delivered = []
    original = pane._add

    def spy(level, text):
        delivered.append((threading.current_thread() is threading.main_thread(), text))
        original(level, text)

    pane._lines.line.disconnect()
    pane._lines.line.connect(spy)

    worker = threading.Thread(target=lambda: log.info("from the worker"))
    worker.start()
    worker.join()

    qtbot.waitUntil(lambda: bool(delivered), timeout=WAIT)

    assert delivered == [(True, "from the worker")]


# --- the level --------------------------------------------------------------------------------


def test_normal_messages_show_but_debug_messages_need_show_details(pane):
    log.debug("technical detail")
    assert "technical detail" not in pane.plain_text()

    pane.details_check.setChecked(True)
    log.debug("technical detail")
    assert "technical detail" in pane.plain_text()

    pane.details_check.setChecked(False)
    log.debug("another detail")
    assert "another detail" not in pane.plain_text()


def test_show_details_also_turns_on_whispers_own_log(pane):
    whisper = logging.getLogger("faster_whisper")
    assert whisper.level != logging.DEBUG

    pane.details_check.setChecked(True)
    assert whisper.level == logging.DEBUG

    pane.details_check.setChecked(False)
    assert whisper.level != logging.DEBUG


# --- attaching and detaching ------------------------------------------------------------------


def test_the_pane_adds_exactly_one_handler_and_removes_it(qtbot):
    before = handlers()
    pane = LogPane()
    qtbot.addWidget(pane)

    pane.attach()
    pane.attach()  # harmless to repeat
    assert len(handlers()) == len(before) + 1
    assert pane.is_attached()

    pane.detach()
    pane.detach()
    assert handlers() == before
    assert not pane.is_attached()


def test_detaching_puts_the_logger_level_back(qtbot):
    log.setLevel(logging.ERROR)
    pane = LogPane()
    qtbot.addWidget(pane)

    pane.attach()
    assert log.level == logging.INFO

    pane.detach()
    assert log.level == logging.ERROR


def test_a_detached_pane_shows_nothing_more(pane):
    log.info("before")
    pane.detach()
    log.warning("after")

    assert "before" in pane.plain_text() and "after" not in pane.plain_text()


def test_other_handlers_are_left_alone(qtbot, caplog):
    # pytest's own capture handler must survive the pane coming and going.
    pane = LogPane()
    qtbot.addWidget(pane)

    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        pane.attach()
        log.info("seen by both")
        pane.detach()
        log.info("seen by pytest only")

    assert "seen by both" in caplog.text and "seen by pytest only" in caplog.text
    assert "seen by pytest only" not in pane.plain_text()


def test_a_deleted_pane_does_not_break_logging(qtbot, capsys):
    import shiboken6

    pane = LogPane()
    pane.attach()
    handler = handlers()[-1]

    shiboken6.delete(pane._lines)  # as if the pane were destroyed without detaching
    log.warning("nobody is listening")  # must not raise or print a logging error

    assert handler not in log.handlers  # it removed itself
    assert "Logging error" not in capsys.readouterr().err

    pane.detach()


# --- the buttons ------------------------------------------------------------------------------


def test_clear_empties_the_log(pane):
    log.info("something")

    pane.clear_button.click()

    assert pane.plain_text() == ""


def test_copy_puts_the_whole_log_on_the_clipboard(pane):
    log.info("first")
    log.warning("second")

    pane.copy_button.click()

    assert QApplication.clipboard().text() == "first\nWarning: second"


def test_save_writes_the_log_to_the_chosen_file(pane, tmp_path, monkeypatch):
    target = tmp_path / "out.txt"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )
    log.info("first")
    log.error("second")

    pane.save_button.click()

    assert target.read_text(encoding="utf-8") == "first\nError: second\n"


def test_cancelling_the_save_dialog_writes_nothing(pane, tmp_path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    log.info("first")

    pane.save_button.click()

    assert list(tmp_path.iterdir()) == []


def test_a_file_that_cannot_be_written_is_reported_not_raised(pane, tmp_path, monkeypatch):
    shown = []
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        staticmethod(lambda *a, **k: (str(tmp_path / "missing-folder" / "out.txt"), "")),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda parent, title, text, *a, **k: shown.append(text)),
    )
    log.info("first")

    pane.save_button.click()

    assert len(shown) == 1 and "out.txt" in shown[0]


# --- in the window ----------------------------------------------------------------------------


def test_the_window_has_a_log_tab_that_follows_a_real_run(make_window, qtbot, fake_model, tmp_path):
    window = make_window()
    window.panel.add_paths(media(tmp_path, "talk.mp3"))

    window.panel.start_button.click()
    qtbot.waitUntil(lambda: "1 done" in window.panel.detail.text(), timeout=WAIT)
    qtbot.waitUntil(lambda: "Generated" in window.log_pane.plain_text(), timeout=WAIT)

    text = window.log_pane.plain_text()

    assert "Input:" in text and "talk.mp3" in text
    assert "Transcribing..." in text
    assert "Generated 1 subtitle cues." in text
    assert "Writing:" in text


def test_a_warning_from_a_run_shows_in_the_log(make_window, qtbot, fake_model, tmp_path):
    fake_model.segments = [
        make_segment(
            " mikey what's going on what's going on in there are you okay now i get it",
            i * 5.0,
            i * 5.0 + 4.0,
        )
        for i in range(12)
    ]
    window = make_window()
    window.panel.add_paths(media(tmp_path, "a.mp3"))

    window.panel.start_button.click()
    qtbot.waitUntil(lambda: "almost no punctuation" in window.log_pane.plain_text(), timeout=WAIT)

    assert "Warning: Whisper wrote almost no punctuation" in window.log_pane.plain_text()


def test_a_failed_file_is_in_the_log_with_its_reason(make_window, qtbot, fake_model, tmp_path):
    fake_model.fail["bad.mp3"] = ValueError("boom")
    window = make_window()
    window.panel.add_paths(media(tmp_path, "bad.mp3", "ok.mp3"))

    window.panel.start_button.click()
    qtbot.waitUntil(lambda: "Finished:" in window.log_pane.plain_text(), timeout=WAIT)

    text = window.log_pane.plain_text()

    assert "Error: failed to process" in text and "bad.mp3" in text and "boom" in text
    assert "Finished: 1 done, 1 failed." in text
    assert window.tabs.tabText(2) == "Log ●"  # a failure calls for attention


def test_the_log_tab_is_marked_by_a_warning_until_it_is_opened(make_window, qtbot):
    window = make_window()
    assert window.tabs.tabText(2) == "Log"

    log.info("just information")
    assert window.tabs.tabText(2) == "Log"  # only warnings and errors call for attention

    log.warning("look at this")
    assert window.tabs.tabText(2) == "Log ●"

    window.tabs.setCurrentWidget(window.log_pane)
    assert window.tabs.tabText(2) == "Log"

    log.error("this too")  # already on the tab: nothing to point at
    assert window.tabs.tabText(2) == "Log"


def test_closing_the_window_detaches_the_log(make_window):
    before = handlers()
    window = make_window()
    assert len(handlers()) == len(before) + 1

    window.close()

    assert handlers() == before
