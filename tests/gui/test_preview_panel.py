"""Opening the subtitle preview from the queue, and what comes back from it."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402

from subtitlemaker.gui.preview import CuePreviewDialog  # noqa: E402
from subtitlemaker.gui.queue_model import Status  # noqa: E402
from subtitlemaker.gui.settings_panel import SETTINGS_KEY  # noqa: E402
from tests.conftest import make_segment, make_word  # noqa: E402
from tests.gui.helpers import media  # noqa: E402

WAIT = 5000  # ms
SENTENCE = "She walked into the room and then the old man looked at the small dog on the floor"


@pytest.fixture(autouse=True)
def known_duration(monkeypatch):
    monkeypatch.setattr("subtitlemaker.pipeline.get_duration", lambda path: 10.0)


@pytest.fixture
def store(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def ran(make_window, qtbot, fake_model, tmp_path, store):
    """A window that has transcribed two files (the model says the same thing for both)."""

    words = SENTENCE.split()
    fake_model.segments = [
        make_segment(
            " " + " ".join(words) + ".",
            0.0,
            len(words) * 0.4,
            [make_word(f" {w}", i * 0.4, i * 0.4 + 0.3) for i, w in enumerate(words)],
        )
    ]
    window = make_window(use_panel=True, store=store)
    window.settings_panel.widget("max_line_length").setValue(16)
    window.panel.add_paths(media(tmp_path, "a.mp3", "b.mp3"))
    window.panel.start_button.click()
    qtbot.waitUntil(
        lambda: not window.panel.is_busy() and "2 done" in window.panel.detail.text(), timeout=WAIT
    )

    return window


def test_a_finished_file_has_a_result_and_a_queued_one_does_not(ran, tmp_path):
    ran.panel.add_paths(media(tmp_path, "later.mp3"))

    results = [item.result for item in ran.panel.model.items()]

    assert results[0] is not None and results[1] is not None
    assert results[2] is None


def test_the_preview_button_needs_exactly_one_file_with_a_result(ran, tmp_path):
    panel = ran.panel
    panel.add_paths(media(tmp_path, "later.mp3"))

    assert not panel.preview_button.isEnabled()  # nothing selected

    panel.view.selectRow(0)
    assert panel.preview_button.isEnabled()

    panel.view.selectRow(2)  # queued, never transcribed
    assert not panel.preview_button.isEnabled()

    panel.view.selectAll()
    assert not panel.preview_button.isEnabled()  # several at once


def test_the_preview_shows_that_files_subtitles(ran):
    ran.panel.view.selectRow(1)

    ran.panel.preview_button.click()

    (dialog,) = ran.panel.previews()

    assert isinstance(dialog, CuePreviewDialog)
    assert dialog.windowTitle() == "Subtitles of b.mp3"
    assert dialog.cues() == ran.panel.model.item(1).result.subtitles


def test_asking_again_raises_the_same_preview_instead_of_opening_another(ran):
    first = ran.panel.open_preview(0)
    again = ran.panel.open_preview(0)
    other = ran.panel.open_preview(1)

    assert again is first
    assert other is not first
    assert len(ran.panel.previews()) == 2


def test_a_closed_preview_can_be_opened_again(ran, qtbot):
    first = ran.panel.open_preview(0)

    first.close()
    qtbot.waitUntil(lambda: ran.panel.previews() == [], timeout=WAIT)

    assert ran.panel.open_preview(0) is not None
    assert len(ran.panel.previews()) == 1


def test_double_clicking_a_finished_file_opens_its_preview(ran):
    ran.panel.view.doubleClicked.emit(ran.panel.model.index(0, 0))

    assert len(ran.panel.previews()) == 1


def test_double_clicking_a_file_without_a_result_does_nothing(ran, tmp_path, warnings):
    ran.panel.add_paths(media(tmp_path, "later.mp3"))

    ran.panel.view.doubleClicked.emit(ran.panel.model.index(2, 0))

    assert ran.panel.previews() == [] and warnings == []


def test_a_file_without_a_transcript_says_so(ran, tmp_path, warnings):
    ran.panel.add_paths(media(tmp_path, "later.mp3"))

    assert ran.panel.open_preview(2) is None

    assert warnings == [("No preview", "later.mp3 has not been transcribed in this session.")]


def test_queueing_a_file_again_takes_its_preview_away(ran):
    ran.panel.view.selectRow(0)
    assert ran.panel.preview_button.isEnabled()

    ran.panel.requeue_button.click()

    assert ran.panel.model.item(0).status is Status.QUEUED
    assert not ran.panel.preview_button.isEnabled()


def test_the_preview_uses_the_style_of_the_run_not_the_current_settings(ran):
    ran.settings_panel.widget("max_line_length").setValue(42)  # changed after the run

    dialog = ran.panel.open_preview(0)

    assert dialog.style_form.widget("max_line_length").value() == 16
    assert dialog.cues() == ran.panel.model.item(0).result.subtitles


# --- a style tried in the preview becomes the style for new files --------------------------------


def test_a_style_kept_in_the_preview_reaches_the_settings(ran, store):
    dialog = ran.panel.open_preview(0)
    dialog.style_form.widget("max_line_length").setValue(33)
    dialog.style_form.widget("linger").setValue(0.0)

    dialog.keep_button.click()

    form = ran.settings_panel.values()

    assert form.max_line_length == 33 and form.linger == 0.0
    assert ran.settings_panel.widget("max_line_length").value() == 33
    assert '"max_line_length": 33' in store.value(SETTINGS_KEY)  # and it is remembered


def test_the_style_chosen_is_used_for_the_next_run(ran, qtbot, fake_model, tmp_path):
    dialog = ran.panel.open_preview(0)
    dialog.style_form.widget("max_line_length").setValue(60)
    dialog.keep_button.click()

    ran.panel.add_paths(media(tmp_path, "next.mp3"))
    ran.panel.detail.setText("")
    ran.panel.start_button.click()
    qtbot.waitUntil(lambda: "1 done" in ran.panel.detail.text(), timeout=WAIT)

    assert ran.panel.model.item(2).result.style.max_line_length == 60


def test_closing_the_window_closes_its_previews(ran, qtbot):
    ran.panel.open_preview(0)
    ran.panel.open_preview(1)
    assert len(ran.panel.previews()) == 2

    ran.close()

    qtbot.waitUntil(lambda: ran.panel.previews() == [], timeout=WAIT)
