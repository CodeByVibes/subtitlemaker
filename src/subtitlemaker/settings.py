"""Everything decided before a run starts, from plain values.

The command line and the desktop app both build their settings here, so
they follow the same precedence (built-in defaults < config file < what the
user chose) and reject the same invalid values. Nothing in this module knows
about argparse or a user interface: problems are raised as `ConfigError`.
"""

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .config import ConfigError, ModelConfig, SubtitleStyle, load_config
from .formats import parse_formats
from .languages import parse_language_argument
from .pipeline import Options

TASKS = ("transcribe", "translate")
DEFAULT_TASK = "transcribe"

# How many segments are sampled for the first language guess, and how sure
# Whisper has to be about it.
DEFAULT_DETECT_SEGMENTS = 1
DEFAULT_DETECT_THRESHOLD = 0.5


@dataclasses.dataclass(frozen=True)
class Settings:
    """Everything decided from the user's choices and the config file."""

    style: SubtitleStyle
    model_config: ModelConfig
    formats: list[str]
    task: str
    languages: list[str]
    language_hint: str | None
    multilingual: bool
    condition_on_previous_text: bool
    detect_segments: int
    detect_threshold: float

    def options(self, model_config: ModelConfig | None = None) -> Options:
        """
        The per-run `Options` for `pipeline.process_file`.

        Pass the `ModelConfig` that was actually loaded (with "auto" resolved
        to a real model and device); by default the requested one is used.
        """

        return Options(
            style=self.style,
            model_config=model_config or self.model_config,
            task=self.task,
            languages=self.languages,
            language_hint=self.language_hint,
            multilingual=self.multilingual,
            condition_on_previous_text=self.condition_on_previous_text,
            detect_segments=self.detect_segments,
            detect_threshold=self.detect_threshold,
        )


def resolve_settings(
    *,
    config: str | Path | None = None,
    style: Mapping[str, Any] | None = None,
    model: Mapping[str, Any] | None = None,
    formats: str | None = None,
    task: str = DEFAULT_TASK,
    language: str | None = None,
    multilingual: bool = False,
    condition_on_previous_text: bool | None = None,
    detect_segments: int = DEFAULT_DETECT_SEGMENTS,
    detect_threshold: float = DEFAULT_DETECT_THRESHOLD,
) -> Settings:
    """
    Combine the built-in defaults, the config file and the user's choices.

    `style` and `model` hold the values the user chose, keyed by the field
    names of `SubtitleStyle` and `ModelConfig`; a value of `None` means "not
    chosen" and leaves the config file or default in place. `config` is a
    config file path (`None` uses the default location, if it exists).
    `formats` is a comma separated list such as "srt,vtt". `language` is a
    code such as "sv", or several separated by commas.

    Raises `ConfigError` with a message fit to show the user.
    """

    style_config, model_config = load_config(config)

    style_choices = _chosen(style)
    model_choices = _chosen(model)

    try:
        style_config = dataclasses.replace(style_config, **style_choices)
        model_config = dataclasses.replace(model_config, **model_choices)

    except TypeError as e:
        # Not a user error: the caller used a name that is not a setting.
        raise ValueError(f"unknown setting: {e}") from e

    try:
        format_names = parse_formats(formats)

    except ValueError as e:
        raise ConfigError(str(e)) from e

    if task not in TASKS:
        raise ConfigError(f"task must be one of: {', '.join(TASKS)}")

    try:
        languages, listed_multilingual = parse_language_argument(language)

    except ValueError as e:
        raise ConfigError(str(e)) from e

    if detect_segments < 1:
        raise ConfigError("detect_segments must be at least 1")

    if not 0.0 < detect_threshold <= 1.0:
        raise ConfigError("detect_threshold must be greater than 0 and at most 1")

    # More than one language code, or an explicit multilingual choice, means
    # the language has to be decided again for every segment instead of once
    # for the whole file.
    multilingual = multilingual or listed_multilingual

    # Whisper holds a single language token per decode, so a hint is only
    # used when the language is fixed for the whole file. Leaving it unset
    # also keeps the initial detection available for the report.
    language_hint = None if multilingual else (languages[0] if languages else None)

    if condition_on_previous_text is None:

        # Text from the previous segment pulls the next one back towards the
        # language it was written in, which fights per-segment language
        # detection.
        condition_on_previous_text = model_config.condition_on_previous_text and not multilingual

    return Settings(
        style=style_config,
        model_config=model_config,
        formats=format_names,
        task=task,
        languages=languages,
        language_hint=language_hint,
        multilingual=multilingual,
        condition_on_previous_text=condition_on_previous_text,
        detect_segments=detect_segments,
        detect_threshold=detect_threshold,
    )


def _chosen(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """The entries of `values` that were actually chosen (not `None`)."""

    return {key: value for key, value in (values or {}).items() if value is not None}
