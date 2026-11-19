"""The About box."""

from pathlib import Path

import PySide6
from PySide6.QtCore import Qt, qVersion
from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from .about_info import (
    CHANGELOG,
    CREDITS,
    DESCRIPTION,
    HOMEPAGE,
    ISSUES,
    LICENCE,
    environment_report,
)
from .resources import ICON_PATH
from .settings_panel import device_summary


class AboutDialog(QDialog):
    """Name, version, links, credits, and the details to paste into a bug report."""

    def __init__(self, settings_file: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self.setWindowTitle("About SubtitleMaker")
        self.resize(540, 520)

        icon = QLabel()
        icon.setPixmap(QIcon(str(ICON_PATH)).pixmap(80, 80))
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.title_label = QLabel(f"<h2>SubtitleMaker {__version__}</h2>")

        self.description_label = QLabel(DESCRIPTION)
        self.description_label.setWordWrap(True)

        self.links_label = self._rich(
            f'<a href="{HOMEPAGE}">Project page</a> · '
            f'<a href="{ISSUES}">Report a problem</a> · '
            f'<a href="{CHANGELOG}">What changed</a>'
        )

        credits_ = "<br>".join(
            f'<a href="{address}">{name}</a> ({licence})' for name, address, licence in CREDITS
        )
        self.credits_label = self._rich(f"<b>Built on</b><br>{credits_}")
        self.licence_label = QLabel(LICENCE)
        self.licence_label.setWordWrap(True)

        header = QVBoxLayout()
        header.addWidget(self.title_label)
        header.addWidget(self.description_label)
        header.addWidget(self.links_label)

        top = QHBoxLayout()
        top.addWidget(icon)
        top.addLayout(header, 1)

        self.details = QPlainTextEdit(
            environment_report(
                qt=f"{qVersion()} (PySide6 {PySide6.__version__}), "
                f"platform {QGuiApplication.platformName()}",
                device=device_summary(),
                settings_file=settings_file,
            )
        )
        self.details.setReadOnly(True)
        self.details.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.details.setMinimumHeight(150)
        self.details.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)  # nothing hidden

        self.copy_button = QPushButton("Copy details")
        self.copy_button.setToolTip("Copy these details, for a bug report")
        self.close_button = QPushButton("Close")
        self.close_button.setDefault(True)

        self.copy_button.clicked.connect(self.copy_details)
        self.close_button.clicked.connect(self.close)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.close_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.credits_label)
        layout.addWidget(self.licence_label)
        layout.addWidget(QLabel("<b>Details</b> (for a bug report)"))
        layout.addWidget(self.details)
        layout.addLayout(buttons)

    def copy_details(self) -> None:
        """Put the details on the clipboard."""

        QApplication.clipboard().setText(self.details.toPlainText())

    @staticmethod
    def _rich(html: str) -> QLabel:
        """A label whose links open in the browser."""

        label = QLabel(html)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setOpenExternalLinks(True)
        label.setWordWrap(True)

        return label
