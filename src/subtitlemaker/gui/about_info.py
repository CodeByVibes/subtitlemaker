"""What the About box says, built without Qt so it can be tested without a window."""

import importlib.metadata
import platform
import re
import sys
from pathlib import Path

from .. import __version__
from ..config import default_config_path

HOMEPAGE = "https://github.com/CodeByVibes/subtitlemaker"
ISSUES = "https://github.com/CodeByVibes/subtitlemaker/issues"
CHANGELOG = "https://github.com/CodeByVibes/subtitlemaker/blob/main/CHANGELOG.md"

DESCRIPTION = (
    "Subtitles from audio and video, made on your own computer with faster-whisper."
)

# (name, address, licence)
CREDITS = (
    ("faster-whisper", "https://github.com/SYSTRAN/faster-whisper", "MIT"),
    ("CTranslate2", "https://github.com/OpenNMT/CTranslate2", "MIT"),
    ("OpenAI Whisper models", "https://github.com/openai/whisper", "MIT"),
    ("Qt for Python (PySide6)", "https://doc.qt.io/qtforpython-6/", "LGPL-3.0"),
)

LICENCE = "SubtitleMaker is free software under the MIT licence."


def shorten_home(text: str, home: Path | None = None) -> str:
    """`text` with the user's home folder written as `~`, so a pasted report has no user name."""

    folder = str(home if home is not None else Path.home())

    if folder in ("", "/"):
        return text

    # Only where a path starts (not inside another path), and only the whole folder name.
    return re.sub(r"(?<![\w./~-])" + re.escape(folder) + r"(?=/|$|[\s)\]'\"])", "~", text)


def package_version(name: str) -> str:
    """The installed version of a package, or "unknown"."""

    try:
        return importlib.metadata.version(name)

    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def environment_report(
    *,
    qt: str,
    device: str,
    settings_file: Path | None,
    home: Path | None = None,
) -> str:
    """
    The details a bug report needs, as plain text.

    `qt` describes the Qt in use (version and platform), which only the window
    knows. Paths are shown with `~` for the home folder.
    """

    config = default_config_path()

    lines = [
        f"SubtitleMaker {__version__}",
        f"Python {sys.version.split()[0]} ({platform.python_implementation()})",
        f"OS: {platform.platform()}",
        f"Qt: {qt}",
        f"faster-whisper {package_version('faster-whisper')}, "
        f"CTranslate2 {package_version('ctranslate2')}",
        f"Device: {device}",
        f"Config file: {config}" + ("" if config.is_file() else " (not found)"),
    ]

    if settings_file is not None:
        lines.append(f"Settings file: {settings_file}")

    return shorten_home("\n".join(lines), home)
