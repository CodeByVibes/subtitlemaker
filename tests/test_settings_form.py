"""The settings panel's values and rules, without any window (Qt is not needed)."""

import dataclasses
import json

import pytest

from subtitlemaker.config import ConfigError, ModelConfig, SubtitleStyle
from subtitlemaker.gui.settings_form import (
    FormValues,
    base_values,
    changes,
    decode,
    encode,
    to_settings,
)
from subtitlemaker.settings import resolve_settings


@pytest.fixture(autouse=True)
def no_user_config(tmp_path, monkeypatch):
    """Never read the real ~/.config/subtitlemaker/config.toml."""

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


def write_config(tmp_path, text):
    folder = tmp_path / "xdg" / "subtitlemaker"
    folder.mkdir(parents=True)
    (folder / "config.toml").write_text(text)


# --- where the form starts ----------------------------------------------------------


def test_the_form_defaults_are_the_library_defaults():
    values, problem = base_values()

    assert problem == ""
    assert values == FormValues()  # one source of truth: the dataclasses' own defaults

    style, model = SubtitleStyle(), ModelConfig()

    for field in dataclasses.fields(style):
        assert getattr(values, field.name) == getattr(style, field.name), field.name

    assert values.model_name == model.name
    assert values.device == model.device
    assert values.compute_type == model.compute_type
    assert values.vad_filter == model.vad_filter
    assert values.word_timestamps == model.word_timestamps
    assert values.initial_prompt == model.initial_prompt
    assert values.hallucination_silence_threshold == model.hallucination_silence_threshold


def test_the_config_file_seeds_the_form(tmp_path):
    write_config(
        tmp_path,
        '[style]\nmax_line_length = 30\nlinger = 0\n\n[model]\nname = "small"\n'
        'initial_prompt = "Hello, there."\n',
    )

    values, problem = base_values()

    assert problem == ""
    assert values.max_line_length == 30
    assert values.linger == 0
    assert values.model_name == "small"
    assert values.initial_prompt == "Hello, there."
    assert values.max_lines == 2  # not in the file: the default


def test_a_broken_config_file_gives_the_defaults_and_says_why(tmp_path):
    write_config(tmp_path, "[style]\nmax_lines = 3\n")

    values, problem = base_values()

    assert values == FormValues()
    assert "max_lines must be 1 or 2" in problem


# --- turning the form into a run's settings -----------------------------------------


def test_the_default_form_gives_the_default_settings():
    assert to_settings(FormValues()) == resolve_settings()


@pytest.mark.parametrize(
    ("change", "check"),
    [
        ({"model_name": "tiny"}, lambda s: s.model_config.name == "tiny"),
        ({"device": "cpu"}, lambda s: s.model_config.device == "cpu"),
        ({"compute_type": "int8"}, lambda s: s.model_config.compute_type == "int8"),
        ({"vad_filter": False}, lambda s: s.model_config.vad_filter is False),
        ({"word_timestamps": False}, lambda s: s.model_config.word_timestamps is False),
        ({"initial_prompt": "Hi."}, lambda s: s.model_config.initial_prompt == "Hi."),
        (
            {"hallucination_silence_threshold": 2.0},
            lambda s: s.model_config.hallucination_silence_threshold == 2.0,
        ),
        ({"formats": ("vtt", "srt")}, lambda s: s.formats == ["vtt", "srt"]),
        ({"formats": ("txt",)}, lambda s: s.formats == ["txt"]),
        ({"task": "translate"}, lambda s: s.task == "translate"),
        ({"language": "sv"}, lambda s: s.languages == ["sv"] and s.language_hint == "sv"),
        ({"language": " sv "}, lambda s: s.languages == ["sv"]),
        ({"language": ""}, lambda s: s.languages == [] and s.language_hint is None),
        ({"language": "he, en"}, lambda s: s.languages == ["he", "en"] and s.multilingual),
        ({"multilingual": True}, lambda s: s.multilingual and s.language_hint is None),
        ({"condition_on_previous_text": False}, lambda s: s.condition_on_previous_text is False),
        ({"condition_on_previous_text": True}, lambda s: s.condition_on_previous_text is True),
        ({"detect_segments": 3}, lambda s: s.detect_segments == 3),
        ({"detect_threshold": 0.8}, lambda s: s.detect_threshold == 0.8),
        ({"max_line_length": 30}, lambda s: s.style.max_line_length == 30),
        ({"max_lines": 1}, lambda s: s.style.max_lines == 1),
        ({"max_cps": 15.0}, lambda s: s.style.max_cps == 15.0),
        ({"min_duration": 0.5}, lambda s: s.style.min_duration == 0.5),
        ({"max_duration": 5.0}, lambda s: s.style.max_duration == 5.0),
        ({"min_gap": 0.1}, lambda s: s.style.min_gap == 0.1),
        ({"max_pause": 2.0}, lambda s: s.style.max_pause == 2.0),
        ({"linger": 0.0}, lambda s: s.style.linger == 0.0),
        ({"close_gap": 0.0}, lambda s: s.style.close_gap == 0.0),
    ],
    ids=lambda value: next(iter(value)) if isinstance(value, dict) else "",
)
def test_every_field_reaches_the_settings(change, check):
    assert check(to_settings(FormValues(**change)))


def test_every_form_field_is_covered_by_that_table():
    # A new field added to FormValues must be wired up and listed above.
    covered = {
        "model_name", "device", "compute_type", "vad_filter", "word_timestamps",
        "initial_prompt", "hallucination_silence_threshold", "formats", "task", "language",
        "multilingual", "condition_on_previous_text", "detect_segments", "detect_threshold",
        "max_line_length", "max_lines", "max_cps", "min_duration", "max_duration", "min_gap",
        "max_pause", "linger", "close_gap",
    }  # fmt: skip

    assert {f.name for f in dataclasses.fields(FormValues)} == covered


def test_automatic_previous_text_follows_the_config_file(tmp_path):
    write_config(tmp_path, "[model]\ncondition_on_previous_text = false\n")

    assert to_settings(FormValues()).condition_on_previous_text is False
    assert to_settings(FormValues(condition_on_previous_text=True)).condition_on_previous_text


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"formats": ()}, "choose at least one output format"),
        ({"language": "xx"}, "unknown language code"),
        ({"task": "summarise"}, "task must be one of"),
        ({"device": "tpu"}, "device must be one of"),
        ({"max_lines": 3}, "max_lines must be 1 or 2"),
        ({"min_duration": 9.0, "max_duration": 2.0}, "min_duration must not be greater"),
        ({"detect_segments": 0}, "detect_segments must be at least 1"),
        ({"detect_threshold": 0.0}, "detect_threshold must be greater than 0"),
        ({"model_name": ""}, "name must not be empty"),
        ({"hallucination_silence_threshold": -1.0}, "hallucination_silence_threshold"),
    ],
)
def test_invalid_forms_are_config_errors_with_a_readable_message(change, message):
    with pytest.raises(ConfigError, match=message):
        to_settings(FormValues(**change))


def test_a_broken_config_file_is_reported_when_starting(tmp_path):
    write_config(tmp_path, "[style\n")

    with pytest.raises(ConfigError, match="invalid TOML"):
        to_settings(FormValues())


# --- saving only what changed -------------------------------------------------------


def test_nothing_changed_nothing_saved():
    assert changes(FormValues(), FormValues()) == {}
    assert encode(FormValues(), FormValues()) == "{}"


def test_only_the_changed_fields_are_saved():
    values = FormValues(task="translate", max_lines=1, formats=("srt", "vtt"), language="sv")

    assert changes(values, FormValues()) == {
        "task": "translate",
        "max_lines": 1,
        "formats": ["srt", "vtt"],  # a list: JSON has no tuples
        "language": "sv",
    }


def test_what_is_saved_comes_back():
    base = FormValues()
    values = dataclasses.replace(
        base,
        model_name="small",
        formats=("vtt", "txt"),
        multilingual=True,
        linger=0.0,
        condition_on_previous_text=False,
        initial_prompt="Hello, everyone.",
        max_cps=17.5,
    )

    assert decode(encode(values, base), base) == values


def test_none_is_a_saved_choice_too():
    # "Automatic" is a real choice for previous text, distinct from on and off.
    base = FormValues(condition_on_previous_text=True)
    values = dataclasses.replace(base, condition_on_previous_text=None)

    assert decode(encode(values, base), base).condition_on_previous_text is None


def test_untouched_fields_follow_a_changed_config_file():
    old_base = FormValues(max_line_length=30, linger=0.0)
    chosen = dataclasses.replace(old_base, max_lines=1)  # the only thing the user touched
    stored = encode(chosen, old_base)

    new_base = FormValues(max_line_length=50, linger=0.2)  # the config file was edited

    restored = decode(stored, new_base)

    assert restored.max_lines == 1  # their change survives
    assert restored.max_line_length == 50  # the file's new values show through
    assert restored.linger == 0.2


@pytest.mark.parametrize(
    "stored",
    [
        None,
        "",
        "   ",
        5,
        ["x"],
        "not json at all",
        "[]",
        '"just a string"',
        "{",
        '{"no_such_setting": 1}',
        '{"max_lines": "two"}',
        '{"linger": true}',
        '{"max_line_length": 4.5}',
        '{"max_line_length": true}',
        '{"formats": "srt"}',
        '{"formats": [1, 2]}',
        '{"vad_filter": "yes"}',
        '{"condition_on_previous_text": "no"}',
        '{"max_cps": NaN}',
        '{"max_cps": Infinity}',
        '{"initial_prompt": 7}',
    ],
)
def test_unusable_stored_data_is_ignored(stored):
    assert decode(stored, FormValues()) == FormValues()


def test_good_entries_survive_next_to_bad_ones():
    stored = json.dumps({"max_lines": "two", "linger": 0.1, "nonsense": 1, "task": "translate"})

    restored = decode(stored, FormValues())

    assert restored.linger == 0.1
    assert restored.task == "translate"
    assert restored.max_lines == FormValues().max_lines


def test_a_whole_number_may_stand_for_a_decimal():
    assert decode('{"linger": 1}', FormValues()).linger == 1.0
    assert isinstance(decode('{"linger": 1}', FormValues()).linger, float)
