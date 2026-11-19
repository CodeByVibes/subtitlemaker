"""The settings panel: what a user sees and what a run gets."""

import dataclasses

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QSpinBox,
)

from subtitlemaker.cli import option_help  # noqa: E402
from subtitlemaker.config import ConfigError  # noqa: E402
from subtitlemaker.gui.queue_model import Status  # noqa: E402
from subtitlemaker.gui.settings_form import FormValues, to_settings  # noqa: E402
from subtitlemaker.gui.settings_panel import (  # noqa: E402
    _MODEL_CHOICES,
    SETTINGS_KEY,
    SettingsPanel,
    device_summary,
)
from tests.gui.helpers import media  # noqa: E402

WAIT = 5000  # ms


def write_config(tmp_path, text):
    folder = tmp_path / "xdg-config" / "subtitlemaker"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "config.toml").write_text(text)


@pytest.fixture
def store(tmp_path):
    return QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)


@pytest.fixture
def panel(qtbot):
    panel = SettingsPanel()
    qtbot.addWidget(panel)

    return panel


def test_the_panel_starts_at_the_defaults(panel):
    assert panel.values() == FormValues()
    assert panel.settings() == to_settings(FormValues())
    assert panel.error_label.isHidden()


def test_every_value_has_an_editor(panel):
    for field in dataclasses.fields(FormValues):
        assert panel.widget(field.name) is not None, field.name


def test_what_is_set_is_what_is_shown(panel):
    values = FormValues(
        model_name="small",
        device="cpu",
        compute_type="int8",
        vad_filter=False,
        word_timestamps=False,
        initial_prompt="Hello, everyone.",
        hallucination_silence_threshold=2.0,
        formats=("vtt", "txt"),
        task="translate",
        language="he,en",
        multilingual=True,
        condition_on_previous_text=False,
        detect_segments=3,
        detect_threshold=0.8,
        max_line_length=30,
        max_lines=1,
        max_cps=15.0,
        min_duration=0.5,
        max_duration=5.0,
        min_gap=0.1,
        max_pause=2.0,
        linger=0.0,
        close_gap=0.2,
    )

    panel.set_values(values)

    assert panel.values() == values


@pytest.mark.parametrize("previous", [None, True, False])
def test_previous_text_remembers_all_three_choices(panel, previous):
    panel.set_values(FormValues(condition_on_previous_text=previous))

    assert panel.values().condition_on_previous_text is previous


# --- the editors ------------------------------------------------------------------------------


def test_editing_the_widgets_changes_the_values(panel):
    panel.widget("model_name").setCurrentText("tiny")
    panel.widget("language").setText("sv")
    panel.widget("multilingual").setChecked(True)
    panel.widget("task").setCurrentIndex(panel.widget("task").findData("translate"))
    panel.widget("initial_prompt").setText("Hej.")
    panel.widget("max_line_length").setValue(33)
    panel.widget("max_lines").setCurrentIndex(0)  # "1"
    panel.widget("linger").setValue(0.0)
    panel.widget("device").setCurrentText("cpu")
    panel.widget("compute_type").setCurrentText("int8")
    panel.widget("word_timestamps").setChecked(False)
    panel.widget("vad_filter").setChecked(False)
    panel.widget("hallucination_silence_threshold").setValue(1.5)
    panel.widget("detect_segments").setValue(2)
    panel.widget("detect_threshold").setValue(0.9)

    values = panel.values()

    assert values.model_name == "tiny"
    assert values.language == "sv"
    assert values.multilingual is True
    assert values.task == "translate"
    assert values.initial_prompt == "Hej."
    assert values.max_line_length == 33
    assert values.max_lines == 1
    assert values.linger == 0.0
    assert values.device == "cpu"
    assert values.compute_type == "int8"
    assert values.word_timestamps is False
    assert values.vad_filter is False
    assert values.hallucination_silence_threshold == 1.5
    assert values.detect_segments == 2
    assert values.detect_threshold == 0.9


def test_the_output_formats_are_checkboxes(panel):
    assert panel.values().formats == ("srt",)

    boxes = {box.text(): box for box in panel.widget("formats").findChildren(QCheckBox)}
    assert sorted(boxes) == ["SRT", "TXT", "VTT"]

    boxes["VTT"].setChecked(True)
    boxes["SRT"].setChecked(False)

    assert panel.values().formats == ("vtt",)  # in the order the formats are defined


def test_the_editors_are_the_right_kind_of_widget(panel):
    assert isinstance(panel.widget("model_name"), QComboBox)
    assert panel.widget("model_name").isEditable()  # any name or path can be typed
    assert not panel.widget("device").isEditable()
    assert isinstance(panel.widget("language"), QLineEdit)
    assert isinstance(panel.widget("max_line_length"), QSpinBox)
    assert isinstance(panel.widget("linger"), QDoubleSpinBox)
    assert isinstance(panel.widget("multilingual"), QCheckBox)


def test_the_language_box_suggests_whisper_language_codes(panel):
    completer = panel.widget("language").completer()
    codes = [completer.model().index(i, 0).data() for i in range(completer.model().rowCount())]

    assert "sv" in codes and "en" in codes and len(codes) == 100


def test_the_model_choices_are_models_that_exist(panel):
    from faster_whisper import available_models

    # A list kept by hand must not drift from what faster-whisper can download.
    assert set(_MODEL_CHOICES) - {"auto"} <= set(available_models())
    box = panel.widget("model_name")
    assert [box.itemText(i) for i in range(box.count())] == list(_MODEL_CHOICES)


# --- mistakes are shown as they happen --------------------------------------------------------


def test_a_mistake_is_shown_at_once_and_goes_away_when_fixed(panel):
    panel.widget("language").setText("xx")

    assert panel.error_label.isVisibleTo(panel)
    assert "unknown language code" in panel.error_label.text()

    panel.widget("language").setText("sv")

    assert panel.error_label.isHidden()


def test_the_message_is_at_the_top_where_it_cannot_scroll_out_of_sight(panel):
    layout = panel.layout()
    order = [layout.itemAt(i).widget() for i in range(layout.count()) if layout.itemAt(i).widget()]

    # right after the device line, before every control
    assert order.index(panel.error_label) == order.index(panel.device_label) + 1
    assert order.index(panel.error_label) < order.index(panel.style_section)


def test_a_form_that_contradicts_itself_says_so(panel):
    panel.widget("min_duration").setValue(10.0)
    panel.widget("max_duration").setValue(2.0)

    assert "min_duration must not be greater than max_duration" in panel.error_label.text()


def test_at_least_one_format_is_needed(panel):
    for box in panel.widget("formats").findChildren(QCheckBox):
        box.setChecked(False)

    assert "choose at least one output format" in panel.error_label.text()

    with pytest.raises(ConfigError, match="at least one output format"):
        panel.settings()


def test_a_broken_form_stops_a_run_with_the_same_message(panel):
    panel.widget("language").setText("xx")

    with pytest.raises(ConfigError, match="unknown language code"):
        panel.settings()


def test_the_panel_announces_edits_but_not_what_it_loads_itself(panel, qtbot):
    with qtbot.waitSignal(panel.changed, timeout=WAIT):
        panel.widget("max_lines").setCurrentIndex(0)

    with qtbot.assertNotEmitted(panel.changed):
        panel.set_values(FormValues(task="translate"))


# --- the sections -----------------------------------------------------------------------------


def test_style_and_advanced_start_closed_and_open_on_click(panel):
    for section in (panel.style_section, panel.advanced_section):
        assert not section.is_expanded()
        assert section.content.isHidden()

    panel.style_section.toggle.click()

    assert panel.style_section.is_expanded()
    assert not panel.style_section.content.isHidden()
    assert panel.advanced_section.content.isHidden()  # the other one is unaffected

    panel.style_section.toggle.click()

    assert panel.style_section.content.isHidden()


# --- the help comes from the command line -----------------------------------------------------


@pytest.mark.parametrize(
    ("field", "option"),
    [
        ("model_name", "model"),
        ("device", "device"),
        ("compute_type", "compute_type"),
        ("word_timestamps", "word_timestamps"),
        ("initial_prompt", "prompt"),
        ("language", "language"),
        ("multilingual", "multilingual"),
        ("task", "task"),
        ("formats", "format"),
        ("condition_on_previous_text", "condition_on_previous_text"),
        ("hallucination_silence_threshold", "hallucination_silence_threshold"),
        ("detect_segments", "detect_segments"),
        ("detect_threshold", "detect_threshold"),
        ("max_line_length", "max_line_length"),
        ("max_lines", "max_lines"),
        ("max_cps", "max_cps"),
        ("min_duration", "min_duration"),
        ("max_duration", "max_duration"),
        ("min_gap", "min_gap"),
        ("max_pause", "max_pause"),
        ("linger", "linger"),
        ("close_gap", "close_gap"),
    ],
)
def test_tooltips_are_the_command_lines_help(panel, field, option):
    assert panel.widget(field).toolTip() == option_help()[option]


def test_the_silence_filter_has_a_tooltip_of_its_own(panel):
    # There is no command line flag for it, so no command line help either.
    assert "silence" in panel.widget("vad_filter").toolTip().lower()


# --- where the starting values come from ------------------------------------------------------


def test_the_config_file_sets_what_the_panel_starts_with(qtbot, tmp_path):
    write_config(tmp_path, '[style]\nmax_line_length = 30\nlinger = 0\n\n[model]\nname = "small"\n')

    panel = SettingsPanel()
    qtbot.addWidget(panel)

    assert panel.widget("max_line_length").value() == 30
    assert panel.widget("linger").value() == 0
    assert panel.widget("model_name").currentText() == "small"
    assert panel.widget("max_lines").currentData() == 2  # not in the file: the default


def test_a_broken_config_file_is_shown_in_the_panel(qtbot, tmp_path):
    write_config(tmp_path, "[style]\nmax_lines = 3\n")

    panel = SettingsPanel()
    qtbot.addWidget(panel)

    assert panel.values() == FormValues()  # the panel still works, on the defaults
    assert "max_lines must be 1 or 2" in panel.error_label.text()
    assert "config.toml" in panel.error_label.text()

    with pytest.raises(ConfigError):
        panel.settings()  # and it will not run on a config it could not read


# --- remembering between sessions -------------------------------------------------------------


def test_what_the_user_changed_is_there_next_time(qtbot, store):
    first = SettingsPanel(store)
    qtbot.addWidget(first)
    first.widget("language").setText("sv")
    first.widget("task").setCurrentIndex(first.widget("task").findData("translate"))
    first.widget("max_line_length").setValue(33)
    for box in first.widget("formats").findChildren(QCheckBox):
        box.setChecked(box.text() in ("SRT", "VTT"))

    second = SettingsPanel(store)
    qtbot.addWidget(second)

    assert second.values() == first.values()
    assert second.values().language == "sv"
    assert second.values().formats == ("srt", "vtt")


def test_only_changes_are_stored(qtbot, store):
    panel = SettingsPanel(store)
    qtbot.addWidget(panel)

    assert store.value(SETTINGS_KEY, "") in ("", "{}")

    panel.widget("max_lines").setCurrentIndex(0)

    assert store.value(SETTINGS_KEY) == '{"max_lines": 1}'


def test_untouched_settings_follow_the_config_file_after_it_changes(qtbot, tmp_path, store):
    write_config(tmp_path, "[style]\nmax_line_length = 30\n")
    first = SettingsPanel(store)
    qtbot.addWidget(first)
    first.widget("max_lines").setCurrentIndex(0)  # the only thing the user touched

    write_config(tmp_path, "[style]\nmax_line_length = 50\n")  # the file is edited later
    second = SettingsPanel(store)
    qtbot.addWidget(second)

    assert second.widget("max_lines").currentData() == 1  # kept
    assert second.widget("max_line_length").value() == 50  # followed the file


def test_damaged_stored_settings_are_ignored(qtbot, store):
    store.setValue(SETTINGS_KEY, "{this is not json")

    panel = SettingsPanel(store)
    qtbot.addWidget(panel)

    assert panel.values() == FormValues()


def test_reset_goes_back_and_forgets(qtbot, tmp_path, store):
    write_config(tmp_path, "[style]\nmax_line_length = 30\n")
    panel = SettingsPanel(store)
    qtbot.addWidget(panel)
    panel.widget("max_line_length").setValue(60)
    panel.widget("language").setText("sv")

    panel.reset_button.click()

    assert panel.widget("max_line_length").value() == 30  # the config file's, not the built-in 42
    assert panel.widget("language").text() == ""
    assert store.value(SETTINGS_KEY) == "{}"
    assert panel.error_label.isHidden()


def test_without_a_store_nothing_is_kept(qtbot):
    first = SettingsPanel()
    qtbot.addWidget(first)
    first.widget("language").setText("sv")

    second = SettingsPanel()
    qtbot.addWidget(second)

    assert second.widget("language").text() == ""


# --- what the machine can do ------------------------------------------------------------------


def test_the_device_line_says_what_will_run(monkeypatch):
    monkeypatch.setattr("subtitlemaker.transcribe.cuda_available", lambda: False)
    assert "No NVIDIA GPU" in device_summary() and "CPU" in device_summary()

    monkeypatch.setattr("subtitlemaker.transcribe.cuda_available", lambda: True)
    monkeypatch.setattr("subtitlemaker._cuda.pip_libs_installed", lambda: True)
    assert "GPU found and ready" in device_summary()

    monkeypatch.setattr("subtitlemaker._cuda.pip_libs_installed", lambda: False)
    text = device_summary()
    assert "GPU found" in text and "pip install 'subtitlemaker[cuda]'" in text


def test_the_panel_shows_the_device_line(qtbot, monkeypatch):
    monkeypatch.setattr("subtitlemaker.transcribe.cuda_available", lambda: False)

    panel = SettingsPanel()
    qtbot.addWidget(panel)

    assert "No NVIDIA GPU" in panel.device_label.text()


# --- in the window: the panel drives the run --------------------------------------------------


def run_with_panel(make_window, qtbot, tmp_path, *, store=None, files=("a.mp3",), edit=None):
    """Open a window that uses its settings panel, apply `edit(window)`, run `files`."""

    window = make_window(use_panel=True, store=store)

    if edit:
        edit(window)

    window.panel.add_paths(media(tmp_path, *files))
    window.panel.start_button.click()
    qtbot.waitUntil(
        lambda: not window.panel.is_busy() and "done" in window.panel.detail.text(), timeout=WAIT
    )

    return window


def test_the_chosen_formats_are_what_gets_written(make_window, qtbot, fake_model, tmp_path):
    def choose(window):
        for box in window.settings_panel.widget("formats").findChildren(QCheckBox):
            box.setChecked(box.text() in ("VTT", "TXT"))

    run_with_panel(make_window, qtbot, tmp_path, edit=choose)

    assert (tmp_path / "a.vtt").exists() and (tmp_path / "a.txt").exists()
    assert not (tmp_path / "a.srt").exists()


def test_language_task_and_prompt_reach_the_model(make_window, qtbot, fake_model, tmp_path):
    def choose(window):
        panel = window.settings_panel
        panel.widget("language").setText("sv")
        panel.widget("task").setCurrentIndex(panel.widget("task").findData("translate"))
        panel.widget("initial_prompt").setText("Hej, alla.")
        panel.widget("word_timestamps").setChecked(False)
        panel.widget("vad_filter").setChecked(False)

    run_with_panel(make_window, qtbot, tmp_path, edit=choose)

    call = fake_model.calls[0]

    assert call["language"] == "sv"
    assert call["task"] == "translate"
    assert call["initial_prompt"] == "Hej, alla."
    assert call["word_timestamps"] is False
    assert call["vad_filter"] is False


def test_the_chosen_model_is_the_one_loaded(make_window, qtbot, fake_model, tmp_path):
    def choose(window):
        window.settings_panel.widget("model_name").setCurrentText("base")

    run_with_panel(make_window, qtbot, tmp_path, edit=choose)

    assert fake_model.requested.name == "base"


def test_subtitle_style_changes_the_subtitles(make_window, qtbot, fake_model, tmp_path):
    from tests.conftest import make_segment, make_word

    fake_model.segments = [
        make_segment(
            " one two three four five six seven eight",
            0.0,
            4.0,
            [make_word(f" w{i}", i * 0.5, i * 0.5 + 0.4) for i in range(8)],
        )
    ]

    def choose(window):
        window.settings_panel.widget("max_line_length").setValue(10)
        window.settings_panel.widget("max_lines").setCurrentIndex(0)  # one line

    run_with_panel(make_window, qtbot, tmp_path, edit=choose)

    text = (tmp_path / "a.srt").read_text()
    cues = [block for block in text.strip().split("\n\n") if block]

    assert len(cues) > 1  # long text was split into several one-line subtitles
    assert all(len(line) <= 10 for block in cues for line in block.split("\n")[2:])


def test_a_mistake_in_the_panel_stops_start_with_a_message(
    make_window, warnings, fake_model, tmp_path
):
    window = make_window(use_panel=True)
    window.settings_panel.widget("language").setText("xx")
    window.panel.add_paths(media(tmp_path, "a.mp3"))

    window.panel.start_button.click()

    assert warnings and warnings[0][0] == "Settings"
    assert "unknown language code" in warnings[0][1]
    assert [i.status for i in window.panel.model.items()] == [Status.QUEUED]
    assert fake_model.calls == []


def test_settings_chosen_in_one_session_are_used_in_the_next(
    make_window, qtbot, fake_model, tmp_path, store
):
    first = make_window(use_panel=True, store=store)
    first.settings_panel.widget("language").setText("sv")
    first.close()

    run_with_panel(make_window, qtbot, tmp_path, store=store)

    assert fake_model.calls[0]["language"] == "sv"


def test_run_keeps_the_settings_in_the_apps_own_file(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from subtitlemaker.gui.app import run
    from subtitlemaker.gui.main_window import MainWindow

    windows = []
    monkeypatch.setattr(QApplication, "exec", staticmethod(lambda: 0))
    monkeypatch.setattr(MainWindow, "show", lambda self: windows.append(self))

    run([])

    # The window `run` opened keeps what the user changes, in the app's own file ...
    windows[0].settings_panel.widget("language").setText("sv")

    app_file = tmp_path / "xdg-config" / "subtitlemaker" / "SubtitleMaker.conf"
    assert QSettings().fileName() == str(app_file)  # ... next to the config file
    assert QSettings().value(SETTINGS_KEY) == '{"language": "sv"}'

    windows[0].bridge.shutdown()
