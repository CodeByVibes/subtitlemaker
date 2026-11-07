"""Parsing of the -l/--language argument (light: no machine learning imports)."""

import re
from collections.abc import Collection


def _known_language_codes() -> Collection[str] | None:
    """Whisper's language codes, or None if they can't be looked up."""

    # Imported here so that --help and --version stay fast.
    try:
        from faster_whisper.tokenizer import _LANGUAGE_CODES

    except ImportError:
        return None

    codes: Collection[str] = _LANGUAGE_CODES

    return codes


def parse_language_argument(value: str | None) -> tuple[list[str], bool]:
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

    codes = _known_language_codes()

    if codes is not None:

        unknown = [
            code
            for code in languages
            if code not in codes
        ]

        if unknown:
            raise ValueError(
                f"unknown language code(s): "
                f"{', '.join(unknown)}"
            )

    return languages, len(languages) > 1
