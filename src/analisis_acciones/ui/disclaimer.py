"""First-run disclaimer dialog."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from analisis_acciones.ui import strings


class DisclaimerDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, require_acceptance: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.DISCLAIMER_TITLE)
        self.setMinimumWidth(460)

        text = QLabel(strings.DISCLAIMER_TEXT)
        text.setWordWrap(True)

        buttons = QDialogButtonBox()
        if require_acceptance:
            buttons.addButton(strings.DISCLAIMER_ACCEPT, QDialogButtonBox.ButtonRole.AcceptRole)
            buttons.addButton(strings.DISCLAIMER_REJECT, QDialogButtonBox.ButtonRole.RejectRole)
        else:
            buttons.addButton(QDialogButtonBox.StandardButton.Close)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.buttons = buttons

        layout = QVBoxLayout(self)
        layout.addWidget(text)
        layout.addWidget(buttons)
