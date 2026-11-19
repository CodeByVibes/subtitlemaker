"""The main window and the application start-up (offscreen)."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import subtitlemaker  # noqa: E402
from subtitlemaker.gui.app import run  # noqa: E402
from subtitlemaker.gui.main_window import ICON_PATH, MainWindow  # noqa: E402


def test_tests_never_open_real_windows(qtbot):
    # A desktop session may export QT_QPA_PLATFORM=wayland;xcb; the tests must not follow it.
    assert QGuiApplication.platformName() == "offscreen"


def test_the_window_title_names_the_app_and_its_version(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.windowTitle() == f"SubtitleMaker {subtitlemaker.__version__}"


def test_the_window_has_an_icon_that_renders(qtbot):
    assert ICON_PATH.is_file()

    window = MainWindow()
    qtbot.addWidget(window)

    icon = window.windowIcon()

    assert not icon.isNull()
    assert not icon.pixmap(64, 64).isNull()  # the SVG really draws (needs the SVG plugin)


def test_the_window_can_be_shown_and_closed(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    window.show()
    assert window.isVisible()

    window.close()
    assert not window.isVisible()


def test_run_shows_the_window_and_returns_the_exit_code(qtbot, monkeypatch):
    shown = []

    monkeypatch.setattr(QApplication, "exec", staticmethod(lambda: 7))
    monkeypatch.setattr(MainWindow, "show", lambda self: shown.append(self))

    assert run([]) == 7
    assert len(shown) == 1

    app = QApplication.instance()
    assert app.applicationName() == "SubtitleMaker"
    assert app.applicationVersion() == subtitlemaker.__version__
    assert QGuiApplication.desktopFileName() == "subtitlemaker"  # the Wayland app id
