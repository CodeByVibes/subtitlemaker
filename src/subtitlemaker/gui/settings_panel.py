"""The settings panel: what to make and how, shown beside the file queue."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..cli import option_help
from ..config import DEVICES, ConfigError, SubtitleStyle
from ..formats import FORMATS
from ..languages import known_language_codes
from ..settings import TASKS, Settings
from .settings_form import FormValues, base_values, decode, encode, to_settings
from .style_form import STYLE_FIELDS, StyleForm

SETTINGS_KEY = "settings/changes"

_COMPUTE_TYPES = ("auto", "float16", "int8_float16", "int8", "float32")

# Whisper models offered in the list (any other name or path can still be typed).
_MODEL_CHOICES = ("auto", "tiny", "base", "small", "medium", "large-v3", "turbo")

_TASK_LABELS = {
    "transcribe": "Transcribe (subtitles in the spoken language)",
    "translate": "Translate to English",
}

class CollapsibleSection(QWidget):
    """A heading that shows or hides what is under it."""

    def __init__(self, title: str, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.content = content

        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.toggle.toggled.connect(self.set_expanded)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle)
        layout.addWidget(content)

        self.set_expanded(False)

    def is_expanded(self) -> bool:
        return self.toggle.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle.setChecked(expanded)
        self.toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.content.setVisible(expanded)


class SettingsPanel(QWidget):
    """What to make (model, language, task, formats) and how (style, advanced options)."""

    # Emitted whenever any value changes.
    changed = Signal()

    # Emitted whenever the form is checked, with what is wrong with it ("" if nothing).
    problem_changed = Signal(str)

    def __init__(self, store: QSettings | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._store = store
        self._loading = False

        self._base, self._config_problem = base_values()
        self._help = option_help()

        # name -> (widget, read value, write value)
        self._fields: dict[str, tuple[QWidget, Callable[[], Any], Callable[[Any], object]]] = {}

        self._build()

        self.set_values(self._restored())

    # --- what the window asks ------------------------------------------------------

    def values(self) -> FormValues:
        """What the form holds now."""

        return FormValues(**{name: read() for name, (_, read, _w) in self._fields.items()})

    def set_values(self, values: FormValues) -> None:
        """Show `values` (without saving them: that follows only a user's change)."""

        self._loading = True

        try:
            for name, (_, _r, write) in self._fields.items():
                write(getattr(values, name))

        finally:
            self._loading = False

        self._validate()

    def apply_style(self, style: SubtitleStyle) -> None:
        """Make `style` the subtitle style of the form, as if the user had typed it."""

        self.style_form.write_style(style)
        self._edited()

    def widget(self, name: str) -> QWidget:
        """The editor of the form field `name` (a field of `FormValues`)."""

        return self._fields[name][0]

    def settings(self) -> Settings:
        """The settings for a run. Raises `ConfigError` with a message fit to show."""

        return to_settings(self.values())

    def reset(self) -> None:
        """Back to the config file's values (or the defaults), forgetting what was saved."""

        self.set_values(self._base)
        self._save()

    # --- building the form ------------------------------------------------------------

    def _build(self) -> None:

        self.error_label = QLabel()
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #ef4444;")
        self.error_label.hide()

        self.device_label = QLabel(device_summary())
        self.device_label.setWordWrap(True)

        basics = self._form()
        basics.addRow("Model", self._combo("model_name", _MODEL_CHOICES, "model"))
        basics.addRow("Language", self._language())
        basics.addRow(self._check("multilingual", "More than one language in the audio"))
        basics.addRow(
            "Task",
            self._choice(
                "task", [(_TASK_LABELS[key], key) for key in TASKS], tip_key="task"
            ),
        )
        basics.addRow("Subtitle files", self._formats())
        basics.addRow(
            "Prompt",
            self._text("initial_prompt", "Optional, e.g. a punctuated sentence", "prompt"),
        )

        self.style_form = StyleForm(self._help)
        self.style_form.edited.connect(self._edited)

        for name in STYLE_FIELDS:
            self._register_style_field(name)

        advanced = self._form()
        advanced.addRow("Device", self._combo("device", DEVICES, "device", editable=False))
        advanced.addRow("Precision", self._combo("compute_type", _COMPUTE_TYPES, "compute_type"))
        advanced.addRow(self._check("word_timestamps", "Time subtitles from single words"))
        advanced.addRow(self._check("vad_filter", "Skip silence before speech (VAD)", _VAD_HELP))
        advanced.addRow(
            "Use previous text as prompt",
            self._choice(
                "condition_on_previous_text",
                [("Automatic", None), ("On", True), ("Off", False)],
                tip_key="condition_on_previous_text",
            ),
        )
        advanced.addRow(
            "Skip silences longer than (s)",
            self._decimal("hallucination_silence_threshold", 0, 60, 0.5),
        )
        advanced.addRow("Language detection samples", self._spin("detect_segments", 1, 20, 1))
        advanced.addRow(
            "Language detection confidence", self._decimal("detect_threshold", 0.05, 1, 0.05)
        )

        self.style_section = CollapsibleSection("Subtitle style", self.style_form)
        self.advanced_section = CollapsibleSection("Advanced", _wrap(advanced))

        self.reset_button = QPushButton("Reset to defaults")
        self.reset_button.clicked.connect(self.reset)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)

        layout = QVBoxLayout(self)
        layout.addWidget(self.device_label)
        layout.addWidget(self.error_label)  # at the top, where it cannot be scrolled out of sight
        layout.addWidget(line)
        layout.addWidget(_wrap(basics))
        layout.addWidget(self.style_section)
        layout.addWidget(self.advanced_section)
        layout.addWidget(self.reset_button)
        layout.addStretch(1)

    # --- widget helpers -------------------------------------------------------------------

    def _register_style_field(self, name: str) -> None:
        """Make the style form's editor of `name` a field of this form."""

        def read() -> Any:
            return self.style_form.value(name)

        def write(value: Any) -> None:
            self.style_form.set_value(name, value)

        self._fields[name] = (self.style_form.widget(name), read, write)

    def _form(self) -> QFormLayout:
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        return form

    def _register(
        self,
        name: str,
        widget: QWidget,
        read: Callable[[], Any],
        write: Callable[[Any], object],
        signal: Any,
        tip_key: str | None = None,
    ) -> None:
        """Make `widget` the editor of the form field `name`."""

        self._fields[name] = (widget, read, write)
        signal.connect(self._edited)
        self._tip(widget, tip_key or name)

    def _combo(
        self, name: str, items: tuple[str, ...], tip_key: str, editable: bool = True
    ) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(editable)
        combo.addItems(items)
        self._register(
            name, combo, combo.currentText, combo.setCurrentText, combo.currentTextChanged, tip_key
        )

        return combo

    def _choice(
        self, name: str, options: list[tuple[str, Any]], tip_key: str
    ) -> QComboBox:
        """A list of `(label, value)`; the form field holds the value."""

        combo = QComboBox()

        for label, value in options:
            combo.addItem(label, value)

        self._register(
            name,
            combo,
            combo.currentData,
            lambda value: combo.setCurrentIndex(max(0, combo.findData(value))),
            combo.currentIndexChanged,
            tip_key,
        )

        return combo

    def _spin(self, name: str, low: int, high: int, step: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        self._register(name, spin, spin.value, spin.setValue, spin.valueChanged)

        return spin

    def _decimal(self, name: str, low: float, high: float, step: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(low, high)
        spin.setSingleStep(step)
        spin.setDecimals(2)
        self._register(name, spin, spin.value, spin.setValue, spin.valueChanged)

        return spin

    def _check(self, name: str, label: str, tip: str | None = None) -> QCheckBox:
        box = QCheckBox(label)
        self._register(name, box, box.isChecked, box.setChecked, box.toggled)

        if tip:
            box.setToolTip(tip)

        return box

    def _text(self, name: str, placeholder: str, tip_key: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        self._register(name, edit, edit.text, edit.setText, edit.textChanged, tip_key)

        return edit

    def _language(self) -> QLineEdit:
        edit = self._text("language", "Detect automatically", "language")

        completer = QCompleter(known_language_codes(), edit)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        edit.setCompleter(completer)

        return edit

    def _formats(self) -> QWidget:
        """One checkbox per output format; the form field is the tuple of the ticked names."""

        group = QWidget()
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)

        self._format_boxes = {name: QCheckBox(name.upper()) for name in FORMATS}

        for box in self._format_boxes.values():
            layout.addWidget(box)

        self._fields["formats"] = (group, self._read_formats, self._write_formats)

        for box in self._format_boxes.values():
            box.toggled.connect(self._edited)

        self._tip(group, "format")

        return group

    def _read_formats(self) -> tuple[str, ...]:
        return tuple(name for name, box in self._format_boxes.items() if box.isChecked())

    def _write_formats(self, names: tuple[str, ...]) -> None:

        for name, box in self._format_boxes.items():
            box.setChecked(name in names)

    def _tip(self, widget: QWidget, key: str) -> None:
        """The tooltip is the command line's help for the same option."""

        text = self._help.get(key)

        if text:
            widget.setToolTip(text)

    # --- reacting to changes ------------------------------------------------------------------

    def _edited(self, *_: object) -> None:

        if self._loading:
            return

        self._validate()
        self._save()
        self.changed.emit()

    def _validate(self) -> None:
        """Show what is wrong with the form, as soon as it is."""

        problem = ""

        try:
            self.settings()

        except ConfigError as e:
            problem = str(e)

        self.error_label.setText(problem)
        self.error_label.setVisible(bool(problem))
        self.problem_changed.emit(problem)

    def _restored(self) -> FormValues:
        """The starting values: the config file's, with what the user changed before."""

        if self._store is None:
            return self._base

        return decode(self._store.value(SETTINGS_KEY, ""), self._base)

    def _save(self) -> None:

        if self._store is not None:
            self._store.setValue(SETTINGS_KEY, encode(self.values(), self._base))
            self._store.sync()


def _wrap(layout: QFormLayout) -> QWidget:
    widget = QWidget()
    widget.setLayout(layout)

    return widget


_VAD_HELP = (
    "Cut out stretches without speech before transcribing, which avoids invented "
    "text in silence (default: on)."
)


def device_summary() -> str:
    """One line on what the machine can run the model on."""

    # Imported here: they load the machine learning libraries.
    from .._cuda import pip_libs_installed
    from .._packaged import CPU_ONLY_NOTE, cpu_only_build
    from ..transcribe import cuda_available

    if cpu_only_build():
        return CPU_ONLY_NOTE

    if not cuda_available():
        return "No NVIDIA GPU found. The CPU will be used, which is much slower."

    if pip_libs_installed():
        return "NVIDIA GPU found and ready (CUDA libraries installed)."

    return (
        "NVIDIA GPU found. If it fails to start, install the CUDA 12 libraries with "
        "pip install 'subtitlemaker[cuda]'."
    )
