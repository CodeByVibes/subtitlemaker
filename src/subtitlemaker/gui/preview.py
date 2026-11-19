"""The subtitle preview: the cues of a finished file, rebuilt live as the style changes.

The transcript is kept, so trying another style does not run the model again:
building the cues takes a few milliseconds.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from .._types import Cue
from ..config import ConfigError, SubtitleStyle
from ..formats import FORMATS
from ..formats._timestamp import format_timestamp
from ..pipeline import FileResult
from .style_form import StyleForm

COLUMNS = ("#", "Start", "End", "Chars/s", "Text")
COL_NUMBER, COL_START, COL_END, COL_SPEED, COL_TEXT = range(5)

# How long to wait after the last edit before building the cues again.
REBUILD_DELAY_MS = 150

_NO_PARENT = QModelIndex()

# Shows where a line breaks inside a cue.
LINE_BREAK = " ↵ "


class CueModel(QAbstractTableModel):
    """The cues as a table."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)

        self._cues: list[Cue] = []

    def set_cues(self, cues: Sequence[Cue]) -> None:
        self.beginResetModel()
        self._cues = list(cues)
        self.endResetModel()

    def cues(self) -> list[Cue]:
        return list(self._cues)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self._cues)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _NO_PARENT) -> int:
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]

        return None

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._cues):
            return None

        cue = self._cues[index.row()]
        column = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if column == COL_NUMBER:
                return index.row() + 1

            if column == COL_START:
                return format_timestamp(cue["start"], ".")

            if column == COL_END:
                return format_timestamp(cue["end"], ".")

            if column == COL_SPEED:
                return f"{characters_per_second(cue):.1f}"

            return cue["text"].replace("\n", LINE_BREAK)

        if role == Qt.ItemDataRole.ToolTipRole and column == COL_TEXT:
            return cue["text"]

        if role == Qt.ItemDataRole.TextAlignmentRole and column != COL_TEXT:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None


def characters_per_second(cue: Cue) -> float:
    """How fast a cue has to be read: its characters (not line breaks) per second on screen."""

    duration = cue["end"] - cue["start"]
    characters = len(cue["text"].replace("\n", ""))

    return characters / duration if duration > 0 else 0.0


class CuePreviewDialog(QDialog):
    """Shows a file's subtitles, and rebuilds them as the style is edited."""

    # The style the user wants to keep for new files ("Use this style for new files").
    style_chosen = Signal(object)

    def __init__(
        self,
        result: FileResult,
        help_text: Mapping[str, str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        # Not `result`: that would hide QDialog.result(), the dialog's exit code.
        self.file_result = result
        self._cues: list[Cue] = list(result.subtitles)
        self._problem = ""

        self.setWindowTitle(f"Subtitles of {result.input_file.name}")
        self.resize(1000, 600)

        self.model = CueModel(self)
        self.model.set_cues(self._cues)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_TEXT, QHeaderView.ResizeMode.Stretch)

        self.style_form = StyleForm(help_text)
        self.style_form.write_style(result.style)
        self.style_form.edited.connect(self._schedule_rebuild)

        self.summary = QLabel()
        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #ef4444;")
        self.error_label.hide()
        self.status = QLabel()
        self.status.setWordWrap(True)

        self.reset_button = QPushButton("Back to the style used")
        self.keep_button = QPushButton("Use this style for new files")
        self.save_button = QPushButton("Save")
        self.close_button = QPushButton("Close")

        self.reset_button.clicked.connect(self.reset_style)
        self.keep_button.clicked.connect(self.keep_style)
        self.save_button.clicked.connect(self.save)
        self.close_button.clicked.connect(self.close)

        side = QVBoxLayout()
        side.addWidget(QLabel("<b>Subtitle style</b>"))
        side.addWidget(self.style_form)
        side.addWidget(self.error_label)
        side.addWidget(self.reset_button)
        side.addWidget(self.keep_button)
        side.addStretch(1)

        side_widget = QWidget()
        side_widget.setLayout(side)
        self.side_scroll = QScrollArea()
        self.side_scroll.setWidget(side_widget)
        self.side_scroll.setWidgetResizable(True)
        self.side_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        # Wide enough for the form (plus a vertical scroll bar), so it is never clipped.
        bar = self.side_scroll.verticalScrollBar().sizeHint().width()
        side_width = side_widget.sizeHint().width() + bar + 8
        self.side_scroll.setMinimumWidth(side_width)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.table)
        splitter.addWidget(self.side_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([self.width() - side_width - 40, side_width])

        buttons = QHBoxLayout()
        buttons.addWidget(self.status, 1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)

        # Typing in a box fires on every keystroke; build once things settle.
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REBUILD_DELAY_MS)
        self._timer.timeout.connect(self.rebuild)

        self._update_summary()

    # --- what the dialog holds ------------------------------------------------------------

    def cues(self) -> list[Cue]:
        """The cues as currently shown."""

        return list(self._cues)

    def current_style(self) -> SubtitleStyle:
        """The style in the form. Raises `ConfigError` if its values contradict each other."""

        return self.style_form.read_style()

    # --- rebuilding ---------------------------------------------------------------------------

    def _schedule_rebuild(self) -> None:
        self._timer.start()

    def flush(self) -> None:
        """Build the cues now if an edit is still waiting for its delay to pass."""

        if self._timer.isActive():
            self._timer.stop()
            self.rebuild()

    def rebuild(self) -> None:
        """Build the cues again with the style in the form."""

        try:
            style = self.current_style()

        except ConfigError as e:
            # Keep showing the last good cues, and say what is wrong.
            self._problem = str(e)
            self.error_label.setText(self._problem)
            self.error_label.show()
            self.save_button.setEnabled(False)

            return

        self._problem = ""
        self.error_label.hide()
        self.save_button.setEnabled(True)

        self._cues = self.file_result.rebuild(style)
        self.model.set_cues(self._cues)
        self.status.setText("")
        self._update_summary()

    def reset_style(self) -> None:
        """Back to the style the run used."""

        self.style_form.write_style(self.file_result.style)
        self._timer.stop()
        self.rebuild()

    def keep_style(self) -> None:
        """Offer the style in the form for new files."""

        # The form already holds any edit that is still waiting for its delay.
        try:
            style = self.current_style()

        except ConfigError:
            return

        self.style_chosen.emit(style)
        self.status.setText("This style will be used for new files.")

    def _update_summary(self) -> None:
        count = len(self._cues)
        original = len(self.file_result.subtitles)
        text = f"{count} subtitle{'s' if count != 1 else ''}"

        if self._cues != self.file_result.subtitles:
            text += f" (the run made {original})"

        if self._cues:
            fastest = max(characters_per_second(cue) for cue in self._cues)
            text += f" · fastest {fastest:.1f} characters/s"

        self.summary.setText(text)

    # --- saving ---------------------------------------------------------------------------------

    def save(self) -> bool:
        """Replace the file's subtitle files with the cues shown. True if they were written."""

        self.flush()

        if self._problem:
            return False

        paths = self.file_result.outputs

        listing = "\n".join(str(path) for path in paths.values())
        answer = QMessageBox.question(
            self,
            "Replace the subtitle files?",
            f"Write these {len(self._cues)} subtitles over:\n\n{listing}",
        )

        if answer != QMessageBox.StandardButton.Yes:
            return False

        try:
            for name, path in paths.items():
                FORMATS[name].write(self._cues, path)

        except OSError as e:
            QMessageBox.warning(self, "Couldn't save", f"{e.filename or ''}: {e.strerror or e}")

            return False

        self.status.setText(f"Saved {len(self._cues)} subtitles.")

        return True
