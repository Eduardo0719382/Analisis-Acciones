"""Simple framed panels with a header, used for the main layout regions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget


class Panel(QFrame):
    """A titled region. ``body`` holds the panel content."""

    def __init__(self, title: str, empty_message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.header = QLabel(title)
        self.header.setObjectName("panelHeader")
        layout.addWidget(self.header)

        self.empty_label = QLabel(empty_message)
        self.empty_label.setObjectName("panelEmpty")
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty_label, stretch=1)
