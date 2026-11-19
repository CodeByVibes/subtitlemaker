"""The file queue screen: add files, start, watch progress, cancel."""

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPoint, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ..config import ConfigError
from ..media import MEDIA_EXTENSIONS
from ..pipeline import FileResult
from ..planning import plan_all_outputs
from ..progress import format_time
from ..runner import Job
from ..settings import Settings
from .bridge import RunnerBridge
from .probe import DurationProber
from .queue_model import LOCKED, QueueModel, Status
from .queue_view import FileQueueView

# How many problems (files that do not exist, ...) a message lists before "and N more".
_MAX_PROBLEMS_SHOWN = 5

_FINISHED = (Status.DONE, Status.FAILED, Status.CANCELLED, Status.SKIPPED)

# What Start runs. A cancelled file is picked up again, because that is what
# "Cancel, then Start" means; finished and failed ones need "Queue again", so
# Start never re-runs a file that is done or keeps retrying one that is broken.
_STARTABLE = (Status.QUEUED, Status.CANCELLED)


class QueuePanel(QWidget):
    """Lists the files to transcribe and runs them through a `RunnerBridge`."""

    def __init__(
        self,
        bridge: RunnerBridge,
        prober: DurationProber,
        settings_provider: Callable[[], Settings],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._bridge = bridge
        self._prober = prober
        self._settings_provider = settings_provider

        # Why the first file of this run failed, for the summary at the end.
        self._first_error = ""

        self.model = QueueModel(self)

        self._build()
        self._connect()
        self._update_buttons()

    # --- what the window asks ------------------------------------------------------

    def is_busy(self) -> bool:
        """True while any file is waiting for or being transcribed."""

        return self.model.count(*LOCKED) > 0

    def output_dir(self) -> Path | None:
        """The folder chosen for the subtitles, or `None` for "next to each file"."""

        if self.folder_radio.isChecked() and self.folder_edit.text():
            return Path(self.folder_edit.text())

        return None

    # --- building the screen --------------------------------------------------------

    def _build(self) -> None:

        self.add_files_button = QPushButton("Add files…")
        self.add_folder_button = QPushButton("Add folder…")
        self.recursive_check = QCheckBox("Include sub folders")
        self.remove_button = QPushButton("Remove")
        self.clear_button = QPushButton("Clear")
        self.up_button = QPushButton("Move up")
        self.down_button = QPushButton("Move down")
        self.requeue_button = QPushButton("Queue again")

        # Two short rows rather than one long one: the window can be narrow
        # (a tiling window manager often makes it so).
        adding = QHBoxLayout()

        for widget in (self.add_files_button, self.add_folder_button, self.recursive_check):
            adding.addWidget(widget)

        adding.addStretch(1)

        editing = QHBoxLayout()

        for widget in (
            self.up_button,
            self.down_button,
            self.requeue_button,
            self.remove_button,
            self.clear_button,
        ):
            editing.addWidget(widget)

        editing.addStretch(1)

        self.view = FileQueueView(self)
        self.view.setModel(self.model)
        self.view.setContextMenuPolicy(self.view.contextMenuPolicy().CustomContextMenu)

        self.next_to_radio = QRadioButton("Next to each file")
        self.folder_radio = QRadioButton("In this folder:")
        self.next_to_radio.setChecked(True)
        self.folder_edit = QLineEdit()
        self.folder_edit.setReadOnly(True)
        self.folder_edit.setPlaceholderText("Choose a folder…")
        self.folder_button = QPushButton("Browse…")
        self.skip_existing_check = QCheckBox("Skip files whose subtitles already exist")

        choice = QHBoxLayout()
        choice.addWidget(QLabel("Save subtitles:"))
        choice.addWidget(self.next_to_radio)
        choice.addWidget(self.folder_radio)
        choice.addStretch(1)

        folder = QHBoxLayout()
        folder.addWidget(self.folder_edit, 1)
        folder.addWidget(self.folder_button)

        self.detail = QLabel("Add files, or drop them here.")
        self.start_button = QPushButton("Start")
        self.cancel_button = QPushButton("Cancel")

        bottom = QHBoxLayout()
        bottom.addWidget(self.detail, 1)
        bottom.addWidget(self.cancel_button)
        bottom.addWidget(self.start_button)

        layout = QVBoxLayout(self)
        layout.addLayout(adding)
        layout.addLayout(editing)
        layout.addWidget(self.view, 1)
        layout.addLayout(choice)
        layout.addLayout(folder)
        layout.addWidget(self.skip_existing_check)
        layout.addLayout(bottom)

        self._update_folder_controls()

    def _connect(self) -> None:

        self.add_files_button.clicked.connect(self.choose_files)
        self.add_folder_button.clicked.connect(self.choose_folder)
        self.remove_button.clicked.connect(self.remove_selected)
        self.clear_button.clicked.connect(self.clear)
        self.up_button.clicked.connect(self.move_up)
        self.down_button.clicked.connect(self.move_down)
        self.requeue_button.clicked.connect(self.requeue_selected)
        self.start_button.clicked.connect(self.start)
        self.cancel_button.clicked.connect(self.cancel)
        self.folder_button.clicked.connect(self.choose_output_folder)
        self.folder_radio.toggled.connect(self._update_folder_controls)

        self.view.paths_dropped.connect(self.add_paths)
        self.view.customContextMenuRequested.connect(self._show_menu)
        self.view.selectionModel().selectionChanged.connect(self._update_buttons)

        for signal in (
            self.model.rowsInserted,
            self.model.rowsRemoved,
            self.model.rowsMoved,
            self.model.dataChanged,
            self.model.modelReset,
        ):
            signal.connect(self._update_buttons)

        self._prober.duration_ready.connect(self.model.set_duration)

        bridge = self._bridge
        bridge.model_loading.connect(self._on_model_loading)
        bridge.model_ready.connect(self._on_model_ready)
        bridge.file_started.connect(self._on_started)
        bridge.file_progress.connect(self._on_progress)
        bridge.file_finished.connect(self._on_finished)
        bridge.file_failed.connect(self._on_failed)
        bridge.file_cancelled.connect(self._on_cancelled)
        bridge.queue_finished.connect(self._on_queue_finished)

    # --- adding files ------------------------------------------------------------------

    def choose_files(self) -> None:
        """Ask for files with the system file dialog."""

        patterns = " ".join(f"*{ext}" for ext in sorted(MEDIA_EXTENSIONS))

        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add files", "", f"Audio and video ({patterns});;All files (*)"
        )

        self.add_paths([Path(p) for p in paths])

    def choose_folder(self) -> None:
        """Ask for a folder whose media files are added."""

        folder = QFileDialog.getExistingDirectory(self, "Add folder")

        if folder:
            self.add_paths([Path(folder)])

    def add_paths(self, paths: list[Path]) -> None:
        """Add files and folders (from a dialog or a drop)."""

        if not paths:
            return

        result = self.model.add_paths(paths, recursive=self.recursive_check.isChecked())

        self._prober.probe(result.added)

        parts = [f"Added {len(result.added)} file{'s' if len(result.added) != 1 else ''}"]

        if result.duplicates:
            parts.append(f"{result.duplicates} already in the list")

        self.detail.setText(", ".join(parts) + ".")

        if result.problems:
            shown = result.problems[:_MAX_PROBLEMS_SHOWN]
            more = len(result.problems) - len(shown)
            text = "\n".join(shown) + (f"\nand {more} more" if more else "")
            self._warn("Some files could not be added", text)

        if not result.added and not result.duplicates and not result.problems:
            self.detail.setText("No media files found.")

    # --- editing the list -----------------------------------------------------------------

    def remove_selected(self) -> None:
        self.model.remove_rows(self.view.selected_rows())

    def clear(self) -> None:
        self.model.clear()

    def move_up(self) -> None:
        self._move(-1)

    def move_down(self) -> None:
        self._move(+1)

    def _move(self, delta: int) -> None:
        rows = self.view.selected_rows()

        # The selection follows the moved row by itself.
        if len(rows) == 1:
            self.model.move(rows[0], delta)

    def requeue_selected(self) -> None:
        self.model.requeue(self.view.selected_rows())

    # --- the output location -----------------------------------------------------------------

    def choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Save subtitles in")

        if folder:
            self.folder_edit.setText(folder)
            self.folder_radio.setChecked(True)

    def _update_folder_controls(self) -> None:
        # Browse stays live: using it switches to "In this folder" by itself.
        self.folder_edit.setEnabled(self.folder_radio.isChecked())

    # --- running ------------------------------------------------------------------------------

    def start(self) -> None:
        """Hand every queued (and cancelled) file to the runner."""

        queued = [item for item in self.model.items() if item.status in _STARTABLE]

        if not queued:
            return

        if self.folder_radio.isChecked() and not self.folder_edit.text():
            self._warn("Can't start", "Choose the folder for the subtitles first.")
            return

        try:
            settings = self._settings_provider()

        except ConfigError as e:
            self._warn("Settings", str(e))
            return

        files = [item.path for item in queued]

        try:
            plan = plan_all_outputs(files, settings.formats, output_dir=self.output_dir())

        except ValueError as e:
            # An output would overwrite an input, or two files would write the same output.
            self._warn("Can't start", str(e))
            return

        jobs = []
        skipped = 0

        for item in queued:
            outputs = plan[item.path]

            if self.skip_existing_check.isChecked() and all(p.exists() for p in outputs.values()):
                self.model.mark_skipped(item.path, outputs)
                skipped += 1
                continue

            self.model.mark_waiting(item.path, outputs)
            jobs.append((Job(item.path, outputs), settings))

        if jobs:
            self._first_error = ""
            self.detail.setText("Starting…")
            self.detail.setToolTip("")
            self._bridge.submit_many(jobs)

        else:
            self.detail.setText(f"Nothing to do: all {skipped} already have subtitles.")

    def cancel(self) -> None:
        """Stop the running file and drop the ones waiting."""

        self.detail.setText("Cancelling…")
        self._bridge.cancel_all()

    # --- what the runner reports -----------------------------------------------------------------

    def _on_model_loading(self, model_config: object) -> None:
        self.detail.setText(f"Loading the {getattr(model_config, 'name', 'speech')} model…")

    def _on_model_ready(self, model_config: object) -> None:
        name = getattr(model_config, "name", "")
        device = getattr(model_config, "device", "")
        self.detail.setText(f"Model {name} ready ({device}).")

    def _on_started(self, job: Job) -> None:
        self.model.on_started(job.input_file)
        self.detail.setText(f"Transcribing {job.input_file.name}…")

    def _on_progress(self, job: Job, position: float, duration: float) -> None:
        self.model.on_progress(job.input_file, position, duration)

        text = f"{job.input_file.name}: {format_time(position)}"

        if duration > 0:
            text += f" / {format_time(duration)}"

        speed = self.model.speed(job.input_file)
        eta = self.model.eta(job.input_file)

        if speed:
            text += f"  ·  {speed:.1f}x"

        if eta is not None:
            text += f"  ·  {format_time(eta)} left"

        self.detail.setText(text)

    def _on_finished(self, job: Job, result: FileResult) -> None:
        self.model.on_finished(job.input_file, result.warnings)

    def _on_failed(self, job: Job, message: str) -> None:
        self.model.on_failed(job.input_file, message)

        if not self._first_error:
            self._first_error = message

    def _on_cancelled(self, job: Job) -> None:
        self.model.on_cancelled(job.input_file)

    def _on_queue_finished(self, done: int, failed: int, cancelled: int) -> None:
        parts = [f"{done} done"]

        if failed:
            parts.append(f"{failed} failed")

        if cancelled:
            parts.append(f"{cancelled} cancelled")

        text = ", ".join(parts) + "."

        if self._first_error:
            text += f" {self._first_error}"

        self.detail.setText(text)
        self.detail.setToolTip(text)
        self._update_buttons()

    # --- the context menu -------------------------------------------------------------------------

    def open_output_folder(self, row: int) -> bool:
        """Show the folder a file's subtitles are in. False if there is none to show."""

        outputs = self.model.item(row).outputs

        if not outputs:
            return False

        folder = next(iter(outputs.values())).parent

        return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))))

    def _show_menu(self, position: QPoint) -> None:
        index = self.view.indexAt(position)

        if not index.isValid():
            return

        row = index.row()
        item = self.model.item(row)
        menu = QMenu(self)

        if item.outputs and item.status in (Status.DONE, Status.SKIPPED):
            menu.addAction("Show subtitles in folder", lambda: self.open_output_folder(row))

        if item.status in _FINISHED:
            menu.addAction("Queue again", lambda: self.model.requeue([row]))

        if item.status is Status.RUNNING:
            menu.addAction("Cancel this file", self._bridge.cancel_current)

        if item.status not in LOCKED:
            menu.addAction("Remove", lambda: self.model.remove_rows([row]))

        if not menu.isEmpty():
            menu.exec(self.view.viewport().mapToGlobal(position))

    # --- keeping the buttons honest -------------------------------------------------

    def _update_buttons(self, *_: object) -> None:
        rows = self.view.selected_rows()
        items = [self.model.item(r) for r in rows]

        self.start_button.setEnabled(self.model.count(*_STARTABLE) > 0)
        self.cancel_button.setEnabled(self.is_busy())
        self.remove_button.setEnabled(any(i.status not in LOCKED for i in items))
        self.clear_button.setEnabled(self.model.count() > self.model.count(*LOCKED))
        self.requeue_button.setEnabled(any(i.status in _FINISHED for i in items))

        single = len(rows) == 1
        self.up_button.setEnabled(single and rows[0] > 0)
        self.down_button.setEnabled(single and rows[0] < self.model.count() - 1)

    def _warn(self, title: str, text: str) -> None:
        QMessageBox.warning(self, title, text)
