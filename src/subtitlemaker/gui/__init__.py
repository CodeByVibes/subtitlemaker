"""The desktop app (needs the `gui` extra: `pip install subtitlemaker[gui]`).

Importing this package does not import Qt, so `main` can explain what is
missing instead of failing with a traceback.
"""

import argparse
import sys
from collections.abc import Sequence

from .. import __version__

INSTALL_HINT = (
    "The desktop app needs PySide6. Install it with:\n"
    "    pip install 'subtitlemaker[gui]'"
)


def _build_parser() -> argparse.ArgumentParser:

    parser = argparse.ArgumentParser(
        prog="subtitlemaker-gui",
        description=(
            "The SubtitleMaker desktop app. Other arguments (such as Qt's own "
            "-platform) are passed on to Qt."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "--self-check",
        action="store_true",
        help=(
            "Check that everything the app needs is present and works, print one "
            "line per check, and exit (0 if all passed). For a packaged app."
        ),
    )

    parser.add_argument(
        "--audio",
        metavar="FILE",
        help="With --self-check: also transcribe this short clip, to check the whole path",
    )

    parser.add_argument(
        "--model",
        metavar="NAME",
        default="tiny",
        help="With --self-check --audio: the model to use (default: tiny)",
    )

    parser.add_argument(
        "--report",
        metavar="FILE",
        help=(
            "With --self-check: also write the report to this file "
            "(a windowed app has no console)"
        ),
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point of `subtitlemaker-gui`: open the window, return the exit code."""

    args, qt_arguments = _build_parser().parse_known_args(
        sys.argv[1:] if argv is None else list(argv)
    )

    try:
        import PySide6  # noqa: F401

    except ImportError:
        print(INSTALL_HINT, file=sys.stderr)
        return 1

    if args.self_check:
        from .selfcheck import run_self_check

        return run_self_check(audio=args.audio, model=args.model, report=args.report)

    from .app import run

    return run([sys.argv[0], *qt_arguments])
