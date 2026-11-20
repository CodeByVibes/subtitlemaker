"""The subtitle style controls, shared by the settings tab and the cue preview."""

import dataclasses
from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QSpinBox, QWidget

from ..config import SubtitleStyle

# (name, label, kind, minimum, maximum, step)
STYLE_ROWS: tuple[tuple[str, str, str, float, float, float], ...] = (
    ("max_line_length", "Characters per line", "int", 10, 200, 1),
    ("max_lines", "Lines per subtitle", "lines", 1, 2, 1),
    ("max_cps", "Characters per second", "float", 1, 100, 1),
    ("min_duration", "Shortest subtitle (s)", "float", 0.1, 60, 0.1),
    ("max_duration", "Longest subtitle (s)", "float", 0.5, 60, 0.5),
    ("min_gap", "Gap between subtitles (s)", "float", 0, 5, 0.05),
    ("max_pause", "Pause that starts a new subtitle (s)", "float", 0.1, 30, 0.1),
    ("linger", "Keep on screen after speech (s)", "float", 0, 5, 0.1),
    ("close_gap", "Close gaps shorter than (s)", "float", 0, 5, 0.1),
    ("start_offset", "Show subtitles later by (s)", "float", -2, 2, 0.05),
)

STYLE_FIELDS = tuple(field.name for field in dataclasses.fields(SubtitleStyle))


class StyleForm(QWidget):
    """One editor for each field of `SubtitleStyle`."""

    # Emitted when the user changes something (not when values are set by code).
    edited = Signal()

    def __init__(self, help_text: Mapping[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._loading = False
        self._widgets: dict[str, QWidget] = {}

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        for name, label, kind, low, high, step in STYLE_ROWS:
            widget = self._make(kind, low, high, step)
            widget.setToolTip(help_text.get(name, ""))

            self._widgets[name] = widget
            form.addRow(label, widget)

    def widget(self, name: str) -> QWidget:
        return self._widgets[name]

    def value(self, name: str) -> Any:
        widget = self._widgets[name]

        if isinstance(widget, QComboBox):
            return widget.currentData()

        assert isinstance(widget, QSpinBox | QDoubleSpinBox)

        return widget.value()

    def set_value(self, name: str, value: Any) -> None:
        widget = self._widgets[name]

        self._loading = True

        try:
            if isinstance(widget, QComboBox):
                widget.setCurrentIndex(max(0, widget.findData(value)))

            else:
                assert isinstance(widget, QSpinBox | QDoubleSpinBox)
                widget.setValue(value)

        finally:
            self._loading = False

    # Not called `style`: that would hide `QWidget.style()`, which returns the widget's QStyle.
    def read_style(self) -> SubtitleStyle:
        """What the form holds. Raises `ConfigError` if the values contradict each other."""

        return SubtitleStyle(**{name: self.value(name) for name in STYLE_FIELDS})

    def write_style(self, style: SubtitleStyle) -> None:
        for name in STYLE_FIELDS:
            self.set_value(name, getattr(style, name))

    # --- building ----------------------------------------------------------------------

    def _make(self, kind: str, low: float, high: float, step: float) -> QWidget:

        if kind == "lines":
            combo = QComboBox()
            combo.addItem("1", 1)
            combo.addItem("2", 2)
            combo.currentIndexChanged.connect(self._changed)

            return combo

        if kind == "int":
            spin = QSpinBox()
            spin.setRange(int(low), int(high))
            spin.setSingleStep(int(step))
            spin.valueChanged.connect(self._changed)

            return spin

        decimal = QDoubleSpinBox()
        decimal.setRange(low, high)
        decimal.setSingleStep(step)
        decimal.setDecimals(2)
        decimal.valueChanged.connect(self._changed)

        return decimal

    def _changed(self, *_: object) -> None:

        if not self._loading:
            self.edited.emit()
