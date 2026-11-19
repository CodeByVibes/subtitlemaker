"""The list of files to transcribe, as a Qt table model.

Holds what the window shows (files, their status, progress) and the rules
for changing it. It starts no work itself: the panel feeds it runner events.
"""

import dataclasses
import enum
import time
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt

from ..pipeline import FileResult
from ..planning import expand_inputs

# `index.data(PROGRESS_ROLE)`: 0.0 to 1.0 for a running file, `None` otherwise.
PROGRESS_ROLE = Qt.ItemDataRole.UserRole + 1
# `index.data(ITEM_ROLE)`: the `QueueItem` of the row.
ITEM_ROLE = Qt.ItemDataRole.UserRole + 2

# The "no parent" index every top-level call uses (a default argument cannot call `QModelIndex()`).
_NO_PARENT = QModelIndex()

COLUMNS = ("File", "Duration", "Status", "Progress")
COL_FILE, COL_DURATION, COL_STATUS, COL_PROGRESS = range(4)


class Status(enum.Enum):
    QUEUED = "Queued"  # waiting for the user to press Start
    WAITING = "Waiting"  # handed to the runner, not started yet
    RUNNING = "Running"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    SKIPPED = "Skipped"  # its output exists already


# A file in these states belongs to the runner and cannot be edited.
LOCKED = frozenset({Status.WAITING, Status.RUNNING})


@dataclasses.dataclass
class QueueItem:
    """One file in the list."""

    path: Path
    status: Status = Status.QUEUED
    duration: float = 0.0  # seconds of media, 0.0 while unknown
    position: float = 0.0  # seconds transcribed so far
    message: str = ""  # why it failed, or its warnings
    outputs: dict[str, Path] = dataclasses.field(default_factory=dict)
    started_at: float | None = None  # clock reading at the first progress report
    result: FileResult | None = None  # what the run produced (the transcript), once done

    @property
    def fraction(self) -> float | None:
        """How much is done (0.0 to 1.0), or `None` if that cannot be told."""

        if self.status is Status.DONE:
            return 1.0

        if self.status is not Status.RUNNING or self.duration <= 0:
            return None

        return min(1.0, max(0.0, self.position / self.duration))


@dataclasses.dataclass(frozen=True)
class AddResult:
    """What `QueueModel.add_paths` did."""

    added: list[Path]
    duplicates: int  # already in the list
    problems: list[str]  # inputs that do not exist or cannot be read


class QueueModel(QAbstractTableModel):
    """The files, one per row."""

    def __init__(
        self,
        parent: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)

        self._items: list[QueueItem] = []
        self._clock = clock

    # --- Qt model interface ------------------------------------------------------

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _NO_PARENT) -> int:
        return 0 if parent.isValid() else len(self._items)

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
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None

        item = self._items[index.row()]
        column = index.column()

        if role == ITEM_ROLE:
            return item

        if role == PROGRESS_ROLE:
            return item.fraction if item.status is Status.RUNNING else None

        if role == Qt.ItemDataRole.DisplayRole:

            if column == COL_FILE:
                return item.path.name

            if column == COL_DURATION:
                return format_duration(item.duration) if item.duration > 0 else ""

            if column == COL_STATUS:
                return status_text(item)

            if column == COL_PROGRESS and item.fraction is not None:
                return f"{round(item.fraction * 100)}%"

            return ""

        if role == Qt.ItemDataRole.ToolTipRole:

            if column == COL_FILE:
                return str(item.path)

            if column == COL_STATUS and item.message:
                return item.message

            return None

        if role == Qt.ItemDataRole.TextAlignmentRole and column in (COL_DURATION, COL_PROGRESS):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        return None

    # --- the list ----------------------------------------------------------------

    def items(self) -> list[QueueItem]:
        return list(self._items)

    def item(self, row: int) -> QueueItem:
        return self._items[row]

    def row_of(self, path: Path) -> int | None:
        """The row of `path`, or `None` if it is not in the list."""

        key = _key(path)

        for row, item in enumerate(self._items):
            if _key(item.path) == key:
                return row

        return None

    def count(self, *statuses: Status) -> int:
        """How many files are in any of `statuses` (all of them if none given)."""

        if not statuses:
            return len(self._items)

        return sum(1 for item in self._items if item.status in statuses)

    def add_paths(self, paths: Iterable[str | Path], recursive: bool = False) -> AddResult:
        """
        Add files, and the media files in folders, that are not in the list yet.

        Folders are scanned (with their sub folders if `recursive`).
        """

        found, problems = expand_inputs(list(paths), recursive)

        known = {_key(item.path) for item in self._items}
        added = []
        duplicates = 0

        for path in found:

            if _key(path) in known:
                duplicates += 1
                continue

            known.add(_key(path))
            added.append(path)

        if added:
            first = len(self._items)
            self.beginInsertRows(QModelIndex(), first, first + len(added) - 1)
            self._items.extend(QueueItem(path) for path in added)
            self.endInsertRows()

        return AddResult(added, duplicates, problems)

    def remove_rows(self, rows: Iterable[int]) -> int:
        """Remove the files in `rows` unless the runner has them. Returns how many went."""

        removable = sorted(
            {r for r in rows if 0 <= r < len(self._items) and self._items[r].status not in LOCKED},
            reverse=True,
        )

        for row in removable:
            self.beginRemoveRows(QModelIndex(), row, row)
            del self._items[row]
            self.endRemoveRows()

        return len(removable)

    def clear(self) -> int:
        """Remove every file the runner does not have. Returns how many went."""

        return self.remove_rows(range(len(self._items)))

    def move(self, row: int, delta: int) -> bool:
        """Move a file up (`delta` -1) or down (+1). False if it cannot move."""

        target = row + delta

        if not (0 <= row < len(self._items) and 0 <= target < len(self._items)):
            return False

        if self._items[row].status in LOCKED or self._items[target].status in LOCKED:
            return False

        # Qt's destination index counts the row's own slot when moving down.
        destination = target + 1 if delta > 0 else target

        if not self.beginMoveRows(QModelIndex(), row, row, QModelIndex(), destination):
            return False

        self._items[row], self._items[target] = self._items[target], self._items[row]
        self.endMoveRows()

        return True

    def requeue(self, rows: Iterable[int]) -> int:
        """Make finished, failed, cancelled or skipped files ready to run again."""

        count = 0

        for row in rows:

            if not 0 <= row < len(self._items):
                continue

            item = self._items[row]

            if item.status in (Status.DONE, Status.FAILED, Status.CANCELLED, Status.SKIPPED):
                item.status = Status.QUEUED
                item.position = 0.0
                item.message = ""
                item.started_at = None
                item.result = None
                self._changed(row)
                count += 1

        return count

    # --- what the runner reports ---------------------------------------------------

    def set_duration(self, path: Path, duration: float) -> None:
        row = self.row_of(path)

        if row is not None and duration > 0:
            self._items[row].duration = duration
            self._changed(row)

    def mark_waiting(self, path: Path, outputs: dict[str, Path]) -> None:
        self._update(
            path, status=Status.WAITING, outputs=outputs, position=0.0, message="", result=None
        )

    def mark_skipped(self, path: Path, outputs: dict[str, Path]) -> None:
        self._update(path, status=Status.SKIPPED, outputs=outputs, message="output exists")

    def on_started(self, path: Path) -> None:
        self._update(path, status=Status.RUNNING, position=0.0, started_at=None)

    def on_progress(self, path: Path, position: float, duration: float) -> None:
        row = self.row_of(path)

        if row is None:
            return

        item = self._items[row]

        if item.status is not Status.RUNNING:
            return

        if item.started_at is None:
            item.started_at = self._clock()

        item.position = position

        if duration > 0:
            item.duration = duration

        self._changed(row)

    def on_finished(
        self, path: Path, warnings: Sequence[str] = (), result: FileResult | None = None
    ) -> None:
        self._update(path, status=Status.DONE, message="; ".join(warnings), result=result)

    def on_failed(self, path: Path, message: str) -> None:
        self._update(path, status=Status.FAILED, message=message)

    def on_cancelled(self, path: Path) -> None:
        self._update(path, status=Status.CANCELLED, message="")

    # --- speed and time left ----------------------------------------------------------

    def speed(self, path: Path) -> float | None:
        """Seconds of media per second of real time for a running file, if known."""

        row = self.row_of(path)

        if row is None:
            return None

        item = self._items[row]

        if item.started_at is None:
            return None

        elapsed = self._clock() - item.started_at

        # Progress is only reported after a segment, so there is nothing to
        # measure until some time has passed and some of the file is done.
        if elapsed <= 0 or item.position <= 0:
            return None

        return item.position / elapsed

    def eta(self, path: Path) -> float | None:
        """Estimated seconds of real time left for a running file, if it can be told."""

        row = self.row_of(path)
        speed = self.speed(path)

        if row is None or not speed:
            return None

        item = self._items[row]

        if item.duration <= item.position:
            return 0.0

        return (item.duration - item.position) / speed

    # --- internals ---------------------------------------------------------------------

    def _update(self, path: Path, **changes: Any) -> None:
        row = self.row_of(path)

        if row is None:
            return

        for name, value in changes.items():
            setattr(self._items[row], name, value)

        self._changed(row)

    def _changed(self, row: int) -> None:
        self.dataChanged.emit(self.index(row, 0), self.index(row, len(COLUMNS) - 1))


def _key(path: Path) -> Path:
    """What makes two paths the same file."""

    try:
        return path.resolve()

    except OSError:
        return path.absolute()


def status_text(item: QueueItem) -> str:
    """The status column: the status, with a mark when there is something to read."""

    if item.status is Status.DONE and item.message:
        return f"{item.status.value} (warning)"

    return item.status.value


def format_duration(seconds: float) -> str:
    """`1:02:03` or `2:03`: how long a file is."""

    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)

    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"

    return f"{minutes}:{secs:02d}"
