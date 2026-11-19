"""The defaults the command line's help promises are the defaults the code uses.

The help text is written by hand, and the desktop app shows it as tooltips, so
a default that changes in the code but not in the help would mislead in both.
"""

import dataclasses
import re

import pytest

from subtitlemaker.cli import option_help
from subtitlemaker.config import ModelConfig, SubtitleStyle
from subtitlemaker.formats import DEFAULT_FORMAT
from subtitlemaker.settings import (
    DEFAULT_DETECT_SEGMENTS,
    DEFAULT_DETECT_THRESHOLD,
    DEFAULT_TASK,
)
from subtitlemaker.transcribe import DEFAULT_COMPUTE_TYPE, DEFAULT_MODEL


def promised_default(option: str) -> str:
    """The text after "(default: " in the option's help, up to a `;` or `)`."""

    match = re.search(r"\(default: ([^;)]+)", option_help()[option])

    assert match, f"{option}: no '(default: ...)' in its help"

    return match.group(1).strip()


@pytest.mark.parametrize("field", [f.name for f in dataclasses.fields(SubtitleStyle)])
def test_style_defaults_in_the_help_are_the_real_ones(field):
    assert float(promised_default(field)) == getattr(SubtitleStyle(), field)


def test_detection_defaults_in_the_help_are_the_real_ones():
    assert int(promised_default("detect_segments")) == DEFAULT_DETECT_SEGMENTS
    assert float(promised_default("detect_threshold")) == DEFAULT_DETECT_THRESHOLD


def test_model_defaults_in_the_help_are_the_real_ones():
    model = ModelConfig()

    assert promised_default("device") == model.device
    assert promised_default("task") == DEFAULT_TASK
    assert promised_default("format") == DEFAULT_FORMAT
    assert promised_default("prompt") == "none" and model.initial_prompt == ""
    assert float(promised_default("hallucination_silence_threshold").split(",")[0]) == (
        model.hallucination_silence_threshold
    )
    assert promised_default("word_timestamps") == "on" and model.word_timestamps is True

    # "large-v3 on GPU, small on CPU" and "float16 on GPU, int8 on CPU"
    assert promised_default("model") == (
        f"{DEFAULT_MODEL['cuda']} on GPU, {DEFAULT_MODEL['cpu']} on CPU"
    )
    assert promised_default("compute_type") == (
        f"{DEFAULT_COMPUTE_TYPE['cuda']} on GPU, {DEFAULT_COMPUTE_TYPE['cpu']} on CPU"
    )


def test_every_default_in_the_help_is_checked_above():
    # A new option that states a default must get a check here too.
    checked = {f.name for f in dataclasses.fields(SubtitleStyle)} | {
        "detect_segments",
        "detect_threshold",
        "device",
        "task",
        "format",
        "prompt",
        "hallucination_silence_threshold",
        "word_timestamps",
        "model",
        "compute_type",
        # stated in words that depend on the language, so not a single value to compare:
        "condition_on_previous_text",
        "config",
    }
    stating_a_default = {name for name, text in option_help().items() if "(default" in text}

    assert stating_a_default <= checked, sorted(stating_a_default - checked)


def test_the_help_covers_the_options_the_desktop_app_shows():
    help_text = option_help()

    for option in (
        "model", "device", "compute_type", "word_timestamps", "prompt", "language",
        "multilingual", "task", "format", "condition_on_previous_text",
        "hallucination_silence_threshold", "detect_segments", "detect_threshold",
        *(f.name for f in dataclasses.fields(SubtitleStyle)),
    ):  # fmt: skip
        assert help_text.get(option), option
