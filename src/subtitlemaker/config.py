"""Configuration: defaults, config file loading and validation.

Precedence, lowest to highest: built-in defaults, config file, command line.
"""

import os
import sys
from dataclasses import dataclass, fields, replace
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


class ConfigError(ValueError):
    """Raised for an invalid config file or setting."""


@dataclass(frozen=True)
class SubtitleStyle:
    """How subtitle cues are laid out and timed."""

    max_line_length: int = 42  # Maximum characters per line
    max_lines: int = 2  # Maximum number of lines
    max_cps: float = 20.0  # Maximum characters per second
    min_duration: float = 1.0  # Minimum subtitle duration (seconds)
    max_duration: float = 7.0  # Maximum subtitle duration (seconds)
    min_gap: float = 0.05  # Minimum gap between subtitles (seconds)

    def __post_init__(self):
        for name in ("max_line_length", "max_lines"):
            if not isinstance(getattr(self, name), int) or getattr(self, name) < 1:
                raise ConfigError(f"{name} must be an integer of at least 1")

        for name in ("max_cps", "min_duration", "max_duration"):
            if getattr(self, name) <= 0:
                raise ConfigError(f"{name} must be greater than 0")

        if self.min_gap < 0:
            raise ConfigError("min_gap must not be negative")

        if self.min_duration > self.max_duration:
            raise ConfigError("min_duration must not be greater than max_duration")


@dataclass(frozen=True)
class ModelConfig:
    """Which Whisper model to run, and how."""

    name: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"
    vad_filter: bool = True
    condition_on_previous_text: bool = True


# Names accepted in each section of the config file.
_SECTIONS = {
    "style": SubtitleStyle,
    "model": ModelConfig,
}


def default_config_path():
    """Location of the user config file (respects XDG_CONFIG_HOME)."""

    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"

    return root / "subtitlemaker" / "config.toml"


def load_config(path=None):
    """
    Load the config file and return `(SubtitleStyle, ModelConfig)`.

    With `path=None` the default location is used and a missing file is
    fine. An explicit `path` that does not exist is an error.
    """

    explicit = path is not None
    path = Path(path) if explicit else default_config_path()

    if not path.is_file():
        if explicit:
            raise ConfigError(f"config file not found: {path}")

        return SubtitleStyle(), ModelConfig()

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)

    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML: {e}") from e

    unknown_sections = sorted(set(data) - set(_SECTIONS))

    if unknown_sections:
        raise ConfigError(f"{path}: unknown section(s): {', '.join(unknown_sections)}")

    built = {}

    for section, cls in _SECTIONS.items():
        values = data.get(section, {})
        allowed = {f.name: f for f in fields(cls)}
        unknown = sorted(set(values) - set(allowed))

        if unknown:
            raise ConfigError(
                f"{path}: unknown key(s) in [{section}]: {', '.join(unknown)}"
            )

        defaults = cls()

        for key, value in values.items():
            expected = type(getattr(defaults, key))

            # TOML integers are fine where a float is expected.
            if expected is float and isinstance(value, int) and not isinstance(value, bool):
                values[key] = float(value)

            elif not isinstance(value, expected) or (
                expected is int and isinstance(value, bool)
            ):
                raise ConfigError(
                    f"{path}: [{section}] {key} must be {expected.__name__}, "
                    f"got {type(value).__name__}"
                )

        try:
            built[section] = replace(defaults, **values)

        except ConfigError as e:
            raise ConfigError(f"{path}: [{section}] {e}") from e

    return built["style"], built["model"]
