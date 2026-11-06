"""Logging setup: messages and progress share one stderr console."""

import logging

from rich.console import Console

LOGGER_NAME = "subtitlemaker"


class _Formatter(logging.Formatter):
    """Plain messages, with a prefix for warnings and errors."""

    def format(self, record):
        message = record.getMessage()

        if record.levelno >= logging.ERROR:
            return f"Error: {message}"

        if record.levelno >= logging.WARNING:
            return f"Warning: {message}"

        return message


class _ConsoleHandler(logging.Handler):
    """
    Print records through a `rich` console.

    Going through the console keeps log lines and the live progress bar
    from overwriting each other. Markup, highlighting and emoji codes are
    off because file names may contain [brackets] or :colons:.
    """

    def __init__(self, console):
        super().__init__()
        self.console = console

    def emit(self, record):
        try:
            self.console.print(
                self.format(record),
                markup=False,
                highlight=False,
                emoji=False,
                soft_wrap=True,
            )

        except Exception:
            self.handleError(record)


def setup_logging(quiet=False, verbose=False):
    """
    Configure logging and return the shared `rich` console.

    Normal runs show INFO and above, `quiet` shows only warnings and
    errors, `verbose` adds DEBUG (including faster-whisper's own log).
    """

    console = Console(stderr=True)

    handler = _ConsoleHandler(console)

    handler.setFormatter(_Formatter())

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.WARNING)

    if quiet:
        level = logging.WARNING

    elif verbose:
        level = logging.DEBUG
        logging.getLogger("faster_whisper").setLevel(logging.DEBUG)

    else:
        level = logging.INFO

    logging.getLogger(LOGGER_NAME).setLevel(level)

    return console
