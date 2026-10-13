"""'Buscar actualizaciones' dialog: check, show changes, apply, offer restart."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.models.errors import user_message_for
from analisis_acciones.services.update_service import UpdateCheck, UpdateResult, UpdateService
from analisis_acciones.ui import strings
from analisis_acciones.ui.workers import Worker, start_worker


class UpdateDialog(QDialog):
    def __init__(self, service: UpdateService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._worker: Worker | None = None  # keep a reference while running
        self.restart_requested = False

        self.setWindowTitle(strings.UPDATE_TITLE)
        self.setMinimumWidth(480)

        self.message = QLabel()
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.message.setWordWrap(True)

        # Commit messages are external data: shown as plain text only.
        self.changes = QPlainTextEdit()
        self.changes.setReadOnly(True)
        self.changes.setVisible(False)

        self.buttons = QDialogButtonBox()
        self.update_button = QPushButton(strings.UPDATE_APPLY)
        self.restart_button = QPushButton(strings.UPDATE_RESTART)
        self.close_button = QPushButton(strings.UPDATE_CLOSE)
        self.buttons.addButton(self.update_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.restart_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.buttons.addButton(self.close_button, QDialogButtonBox.ButtonRole.RejectRole)
        self.update_button.clicked.connect(self._apply)
        self.restart_button.clicked.connect(self._restart)
        self.close_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.message)
        layout.addWidget(self.changes)
        layout.addWidget(self.buttons)

        self._set_state(strings.UPDATE_CHECKING, busy=True)

    def start(self) -> None:
        self._worker = start_worker(self._service.check, self._on_checked, self._on_failed)

    # State -----------------------------------------------------------------
    def _set_state(
        self,
        message: str,
        *,
        busy: bool = False,
        can_update: bool = False,
        can_restart: bool = False,
    ) -> None:
        self.message.setText(message)
        self.update_button.setVisible(can_update)
        self.restart_button.setVisible(can_restart)
        self.close_button.setEnabled(not busy)
        if busy:
            self.setCursor(Qt.CursorShape.BusyCursor)
        else:
            self.unsetCursor()

    def _on_checked(self, result: Any) -> None:
        check: UpdateCheck = result
        if not check.available:
            self._set_state(strings.UPDATE_UP_TO_DATE)
            return
        self.changes.setPlainText("\n".join(f"• {c}" for c in check.changes))
        self.changes.setVisible(True)
        self._set_state(strings.UPDATE_AVAILABLE.format(count=check.behind), can_update=True)

    def _apply(self) -> None:
        self._set_state(strings.UPDATE_APPLYING, busy=True)
        self._worker = start_worker(self._service.apply, self._on_applied, self._on_failed)

    def _on_applied(self, result: Any) -> None:
        update: UpdateResult = result
        message = strings.UPDATE_DONE
        if update.dependencies_reinstalled:
            message += "\n" + strings.UPDATE_DEPS_REINSTALLED
        self._set_state(message, can_restart=True)

    def _on_failed(self, exc: BaseException) -> None:
        self._set_state(user_message_for(exc))

    def _restart(self) -> None:
        self.restart_requested = True
        self.accept()
