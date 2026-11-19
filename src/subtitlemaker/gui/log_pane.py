"""The log tab: what the library writes while it works, as it happens.

The command line prints these messages to the terminal; the app shows them
here. They are produced on the worker thread, so the handler hands each one
over to the Qt thread through a signal.
"""

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..log import LOGGER_NAME, format_record

# The most lines kept; the oldest go first.
MAX_LINES = 5000

# Colours that read on both a light and a dark theme.
_WARNING_COLOUR = "#d97706"
_ERROR_COLOUR = "#ef4444"


class _Lines(QObject):
    """Carries log lines from any thread to the Qt thread."""

    line = Signal(int, str)  # level, text


class QtLogHandler(logging.Handler):
    """Passes each record on as a Qt signal. Safe to call from any thread."""

    def __init__(self, lines: _Lines) -> None:
        super().__init__()
        self._lines = lines
        self.setLevel(logging.DEBUG)

    def emit(self, record: logging.LogRecord) -> None:

        try:
            self._lines.line.emit(record.levelno, format_record(record))

        except RuntimeError:
            # The pane was deleted under us: stop logging to it.
            logging.getLogger(LOGGER_NAME).removeHandler(self)

        except Exception:
            self.handleError(record)


class LogPane(QWidget):
    """A read-only log with Copy, Save, Clear and a switch for more detail."""

    # Emitted for each warning or error, so the window can point at the tab.
    attention = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._lines = _Lines(self)
        self._lines.line.connect(self._add)

        self._handler: QtLogHandler | None = None
        self._previous_level = logging.NOTSET

        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(MAX_LINES)
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self.details_check = QCheckBox("Show details")
        self.details_check.setToolTip("Also show debug messages, like the command line's -v.")
        self.details_check.toggled.connect(self._apply_level)

        self.copy_button = QPushButton("Copy")
        self.save_button = QPushButton("Save…")
        self.clear_button = QPushButton("Clear")

        self.copy_button.clicked.connect(self.copy)
        self.save_button.clicked.connect(self.save)
        self.clear_button.clicked.connect(self.text.clear)

        row = QHBoxLayout()
        row.addWidget(self.details_check)
        row.addStretch(1)

        for button in (self.copy_button, self.save_button, self.clear_button):
            row.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addLayout(row)
        layout.addWidget(self.text, 1)

    # --- connecting to the library's log -------------------------------------------

    def attach(self) -> None:
        """Start showing the library's messages. Does nothing if already attached."""

        if self._handler is not None:
            return

        logger = logging.getLogger(LOGGER_NAME)

        self._handler = QtLogHandler(self._lines)
        self._previous_level = logger.level
        logger.addHandler(self._handler)

        self._apply_level()

    def detach(self) -> None:
        """Stop showing them and put the logger's level back as it was."""

        if self._handler is None:
            return

        logger = logging.getLogger(LOGGER_NAME)
        logger.removeHandler(self._handler)
        logger.setLevel(self._previous_level)

        self._handler = None

    def is_attached(self) -> bool:
        return self._handler is not None

    def _apply_level(self, *_: object) -> None:
        """INFO normally; DEBUG (and faster-whisper's own log) with "Show details"."""

        if self._handler is None:
            return

        detailed = self.details_check.isChecked()

        logging.getLogger(LOGGER_NAME).setLevel(logging.DEBUG if detailed else logging.INFO)
        logging.getLogger("faster_whisper").setLevel(logging.DEBUG if detailed else logging.NOTSET)

    # --- the text ---------------------------------------------------------------------------

    def _add(self, level: int, text: str) -> None:

        if level >= logging.ERROR:
            self._append(text, _ERROR_COLOUR)
            self.attention.emit()

        elif level >= logging.WARNING:
            self._append(text, _WARNING_COLOUR)
            self.attention.emit()

        else:
            self._append(text, None)

    def _append(self, text: str, colour: str | None) -> None:
        """Add `text` as a new line, exactly as it is (the command line aligns its columns)."""

        bar = self.text.verticalScrollBar()
        at_bottom = bar.value() >= bar.maximum() - 2

        fmt = QTextCharFormat()

        if colour:
            fmt.setForeground(QColor(colour))

        cursor = QTextCursor(self.text.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)

        if not self.text.document().isEmpty():
            cursor.insertBlock()

        cursor.insertText(text, fmt)

        # Follow the newest line, unless the user has scrolled up to read.
        if at_bottom:
            bar.setValue(bar.maximum())

    def plain_text(self) -> str:
        return self.text.toPlainText()

    def copy(self) -> None:
        """Put the whole log on the clipboard."""

        QApplication.clipboard().setText(self.plain_text())

    def save(self) -> None:
        """Write the log to a file the user picks."""

        name, _ = QFileDialog.getSaveFileName(self, "Save log", "subtitlemaker-log.txt")

        if not name:
            return

        try:
            Path(name).write_text(self.plain_text() + "\n", encoding="utf-8")

        except OSError as e:
            QMessageBox.warning(self, "Couldn't save the log", f"{name}: {e.strerror or e}")
