"""The main window."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QMainWindow, QMessageBox, QScrollArea, QTabWidget

from .. import __version__
from ..settings import Settings
from .bridge import RunnerBridge
from .log_pane import LogPane
from .probe import DurationProber
from .queue_panel import QueuePanel
from .settings_panel import SettingsPanel

ICON_PATH = Path(__file__).parent / "resources" / "icon.svg"
SETTINGS_TAB = "Settings"
LOG_TAB = "Log"


class MainWindow(QMainWindow):
    """The one window of the app."""

    def __init__(
        self,
        bridge: RunnerBridge | None = None,
        settings_provider: Callable[[], Settings] | None = None,
        prober: DurationProber | None = None,
        store: QSettings | None = None,
    ) -> None:
        """
        `store` keeps the settings between sessions (none: they are not kept).
        `settings_provider` replaces the settings panel as the source of a run's
        settings (for tests); normally the panel is used.
        """

        super().__init__()

        self.setWindowTitle(f"SubtitleMaker {__version__}")
        self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(900, 650)

        self.bridge = bridge or RunnerBridge(self)
        self.prober = prober or DurationProber(self)

        self.settings_panel = SettingsPanel(store)

        self.panel = QueuePanel(
            self.bridge,
            self.prober,
            settings_provider or self.settings_panel.settings,
            self,
        )

        # The settings scroll when the window is short.
        scroll = QScrollArea()
        scroll.setWidget(self.settings_panel)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        # Tabs rather than side by side: a window can be narrow (a tiling window
        # manager often makes it so), and each screen then gets the whole width.
        self.tabs = QTabWidget()
        self.tabs.addTab(self.panel, "Queue")
        self.tabs.addTab(scroll, SETTINGS_TAB)
        self.settings_panel.problem_changed.connect(self._show_settings_problem)
        self._show_settings_problem(self.settings_panel.error_label.text())

        self.log_pane = LogPane()
        self.log_pane.attach()
        self.tabs.addTab(self.log_pane, LOG_TAB)
        self.log_pane.attention.connect(self._point_at_log)
        self.tabs.currentChanged.connect(self._tab_changed)

        self.setCentralWidget(self.tabs)

    def _point_at_log(self) -> None:
        """A warning or error was logged: mark the Log tab unless it is the one being shown."""

        if self.tabs.currentWidget() is not self.log_pane:
            self.tabs.setTabText(2, f"{LOG_TAB} ●")

    def _tab_changed(self, index: int) -> None:

        if self.tabs.widget(index) is self.log_pane:
            self.tabs.setTabText(2, LOG_TAB)

    def _show_settings_problem(self, problem: str) -> None:
        """Mark the Settings tab when the form cannot be run as it is."""

        self.tabs.setTabText(1, f"{SETTINGS_TAB} ⚠" if problem else SETTINGS_TAB)
        self.tabs.setTabToolTip(1, problem)

    def closeEvent(self, event: QCloseEvent) -> None:

        if self.panel.is_busy() and not self._confirm_quit():
            event.ignore()
            return

        # Stops the worker thread. A model that is still loading cannot be
        # interrupted, so this can take a moment.
        self.bridge.cancel_all()
        self.bridge.shutdown()
        self.prober.shutdown()
        self.log_pane.detach()

        event.accept()

    def _confirm_quit(self) -> bool:
        answer = QMessageBox.question(
            self,
            "Quit SubtitleMaker?",
            "Files are still being transcribed. Quit and cancel them?",
        )

        return answer == QMessageBox.StandardButton.Yes
