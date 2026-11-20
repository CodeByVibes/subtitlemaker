"""What the settings panel holds, and how it becomes `Settings`.

No Qt in here: the values are plain Python, so the rules (what counts as a
change, what is saved, how a form turns into a run's settings) are tested
without a window.

The form starts from the config file (or the built-in defaults), so a user
who keeps a `config.toml` sees their values. Only what the user *changed*
from that starting point is saved, so editing the config file later still
shows through for everything they never touched.
"""

import dataclasses
import json
import math
from collections.abc import Mapping
from typing import Any

from ..config import ConfigError, ModelConfig, SubtitleStyle, load_config
from ..settings import (
    DEFAULT_DETECT_SEGMENTS,
    DEFAULT_DETECT_THRESHOLD,
    DEFAULT_TASK,
    Settings,
    resolve_settings,
)

# Which `FormValues` fields are `ModelConfig` fields (the rest of those are
# settings of their own).
_MODEL_FIELDS = (
    "model_name",
    "device",
    "compute_type",
    "vad_filter",
    "word_timestamps",
    "initial_prompt",
    "hallucination_silence_threshold",
)

_STYLE_FIELDS = tuple(field.name for field in dataclasses.fields(SubtitleStyle))


@dataclasses.dataclass(frozen=True)
class FormValues:
    """Every value the settings panel shows."""

    # model
    model_name: str = "auto"
    device: str = "auto"
    compute_type: str = "auto"
    vad_filter: bool = True
    word_timestamps: bool = True
    initial_prompt: str = ""
    hallucination_silence_threshold: float = 0.0  # 0 = off

    # What to make
    formats: tuple[str, ...] = ("srt",)
    task: str = DEFAULT_TASK
    language: str = ""  # "" = detect it; "sv"; or "he,en" for several
    multilingual: bool = False
    # `None` = automatic: on, except when the language changes within the audio.
    condition_on_previous_text: bool | None = None
    detect_segments: int = DEFAULT_DETECT_SEGMENTS
    detect_threshold: float = DEFAULT_DETECT_THRESHOLD

    # subtitle style (the fields of `SubtitleStyle`)
    max_line_length: int = SubtitleStyle.max_line_length
    max_lines: int = SubtitleStyle.max_lines
    max_cps: float = SubtitleStyle.max_cps
    min_duration: float = SubtitleStyle.min_duration
    max_duration: float = SubtitleStyle.max_duration
    min_gap: float = SubtitleStyle.min_gap
    max_pause: float = SubtitleStyle.max_pause
    linger: float = SubtitleStyle.linger
    close_gap: float = SubtitleStyle.close_gap
    start_offset: float = SubtitleStyle.start_offset


def base_values() -> tuple[FormValues, str]:
    """
    The starting point: the config file's values (else the defaults).

    Returns `(values, problem)`; `problem` is the message to show when the
    config file is invalid (the built-in defaults are used then), else "".
    """

    try:
        style, model = load_config(None)
        problem = ""

    except ConfigError as e:
        style, model, problem = SubtitleStyle(), ModelConfig(), str(e)

    values = FormValues(
        model_name=model.name,
        device=model.device,
        compute_type=model.compute_type,
        vad_filter=model.vad_filter,
        word_timestamps=model.word_timestamps,
        initial_prompt=model.initial_prompt,
        hallucination_silence_threshold=model.hallucination_silence_threshold,
        **{name: getattr(style, name) for name in _STYLE_FIELDS},
    )

    return values, problem


def to_settings(values: FormValues) -> Settings:
    """
    The settings for a run. Raises `ConfigError` with a message fit to show.

    Everything in the form counts as chosen, so the form decides; the config
    file only supplies what the form starts from (see `base_values`).
    """

    if not values.formats:
        raise ConfigError("choose at least one output format")

    model = {
        "name": values.model_name,
        "device": values.device,
        "compute_type": values.compute_type,
        "vad_filter": values.vad_filter,
        "word_timestamps": values.word_timestamps,
        "initial_prompt": values.initial_prompt,
        "hallucination_silence_threshold": values.hallucination_silence_threshold,
    }

    return resolve_settings(
        style={name: getattr(values, name) for name in _STYLE_FIELDS},
        model=model,
        formats=",".join(values.formats),
        task=values.task,
        language=values.language or None,
        multilingual=values.multilingual,
        condition_on_previous_text=values.condition_on_previous_text,
        detect_segments=values.detect_segments,
        detect_threshold=values.detect_threshold,
    )


# --- saving only what the user changed ----------------------------------------------


def changes(values: FormValues, base: FormValues) -> dict[str, Any]:
    """The fields of `values` that differ from `base`, as JSON-friendly values."""

    result: dict[str, Any] = {}

    for field in dataclasses.fields(FormValues):
        value = getattr(values, field.name)

        if value != getattr(base, field.name):
            result[field.name] = list(value) if isinstance(value, tuple) else value

    return result


def encode(values: FormValues, base: FormValues) -> str:
    """What to store: the changes from `base`, as JSON."""

    return json.dumps(changes(values, base), sort_keys=True)


def decode(text: object, base: FormValues) -> FormValues:
    """
    `base` with the stored changes applied.

    Stored data can be anything (an older version, a hand edit, a damaged
    file), so whatever is unusable is ignored: unknown names, wrong types,
    and text that is not JSON at all.
    """

    if not isinstance(text, str) or not text.strip():
        return base

    try:
        stored = json.loads(text)

    except ValueError:
        return base

    if not isinstance(stored, Mapping):
        return base

    usable: dict[str, Any] = {}
    fields = {field.name: field for field in dataclasses.fields(FormValues)}

    for name, value in stored.items():

        if name not in fields:
            continue

        current = getattr(base, name)

        if name == "formats":

            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                usable[name] = tuple(value)

            continue

        if name == "condition_on_previous_text":

            if value is None or isinstance(value, bool):
                usable[name] = value

            continue

        if _fits(value, current):
            usable[name] = float(value) if isinstance(current, float) else value

    return dataclasses.replace(base, **usable)


def _fits(value: object, current: object) -> bool:
    """True if `value` is the same kind of thing as `current` (an int may stand for a float)."""

    if isinstance(current, bool):
        return isinstance(value, bool)

    if isinstance(current, float):
        # JSON can hold NaN and Infinity; they are never a usable setting.
        return (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(value)
        )

    if isinstance(current, int):
        return isinstance(value, int) and not isinstance(value, bool)

    return isinstance(value, type(current))
