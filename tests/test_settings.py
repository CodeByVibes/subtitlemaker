"""`resolve_settings`, the settings logic shared by the CLI and the desktop app."""

import pytest

from subtitlemaker.config import ConfigError, ModelConfig, SubtitleStyle
from subtitlemaker.settings import Settings, resolve_settings


@pytest.fixture(autouse=True)
def no_user_config(tmp_path, monkeypatch):
    """Never read the real ~/.config/subtitlemaker/config.toml."""

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "no-config-here"))


@pytest.fixture
def config_file(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "[style]\nmax_line_length = 30\nlinger = 0\n\n"
        '[model]\nname = "small"\nword_timestamps = false\n'
    )

    return path


# --- precedence: defaults < config file < what the user chose ---------------------


def test_without_choices_everything_is_the_default():
    settings = resolve_settings()

    assert isinstance(settings, Settings)
    assert settings.style == SubtitleStyle()
    assert settings.model_config == ModelConfig()
    assert settings.formats == ["srt"]
    assert settings.task == "transcribe"
    assert settings.languages == []
    assert settings.language_hint is None
    assert settings.multilingual is False
    assert settings.condition_on_previous_text is True


def test_config_file_overrides_the_defaults(config_file):
    settings = resolve_settings(config=config_file)

    assert settings.style.max_line_length == 30
    assert settings.style.linger == 0
    assert settings.style.max_lines == 2  # not in the file: still the default
    assert settings.model_config.name == "small"
    assert settings.model_config.word_timestamps is False


def test_a_choice_overrides_the_config_file(config_file):
    settings = resolve_settings(
        config=config_file,
        style={"max_line_length": 50},
        model={"name": "tiny"},
    )

    assert settings.style.max_line_length == 50
    assert settings.style.linger == 0  # the file's value survives
    assert settings.model_config.name == "tiny"
    assert settings.model_config.word_timestamps is False


def test_none_means_not_chosen(config_file):
    settings = resolve_settings(
        config=config_file,
        style={"max_line_length": None, "max_cps": None},
        model={"name": None, "word_timestamps": None},
    )

    assert settings.style.max_line_length == 30
    assert settings.model_config.name == "small"
    assert settings.model_config.word_timestamps is False


def test_false_is_a_choice_not_an_absence(config_file):
    # `False` and `0` are real values; only `None` means "not chosen".
    settings = resolve_settings(
        style={"linger": 0},
        model={"word_timestamps": False},
    )

    assert settings.style.linger == 0
    assert settings.model_config.word_timestamps is False


def test_the_default_config_location_is_used_without_a_path(tmp_path, monkeypatch):
    folder = tmp_path / "xdg" / "subtitlemaker"
    folder.mkdir(parents=True)
    (folder / "config.toml").write_text("[style]\nmax_lines = 1\n")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert resolve_settings().style.max_lines == 1


# --- invalid values are ConfigError, with the message to show ---------------------


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"formats": "doc"}, "unknown output format"),
        ({"language": "xx"}, "unknown language code"),
        ({"task": "summarize"}, "task must be one of: transcribe, translate"),
        ({"detect_segments": 0}, "detect_segments must be at least 1"),
        ({"detect_threshold": 0}, "detect_threshold must be greater than 0"),
        ({"detect_threshold": 1.5}, "detect_threshold must be greater than 0"),
        ({"style": {"max_lines": 3}}, "max_lines must be 1 or 2"),
        ({"style": {"min_duration": 9.0}}, "min_duration must not be greater"),
        ({"model": {"device": "tpu"}}, "device must be one of"),
        ({"model": {"name": ""}}, "name must not be empty"),
        ({"model": {"hallucination_silence_threshold": -1.0}}, "hallucination_silence"),
        ({"config": "does-not-exist.toml"}, "config file not found"),
    ],
)
def test_invalid_values_are_config_errors(kwargs, message):
    with pytest.raises(ConfigError, match=message):
        resolve_settings(**kwargs)


def test_an_unknown_setting_name_is_a_programming_error():
    with pytest.raises(ValueError, match="unknown setting"):
        resolve_settings(style={"max_linez": 1})


# --- formats and languages --------------------------------------------------------


def test_formats_are_parsed_in_order_without_duplicates():
    assert resolve_settings(formats="vtt, srt,vtt").formats == ["vtt", "srt"]


def test_one_language_is_a_hint_for_the_whole_file():
    settings = resolve_settings(language="sv")

    assert settings.languages == ["sv"]
    assert settings.language_hint == "sv"
    assert settings.multilingual is False


def test_several_languages_switch_on_per_segment_detection():
    settings = resolve_settings(language="he,en")

    assert settings.languages == ["he", "en"]
    assert settings.multilingual is True
    assert settings.language_hint is None  # Whisper holds one language per decode


def test_multilingual_without_languages():
    settings = resolve_settings(multilingual=True)

    assert settings.multilingual is True
    assert settings.languages == []
    assert settings.language_hint is None


def test_multilingual_with_one_language_still_has_no_hint():
    settings = resolve_settings(language="sv", multilingual=True)

    assert settings.languages == ["sv"]
    assert settings.language_hint is None


# --- condition_on_previous_text ---------------------------------------------------


def test_previous_text_is_on_by_default_and_off_when_multilingual():
    assert resolve_settings().condition_on_previous_text is True
    assert resolve_settings(multilingual=True).condition_on_previous_text is False
    assert resolve_settings(language="en,sv").condition_on_previous_text is False


def test_previous_text_follows_the_config_file(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text("[model]\ncondition_on_previous_text = false\n")

    assert resolve_settings(config=path).condition_on_previous_text is False


def test_an_explicit_previous_text_choice_wins_even_when_multilingual():
    settings = resolve_settings(multilingual=True, condition_on_previous_text=True)

    assert settings.condition_on_previous_text is True
    assert resolve_settings(condition_on_previous_text=False).condition_on_previous_text is False


# --- the per-run options ----------------------------------------------------------


def test_options_carry_the_settings_for_process_file():
    settings = resolve_settings(
        task="translate", language="sv", detect_segments=3, detect_threshold=0.8
    )

    options = settings.options()

    assert options.style == settings.style
    assert options.model_config == settings.model_config
    assert options.task == "translate"
    assert options.languages == ["sv"]
    assert options.language_hint == "sv"
    assert options.multilingual is False
    assert options.condition_on_previous_text is True
    assert options.detect_segments == 3
    assert options.detect_threshold == 0.8


def test_options_use_the_model_that_was_actually_loaded():
    settings = resolve_settings()
    loaded = ModelConfig(name="large-v3", device="cuda", compute_type="float16")

    assert settings.options(loaded).model_config == loaded
    assert settings.options().model_config == ModelConfig()  # "auto" until resolved
