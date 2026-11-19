"""The desktop app (needs the `gui` extra: `pip install subtitlemaker[gui]`).

Importing this package does not import Qt, so `main` can explain what is
missing instead of failing with a traceback.
"""

import sys

INSTALL_HINT = (
    "The desktop app needs PySide6. Install it with:\n"
    "    pip install 'subtitlemaker[gui]'"
)


def main() -> int:
    """Entry point of `subtitlemaker-gui`: open the window, return the exit code."""

    try:
        import PySide6  # noqa: F401

    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 1

    from .app import run

    return run()
