import pytest

from subtitlemaker.config import (
    ConfigError,
    ModelConfig,
    SubtitleStyle,
    default_config_path,
    load_config,
)


def write(tmp_path, text):
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_defaults():
    style, model = SubtitleStyle(), ModelConfig()

    assert (style.max_line_length, style.max_lines, style.max_cps) == (42, 2, 20)
    assert (style.min_duration, style.max_duration, style.min_gap) == (1.0, 7.0, 0.05)
    assert (model.name, model.device, model.compute_type) == ("auto", "auto", "auto")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_line_length": 0},
        {"max_lines": 0},
        {"max_lines": 1.5},
        {"max_cps": 0},
        {"min_duration": 0},
        {"max_duration": -1},
        {"min_gap": -0.1},
        {"min_duration": 8, "max_duration": 7},
    ],
)
def test_invalid_style_is_rejected(kwargs):
    with pytest.raises(ConfigError):
        SubtitleStyle(**kwargs)


@pytest.mark.parametrize("kwargs", [{"device": "tpu"}, {"name": " "}, {"compute_type": ""}])
def test_invalid_model_config_is_rejected(kwargs):
    with pytest.raises(ConfigError):
        ModelConfig(**kwargs)


def test_file_values_override_defaults(tmp_path):
    path = write(
        tmp_path,
        '[style]\nmax_line_length = 30\nmax_cps = 17\n\n[model]\nname = "tiny"\ndevice = "cpu"\n',
    )

    style, model = load_config(path)

    assert style.max_line_length == 30
    assert style.max_cps == 17.0
    assert style.max_lines == 2  # untouched default
    assert (model.name, model.device) == ("tiny", "cpu")


def test_integer_is_accepted_where_float_expected(tmp_path):
    style, _ = load_config(write(tmp_path, "[style]\nmax_duration = 8\n"))

    assert style.max_duration == 8.0
    assert isinstance(style.max_duration, float)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[style]\nmax_cpz = 1\n", "unknown key"),
        ("[stlye]\n", "unknown section"),
        ('[style]\nmax_lines = "two"\n', "must be int"),
        ("[style]\nmax_lines = true\n", "must be int"),
        ("[model]\nvad_filter = 1\n", "must be bool"),
        ("[style]\nmin_duration = 9\n", "min_duration"),
        ('[model]\ndevice = "gpu"\n', "device must be one of"),
        ("x = [", "invalid TOML"),
    ],
)
def test_bad_files_give_clear_errors(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, text))


def test_explicit_missing_file_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.toml")


def test_missing_default_file_is_fine(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert load_config() == (SubtitleStyle(), ModelConfig())


def test_default_location_follows_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    (tmp_path / "subtitlemaker").mkdir()
    (tmp_path / "subtitlemaker" / "config.toml").write_text("[style]\nmax_lines = 1\n")

    assert default_config_path() == tmp_path / "subtitlemaker" / "config.toml"
    assert load_config()[0].max_lines == 1
