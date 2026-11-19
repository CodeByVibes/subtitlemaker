"""Starting the application."""

import sys
from collections.abc import Sequence

from PySide6.QtCore import QSettings
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from .. import __version__
from .main_window import MainWindow

APP_NAME = "SubtitleMaker"


def run(argv: Sequence[str] | None = None) -> int:
    """Show the main window and run until it is closed. Returns the exit code."""

    app = QApplication.instance() or QApplication(list(sys.argv if argv is None else argv))

    # These name the settings file: ~/.config/subtitlemaker/SubtitleMaker.conf
    app.setOrganizationName("subtitlemaker")
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(__version__)

    # On Wayland this is the app id, which is how a desktop matches the
    # window to its icon and launcher entry.
    QGuiApplication.setDesktopFileName("subtitlemaker")

    window = MainWindow(store=QSettings())
    window.show()

    return app.exec()
