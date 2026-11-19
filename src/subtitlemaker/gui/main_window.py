"""The main window."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QMainWindow, QMessageBox

from .. import __version__
from ..settings import Settings, resolve_settings
from .bridge import RunnerBridge
from .probe import DurationProber
from .queue_panel import QueuePanel

ICON_PATH = Path(__file__).parent / "resources" / "icon.svg"


class MainWindow(QMainWindow):
    """The one window of the app."""

    def __init__(
        self,
        bridge: RunnerBridge | None = None,
        settings_provider: Callable[[], Settings] | None = None,
        prober: DurationProber | None = None,
    ) -> None:
        super().__init__()

        self.setWindowTitle(f"SubtitleMaker {__version__}")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(900, 600)

        self.bridge = bridge or RunnerBridge(self)
        self.prober = prober or DurationProber(self)

        self.panel = QueuePanel(
            self.bridge, self.prober, settings_provider or resolve_settings, self
        )

        self.setCentralWidget(self.panel)

    def closeEvent(self, event: QCloseEvent) -> None:

        if self.panel.is_busy() and not self._confirm_quit():
            event.ignore()
            return

        # Stops the worker thread. A model that is still loading cannot be
        # interrupted, so this can take a moment.
        self.bridge.cancel_all()
        self.bridge.shutdown()
        self.prober.shutdown()

        event.accept()

    def _confirm_quit(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Quit SubtitleMaker?",
            "Files are still being transcribed. Quit and cancel them?",
        )

        return answer == QMessageBox.StandardButton.Yes
