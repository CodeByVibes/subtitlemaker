"""Configuration: defaults, config file loading and validation.

Precedence, lowest to highest: built-in defaults, config file, command line.
"""

import math
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
    max_pause: float = 1.0  # Silence between two words that starts a new subtitle (seconds)
    linger: float = 0.5  # Time a subtitle stays up after its speech ends, if free (seconds)
    close_gap: float = 0.5  # A shorter gap between two subtitles is closed (seconds)

    def __post_init__(self) -> None:
        if not isinstance(self.max_line_length, int) or self.max_line_length < 1:
            raise ConfigError("max_line_length must be an integer of at least 1")

        if self.max_lines not in (1, 2):
            raise ConfigError("max_lines must be 1 or 2")

        # nan compares False with everything, so "<= 0" alone lets it through.
        for name in (
            "max_cps", "min_duration", "max_duration", "max_pause", "min_gap",
            "linger", "close_gap",
        ):
            if not math.isfinite(getattr(self, name)):
                raise ConfigError(f"{name} must be a finite number")

        for name in ("max_cps", "min_duration", "max_duration", "max_pause"):
            if getattr(self, name) <= 0:
                raise ConfigError(f"{name} must be greater than 0")

        for name in ("min_gap", "linger", "close_gap"):
            if getattr(self, name) < 0:
                raise ConfigError(f"{name} must not be negative")

        if self.min_duration > self.max_duration:
            raise ConfigError("min_duration must not be greater than max_duration")


DEVICES = ("auto", "cuda", "cpu")


@dataclass(frozen=True)
class ModelConfig:
    """
    Which Whisper model to run, and how.

    `name`, `device` and `compute_type` may be "auto", which is resolved
    at run time from the hardware (see `transcribe.resolve_model_config`).
    """

    name: str = "auto"  # model size, Hugging Face repo id, or local path
    device: str = "auto"  # auto, cuda or cpu
    compute_type: str = "auto"  # e.g. float16, int8, int8_float16
    vad_filter: bool = True
    condition_on_previous_text: bool = True
    word_timestamps: bool = True  # time cues from words, not whole segments
    initial_prompt: str = ""  # text Whisper continues from, sets the style (--prompt)
    # Skip silences longer than this where Whisper seems to invent text
    # (seconds; 0 = off). Needs word timestamps.
    hallucination_silence_threshold: float = 0.0

    def __post_init__(self) -> None:
        if self.device not in DEVICES:
            raise ConfigError(f"device must be one of: {', '.join(DEVICES)}")

        threshold = self.hallucination_silence_threshold

        if not math.isfinite(threshold) or threshold < 0:
            raise ConfigError(
                "hallucination_silence_threshold must be a finite number, 0 or more"
            )

        for name in ("name", "compute_type"):
            if not getattr(self, name).strip():
                raise ConfigError(f"{name} must not be empty")


# Names accepted in each section of the config file.
_SECTIONS = {
    "style": SubtitleStyle,
    "model": ModelConfig,
}


def default_config_path() -> Path:
    """Location of the user config file (respects XDG_CONFIG_HOME)."""

    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"

    return root / "subtitlemaker" / "config.toml"


def load_config(path: str | Path | None = None) -> tuple[SubtitleStyle, ModelConfig]:
    """
    Load the config file and return `(SubtitleStyle, ModelConfig)`.

    With `path=None` the default location is used and a missing file is
    fine. An explicit `path` that does not exist is an error.
    """

    explicit = path is not None
    path = default_config_path() if path is None else Path(path)

    if not path.is_file():
        if explicit and path.exists():
            raise ConfigError(f"config path is not a file: {path}")

        if explicit:
            raise ConfigError(f"config file not found: {path}")

        return SubtitleStyle(), ModelConfig()

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)

    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: invalid TOML: {e}") from e

    except OSError as e:
        raise ConfigError(f"couldn't read config file {path}: {e.strerror or e}") from e

    unknown_sections = sorted(set(data) - set(_SECTIONS))

    if unknown_sections:
        raise ConfigError(f"{path}: unknown section(s): {', '.join(unknown_sections)}")

    built = {}

    for section, cls in _SECTIONS.items():
        values = data.get(section, {})

        if not isinstance(values, dict):
            raise ConfigError(
                f"{path}: [{section}] must be a table, got {type(values).__name__}"
            )

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
