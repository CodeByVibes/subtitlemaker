"""The subtitle preview: cues shown, and rebuilt live as the style changes."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QModelIndex, Qt  # noqa: E402
from PySide6.QtWidgets import QMessageBox  # noqa: E402

from subtitlemaker.config import SubtitleStyle  # noqa: E402
from subtitlemaker.formats import FORMATS  # noqa: E402
from subtitlemaker.gui.preview import (  # noqa: E402
    COL_END,
    COL_NUMBER,
    COL_SPEED,
    COL_START,
    COL_TEXT,
    REBUILD_DELAY_MS,
    CueModel,
    CuePreviewDialog,
    characters_per_second,
)
from subtitlemaker.pipeline import process_file  # noqa: E402
from subtitlemaker.settings import resolve_settings  # noqa: E402
from tests.conftest import make_segment, make_word  # noqa: E402

WAIT = 5000  # ms

SENTENCE = "She walked into the room and then the old man looked at the small dog on the floor"


@pytest.fixture(autouse=True)
def known_duration(monkeypatch):
    monkeypatch.setattr("subtitlemaker.pipeline.get_duration", lambda path: 10.0)


@pytest.fixture
def result(fake_model, tmp_path):
    """A real result, from a sentence whose subtitles depend on the style."""

    words = SENTENCE.split()
    fake_model.segments = [
        make_segment(
            " " + " ".join(words) + ".",
            0.0,
            len(words) * 0.4,
            [make_word(f" {w}", i * 0.4, i * 0.4 + 0.3) for i, w in enumerate(words)],
        )
    ]
    media = tmp_path / "talk.mp3"
    media.write_bytes(b"")
    settings = resolve_settings(model={"name": "tiny"}, style={"max_line_length": 16})

    return process_file(
        fake_model,
        media,
        {"srt": tmp_path / "talk.srt", "vtt": tmp_path / "talk.vtt"},
        settings.options(),
    )


@pytest.fixture
def dialog(qtbot, result):
    from subtitlemaker.cli import option_help

    dialog = CuePreviewDialog(result, option_help())
    qtbot.addWidget(dialog)

    return dialog


def spin(dialog, name):
    return dialog.style_form.widget(name)


# --- the table model --------------------------------------------------------------------------


def cue(start, end, text):
    return {"start": start, "end": end, "text": text}


def test_the_table_shows_number_times_speed_and_text():
    model = CueModel()
    model.set_cues([cue(1.25, 3.25, "Hello there"), cue(3.5, 65.0, "Second\ncue")])

    def cell(row, column, role=Qt.ItemDataRole.DisplayRole):
        return model.index(row, column).data(role)

    assert cell(0, COL_NUMBER) == 1 and cell(1, COL_NUMBER) == 2
    assert cell(0, COL_START) == "00:00:01.250"
    assert cell(0, COL_END) == "00:00:03.250"
    assert cell(1, COL_END) == "00:01:05.000"
    assert cell(0, COL_SPEED) == "5.5"  # 11 characters in 2 seconds
    assert cell(0, COL_TEXT) == "Hello there"
    assert cell(1, COL_TEXT) == "Second ↵ cue"  # a line break is shown, not lost
    assert cell(1, COL_TEXT, Qt.ItemDataRole.ToolTipRole) == "Second\ncue"
    assert model.rowCount() == 2 and model.columnCount() == 5


def test_the_column_headers():
    model = CueModel()
    headers = [
        model.headerData(c, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
        for c in range(5)
    ]

    assert headers == ["#", "Start", "End", "Chars/s", "Text"]


def test_setting_new_cues_replaces_the_old_ones(qtbot):
    model = CueModel()
    model.set_cues([cue(0, 1, "a"), cue(1, 2, "b"), cue(2, 3, "c")])

    with qtbot.waitSignal(model.modelReset):
        model.set_cues([cue(0, 1, "only")])

    assert model.rowCount() == 1 and model.cues() == [cue(0, 1, "only")]


def test_bad_indexes_give_no_data():
    model = CueModel()
    model.set_cues([cue(0, 1, "a")])

    assert model.data(QModelIndex()) is None
    assert model.index(7, 0).data() is None


def test_reading_speed_counts_characters_not_line_breaks():
    assert characters_per_second(cue(0, 2, "ab\ncd")) == 2.0
    assert characters_per_second(cue(0, 0, "x")) == 0.0  # no time on screen: not a division by zero


# --- the dialog -------------------------------------------------------------------------------


def test_the_dialog_shows_the_cues_of_the_run(dialog, result):
    assert dialog.cues() == result.subtitles
    assert dialog.model.rowCount() == len(result.subtitles)
    assert "talk.mp3" in dialog.windowTitle()
    assert dialog.summary.text().startswith(f"{len(result.subtitles)} subtitles")
    assert "the run made" not in dialog.summary.text()  # nothing has changed yet


def test_the_style_form_starts_with_the_style_the_run_used(dialog, result):
    assert dialog.current_style() == result.style
    assert spin(dialog, "max_line_length").value() == 16


def test_changing_the_style_builds_the_cues_again_without_the_model(
    dialog, result, fake_model, qtbot
):
    calls_before = len(fake_model.calls)

    spin(dialog, "max_line_length").setValue(30)
    dialog.flush()

    expected = result.rebuild(SubtitleStyle(**{**vars(result.style), "max_line_length": 30}))

    assert dialog.cues() == expected
    assert dialog.cues() != result.subtitles
    assert dialog.model.cues() == expected  # the table follows
    assert f"(the run made {len(result.subtitles)})" in dialog.summary.text()
    assert len(fake_model.calls) == calls_before  # the model never ran again


def test_a_burst_of_edits_builds_once(dialog, qtbot):
    resets = []
    dialog.model.modelReset.connect(lambda: resets.append(1))

    for width in (18, 20, 22, 24, 26, 28):  # typing in a box
        spin(dialog, "max_line_length").setValue(width)

    assert resets == []  # nothing yet: waiting for the edits to settle

    qtbot.waitUntil(lambda: len(resets) == 1, timeout=WAIT)
    qtbot.wait(REBUILD_DELAY_MS * 2)

    assert resets == [1]
    assert dialog.current_style().max_line_length == 28


def test_a_style_that_contradicts_itself_keeps_the_last_good_cues(dialog, result):
    good = dialog.cues()

    spin(dialog, "min_duration").setValue(10.0)
    spin(dialog, "max_duration").setValue(2.0)
    dialog.flush()

    assert dialog.error_label.isVisibleTo(dialog)
    assert "min_duration must not be greater than max_duration" in dialog.error_label.text()
    assert dialog.cues() == good  # still the last good ones
    assert not dialog.save_button.isEnabled()  # nothing broken can be saved

    spin(dialog, "max_duration").setValue(20.0)
    dialog.flush()

    assert dialog.error_label.isHidden()
    assert dialog.save_button.isEnabled()


def test_back_to_the_style_used_restores_the_cues(dialog, result):
    spin(dialog, "max_line_length").setValue(42)
    spin(dialog, "max_lines").setCurrentIndex(0)
    dialog.flush()
    assert dialog.cues() != result.subtitles

    dialog.reset_button.click()

    assert dialog.current_style() == result.style
    assert dialog.cues() == result.subtitles
    assert "the run made" not in dialog.summary.text()


def test_a_style_can_be_offered_for_new_files(dialog, qtbot):
    spin(dialog, "max_line_length").setValue(33)  # still waiting for its delay: must be included

    with qtbot.waitSignal(dialog.style_chosen, timeout=WAIT) as signal:
        dialog.keep_button.click()

    style = signal.args[0]

    assert isinstance(style, SubtitleStyle)
    assert style.max_line_length == 33
    assert "new files" in dialog.status.text()


def test_a_broken_style_is_not_offered(dialog, qtbot):
    spin(dialog, "min_duration").setValue(10.0)
    spin(dialog, "max_duration").setValue(2.0)

    with qtbot.assertNotEmitted(dialog.style_chosen):
        dialog.keep_button.click()


# --- saving -----------------------------------------------------------------------------------


@pytest.fixture
def answer(monkeypatch):
    """Answers the "replace the files?" question; records what was asked and any warnings."""

    asked, warned = [], []
    reply = {"value": QMessageBox.StandardButton.Yes}

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda parent, title, text, *a, **k: (asked.append(text), reply["value"])[1]),
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda parent, title, text, *a, **k: warned.append(text)),
    )

    return type("Answer", (), {"asked": asked, "warned": warned, "reply": reply})


def test_saving_writes_the_shown_cues_to_every_output(dialog, result, answer, tmp_path):
    spin(dialog, "max_line_length").setValue(30)  # an edit still waiting: saved too

    assert dialog.save() is True

    cues = result.rebuild(SubtitleStyle(**{**vars(result.style), "max_line_length": 30}))

    for name, path in result.outputs.items():
        FORMATS[name].write(cues, tmp_path / f"expected.{name}")

        assert path.read_text() == (tmp_path / f"expected.{name}").read_text(), name

    assert (
        str(result.outputs["srt"]) in answer.asked[0]
        and str(result.outputs["vtt"]) in answer.asked[0]
    )
    assert dialog.status.text() == f"Saved {len(cues)} subtitles."


def contents(result):
    return {name: path.read_text() for name, path in result.outputs.items()}


def test_saving_can_be_declined(dialog, result, answer):
    before = contents(result)  # the run wrote these
    answer.reply["value"] = QMessageBox.StandardButton.No
    spin(dialog, "max_line_length").setValue(30)

    assert dialog.save() is False

    assert contents(result) == before  # untouched


def test_a_broken_style_cannot_be_saved(dialog, result, answer):
    before = contents(result)
    spin(dialog, "min_duration").setValue(10.0)
    spin(dialog, "max_duration").setValue(2.0)

    assert dialog.save() is False

    assert answer.asked == []  # not even asked
    assert contents(result) == before


def test_a_file_that_cannot_be_written_is_reported(qtbot, result, answer, tmp_path):
    from dataclasses import replace

    from subtitlemaker.cli import option_help

    broken = replace(result, outputs={"srt": tmp_path / "missing-folder" / "talk.srt"})
    other = CuePreviewDialog(broken, option_help())
    qtbot.addWidget(other)

    assert other.save() is False

    assert len(answer.warned) == 1
    assert "No such file or directory" in answer.warned[0]
    assert other.status.text() == ""  # and it does not claim to have saved


# --- the layout -------------------------------------------------------------------------------


def test_the_style_pane_is_wide_enough_that_nothing_is_clipped(dialog, qtbot):
    dialog.show()
    qtbot.waitExposed(dialog)

    bar = dialog.side_scroll.horizontalScrollBar()
    form = dialog.style_form

    assert bar.maximum() == 0  # nothing to scroll sideways: the whole form fits
    assert form.width() >= form.minimumSizeHint().width()
    for name in ("max_line_length", "max_cps", "close_gap"):
        editor = dialog.style_form.widget(name)
        assert editor.width() >= editor.minimumSizeHint().width(), name  # its arrows are visible


def test_the_dialog_is_not_too_wide_for_a_small_screen(dialog):
    assert dialog.width() <= 1000 and dialog.minimumSizeHint().width() <= 900
