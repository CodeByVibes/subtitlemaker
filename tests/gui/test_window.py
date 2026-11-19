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


# --- the tabs and the layout ------------------------------------------------------------


def test_the_window_has_a_queue_tab_and_a_settings_tab(make_window):
    window = make_window()

    assert [window.tabs.tabText(i) for i in range(window.tabs.count())] == ["Queue", "Settings"]
    assert window.tabs.widget(0) is window.panel
    assert window.settings_panel.parent() is not None  # inside the scroll area of the second tab
    assert window.tabs.currentIndex() == 0  # the queue is what you see first


def test_the_settings_tab_is_marked_while_the_form_cannot_run(make_window):
    window = make_window(use_panel=True)
    assert window.tabs.tabText(1) == "Settings"

    window.settings_panel.widget("language").setText("xx")

    assert window.tabs.tabText(1) == "Settings ⚠"
    assert "unknown language code" in window.tabs.tabToolTip(1)

    window.settings_panel.widget("language").setText("sv")

    assert window.tabs.tabText(1) == "Settings"
    assert window.tabs.tabToolTip(1) == ""


def test_a_broken_config_file_marks_the_settings_tab_from_the_start(make_window, tmp_path):
    folder = tmp_path / "xdg-config" / "subtitlemaker"
    folder.mkdir(parents=True)
    (folder / "config.toml").write_text("[style]\nmax_lines = 3\n")

    window = make_window(use_panel=True)

    assert window.tabs.tabText(1) == "Settings ⚠"
    assert "max_lines must be 1 or 2" in window.tabs.tabToolTip(1)


NARROW = 560  # a tiling window manager can easily hand out half a laptop screen


def test_each_screen_fits_a_narrow_window(make_window):
    window = make_window()
    window.settings_panel.style_section.toggle.click()
    window.settings_panel.advanced_section.toggle.click()

    assert window.panel.minimumSizeHint().width() <= NARROW
    assert window.settings_panel.minimumSizeHint().width() <= NARROW
    assert window.minimumSizeHint().width() <= NARROW


def test_no_queue_control_is_squeezed_in_a_narrow_window(make_window, qtbot):
    window = make_window()
    window.resize(NARROW, 700)
    window.show()
    qtbot.waitExposed(window)
    QApplication.processEvents()

    panel = window.panel
    controls = [
        panel.add_files_button,
        panel.add_folder_button,
        panel.recursive_check,
        panel.up_button,
        panel.down_button,
        panel.requeue_button,
        panel.remove_button,
        panel.clear_button,
        panel.next_to_radio,
        panel.folder_radio,
        panel.folder_button,
        panel.skip_existing_check,
        panel.cancel_button,
        panel.start_button,
    ]

    for control in controls:
        inside = control.mapTo(panel, control.rect().topLeft()).x() + control.width()

        assert control.width() >= control.sizeHint().width(), control.text()  # not squeezed
        assert inside <= panel.width(), control.text()  # not pushed out of view
