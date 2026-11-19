"""The table showing the file list, and what it needs beyond a plain table."""

from pathlib import Path
from typing import Any

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSize, Signal
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionProgressBar,
    QStyleOptionViewItem,
    QTableView,
    QWidget,
)

from .queue_model import COL_DURATION, COL_FILE, COL_PROGRESS, COL_STATUS, PROGRESS_ROLE


class ProgressDelegate(QStyledItemDelegate):
    """Draws a progress bar in the cell of a running file, plain text otherwise."""

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        fraction = index.data(PROGRESS_ROLE)

        if fraction is None:
            super().paint(painter, option, index)
            return

        bar = QStyleOptionProgressBar()
        bar.rect = option.rect.adjusted(2, 3, -2, -3)
        bar.minimum = 0
        bar.maximum = 100
        bar.progress = round(fraction * 100)
        bar.text = f"{bar.progress}%"
        bar.textVisible = True

        style = option.widget.style() if option.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ProgressBar, bar, painter, option.widget)

    def sizeHint(
        self, option: QStyleOptionViewItem, index: QModelIndex | QPersistentModelIndex
    ) -> QSize:
        return super().sizeHint(option, index).expandedTo(QSize(120, 22))


class FileQueueView(QTableView):
    """The file table. Files and folders can be dropped on it."""

    # Local paths of everything dropped (files and folders).
    paths_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.setAcceptDrops(True)
        self.setItemDelegateForColumn(COL_PROGRESS, ProgressDelegate(self))

    def setModel(self, model: Any) -> None:
        super().setModel(model)

        header = self.horizontalHeader()
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_DURATION, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_PROGRESS, QHeaderView.ResizeMode.Fixed)
        header.resizeSection(COL_PROGRESS, 140)

    def selected_rows(self) -> list[int]:
        """The selected rows, top to bottom."""

        selection = self.selectionModel()

        if selection is None:
            return []

        return sorted({index.row() for index in selection.selectedRows()})

    # --- dropping files from the file manager --------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:

        if event.mimeData().hasUrls():
            event.acceptProposedAction()

        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:

        if event.mimeData().hasUrls():
            event.acceptProposedAction()

        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:

        paths = [
            Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()
        ]

        if not paths:
            event.ignore()
            return

        event.acceptProposedAction()
        self.paths_dropped.emit(paths)
