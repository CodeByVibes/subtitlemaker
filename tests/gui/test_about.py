"""The About box, and how it is opened."""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QEvent, QSettings, Qt  # noqa: E402
from PySide6.QtGui import QShortcut  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolButton  # noqa: E402

import subtitlemaker  # noqa: E402
from subtitlemaker.gui.about import AboutDialog  # noqa: E402
from subtitlemaker.gui.about_info import CHANGELOG, CREDITS, DESCRIPTION, HOMEPAGE, ISSUES  # noqa: E402

WAIT = 5000  # ms


@pytest.fixture
def dialog(qtbot):
    dialog = AboutDialog(None)
    qtbot.addWidget(dialog)

    return dialog


# --- the dialog -------------------------------------------------------------------------------


def test_it_names_the_app_and_its_version(dialog):
    assert f"SubtitleMaker {subtitlemaker.__version__}" in dialog.title_label.text()
    assert dialog.windowTitle() == "About SubtitleMaker"
    assert dialog.description_label.text() == DESCRIPTION


def test_the_links_open_in_the_browser(dialog):
    text = dialog.links_label.text()

    for address in (HOMEPAGE, ISSUES, CHANGELOG):
        assert f'href="{address}"' in text

    assert dialog.links_label.openExternalLinks()
    assert dialog.credits_label.openExternalLinks()


def test_it_credits_what_it_is_built_on(dialog):
    text = dialog.credits_label.text()

    for name, address, licence in CREDITS:
        assert f'<a href="{address}">{name}</a> ({licence})' in text

    assert "MIT licence" in dialog.licence_label.text()


def test_the_details_describe_this_installation(dialog):
    import PySide6

    details = dialog.details.toPlainText()

    assert details.startswith(f"SubtitleMaker {subtitlemaker.__version__}\n")
    assert f"PySide6 {PySide6.__version__}" in details
    assert "platform offscreen" in details  # what the tests run on, reported as it is
    assert "Device: " in details and "Config file: " in details
    assert "Settings file" not in details  # none was given


def test_long_lines_of_the_details_wrap_instead_of_hiding(dialog, qtbot):
    from PySide6.QtWidgets import QPlainTextEdit

    dialog.show()
    qtbot.waitExposed(dialog)

    assert dialog.details.lineWrapMode() == QPlainTextEdit.LineWrapMode.WidgetWidth
    assert dialog.details.horizontalScrollBar().maximum() == 0  # nothing to scroll sideways


def test_the_details_cannot_be_edited_by_accident(dialog):
    assert dialog.details.isReadOnly()


def test_the_settings_file_is_in_the_details_when_there_is_one(qtbot, tmp_path):
    dialog = AboutDialog(tmp_path / "SubtitleMaker.conf")
    qtbot.addWidget(dialog)

    assert f"Settings file: {tmp_path}/SubtitleMaker.conf" in dialog.details.toPlainText()


def test_copy_puts_the_details_on_the_clipboard(dialog):
    QApplication.clipboard().setText("something else")

    dialog.copy_button.click()

    assert QApplication.clipboard().text() == dialog.details.toPlainText()
    assert QApplication.clipboard().text().startswith("SubtitleMaker ")


def test_the_details_do_not_contain_the_home_folder(qtbot, tmp_path, monkeypatch):
    home = tmp_path / "people" / "alice"
    (home / ".config").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))

    dialog = AboutDialog(home / ".config" / "subtitlemaker" / "SubtitleMaker.conf")
    qtbot.addWidget(dialog)

    details = dialog.details.toPlainText()

    assert "alice" not in details
    assert "Config file: ~/.config/subtitlemaker/config.toml" in details
    assert "Settings file: ~/.config/subtitlemaker/SubtitleMaker.conf" in details


def test_close_closes_it(dialog, qtbot):
    dialog.show()
    qtbot.waitExposed(dialog)

    dialog.close_button.click()

    assert not dialog.isVisible()


# --- opening it from the window ---------------------------------------------------------------


def test_the_about_button_sits_in_the_corner_of_the_tab_bar(make_window):
    window = make_window()
    corner = window.tabs.cornerWidget(Qt.Corner.TopRightCorner)

    assert corner is window.about_button
    assert isinstance(corner, QToolButton) and corner.text() == "About"
    assert "F1" in corner.toolTip()


def test_the_button_opens_the_about_box(make_window, qtbot):
    window = make_window()
    assert window.findChildren(AboutDialog) == []  # nothing yet

    window.about_button.click()  # and only the click: nothing else asks for the dialog

    (dialog,) = window.findChildren(AboutDialog)
    qtbot.waitExposed(dialog)

    assert dialog.isVisible()
    assert dialog.parent() is window


def test_asking_twice_does_not_open_two(make_window):
    window = make_window()

    first = window.show_about()
    second = window.show_about()

    assert second is first


def test_a_closed_about_box_can_be_opened_again(make_window, qtbot):
    window = make_window()
    first = window.show_about()

    first.close()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtbot.waitUntil(lambda: window._about is None, timeout=WAIT)

    again = window.show_about()

    assert again is not first and again.isVisible()


def test_f1_opens_the_about_box(make_window, qtbot):
    window = make_window()
    window.show()
    qtbot.waitExposed(window)

    shortcuts = [s for s in window.findChildren(QShortcut) if s.key().toString() == "F1"]
    assert len(shortcuts) == 1  # the help key is the one that opens it

    shortcuts[0].activated.emit()

    assert window._about is not None and window._about.isVisible()


def test_the_window_gives_the_dialog_the_settings_file_of_its_store(make_window, tmp_path):
    store = QSettings(str(tmp_path / "kept.ini"), QSettings.Format.IniFormat)
    window = make_window(store=store)

    dialog = window.show_about()

    assert f"Settings file: {tmp_path}/kept.ini" in dialog.details.toPlainText()


def test_without_a_store_there_is_no_settings_file_to_report(make_window):
    window = make_window()

    assert "Settings file" not in window.show_about().details.toPlainText()


def test_closing_the_window_closes_the_about_box(make_window, qtbot):
    window = make_window()
    window.show()
    qtbot.waitExposed(window)
    dialog = window.show_about()
    qtbot.waitExposed(dialog)

    window.close()

    assert not dialog.isVisible()


def test_the_tab_bar_still_fits_a_narrow_window(make_window):
    window = make_window()

    assert window.minimumSizeHint().width() <= 560  # the button costs no meaningful width
