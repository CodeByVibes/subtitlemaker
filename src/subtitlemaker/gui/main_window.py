"""The main window."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QLabel, QMainWindow

from .. import __version__

ICON_PATH = Path(__file__).parent / "resources" / "icon.svg"


class MainWindow(QMainWindow):
    """The one window of the app."""

    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle(f"SubtitleMaker {__version__}")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(900, 600)

        placeholder = QLabel("SubtitleMaker")
        placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.setCentralWidget(placeholder)
