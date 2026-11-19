"""Qt tests run without a display: no window ever appears on the developer's screen."""

import os

# Assigned, not `setdefault`: a desktop session often exports its own
# QT_QPA_PLATFORM (e.g. "wayland;xcb"), and the tests must not open real windows.
os.environ["QT_QPA_PLATFORM"] = "offscreen"


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_user_config(tmp_path, monkeypatch):
    """The app reads ~/.config/subtitlemaker/config.toml and writes its own settings file
    there; tests get an empty folder instead, so they depend on and change nothing real."""

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))


from types import SimpleNamespace  # noqa: E402, F401

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from subtitlemaker.gui.main_window import MainWindow  # noqa: E402
from subtitlemaker.settings import resolve_settings  # noqa: E402


@pytest.fixture
def warnings(monkeypatch):
    """Warning dialogs are recorded as `(title, text)`, not shown."""

    shown = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        staticmethod(lambda parent, title, text, *a, **k: shown.append((title, text))),
    )

    return shown


@pytest.fixture
def make_window(qtbot, fake_model, monkeypatch):
    """Makes main windows and stops their worker threads when the test ends.

    The fixture holds the windows itself: pytest-qt only keeps weak references,
    so a window that lives in a test's local variable is gone (and never closed)
    by the time pytest-qt looks.
    """

    windows = []

    # A modal "Quit?" question would block forever without a display; if a test fails
    # while files are running, pytest-qt closes the window and that question appears.
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )

    def make(bridge=None, settings_provider=None, store=None, use_panel=False):
        """`use_panel`: run with the settings panel's values (the real behaviour);
        otherwise settings come from `settings_provider`, by default a tiny model."""

        if not use_panel and settings_provider is None:

            def settings_provider():
                return resolve_settings(model={"name": "tiny"})

        window = MainWindow(
            bridge=bridge,
            settings_provider=None if use_panel else settings_provider,
            store=store,
        )
        qtbot.addWidget(window)
        windows.append(window)

        return window

    yield make

    for window in windows:
        window.bridge.shutdown()
        window.prober.shutdown()
        window.log_pane.detach()


import logging  # noqa: E402


@pytest.fixture(autouse=True)
def restore_logging():
    """A window leaves a log handler and a raised log level behind unless it is closed,
    and pytest-qt does not deliver close events: put the library's logger back after
    every test so one test cannot change what the next one sees."""

    logger = logging.getLogger("subtitlemaker")
    handlers = list(logger.handlers)
    level = logger.level
    whisper_level = logging.getLogger("faster_whisper").level

    yield

    logger.handlers[:] = handlers
    logger.setLevel(level)
    logging.getLogger("faster_whisper").setLevel(whisper_level)
