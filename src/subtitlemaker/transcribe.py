"""Whisper model access and language handling."""

import re

from faster_whisper import WhisperModel

from ._cuda import preload_cuda_libs

try:
    from faster_whisper.tokenizer import _LANGUAGE_CODES
except ImportError:
    _LANGUAGE_CODES = None


def load_model(name, device, compute_type):
    """Load a faster-whisper model."""

    if device == "cuda":
        preload_cuda_libs()

    return WhisperModel(
        name,
        device=device,
        compute_type=compute_type,
    )


def parse_language_argument(value):
    """
    Parse the -l/--language argument.

    Accepts a single language code ("he") or a comma or
    space separated list of codes ("he,en") for audio that
    contains more than one language.

    Returns (languages, multilingual), where `multilingual`
    is True when more than one code was given.
    """

    if not value:
        return [], False

    languages = []

    for code in re.split(r"[,\s]+", value.strip()):

        code = code.lower()

        if not code:
            continue

        if code not in languages:
            languages.append(code)

    if _LANGUAGE_CODES is not None:

        unknown = [
            code
            for code in languages
            if code not in _LANGUAGE_CODES
        ]

        if unknown:
            raise ValueError(
                f"unknown language code(s): "
                f"{', '.join(unknown)}"
            )

    return languages, len(languages) > 1
