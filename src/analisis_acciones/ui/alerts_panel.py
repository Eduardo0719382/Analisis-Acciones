"""'Alertas' tab: manage alert rules, see triggered events, run checks."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.alerts.rules import ALERT_SPECS, AlertKind, AlertRule, validate_alert_params
from analisis_acciones.alerts.service import AlertEvent, AlertService, CheckSummary, kind_choices
from analisis_acciones.models.errors import UserError, user_message_for
from analisis_acciones.ui import strings
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

EXPORT_FILE = "alertas_analisis_acciones.json"

CHECK_INTERVAL_MS = 15 * 60 * 1000
#: With intraday alerts active the check runs this often (intraday data is cached for
#: a few minutes, so most checks do not touch the network).
INTRADAY_CHECK_INTERVAL_MS = 2 * 60 * 1000
FIRST_CHECK_DELAY_MS = 20 * 1000


class NewAlertDialog(QDialog):
    def __init__(self, service: AlertService, symbol: str = "",
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._service = service
        self.setWindowTitle(strings.ALERT_NEW_TITLE)
        self.setMinimumWidth(420)
        self.symbol = QLineEdit(symbol)
        self.symbol.setPlaceholderText("AAPL")
        self.kind = QComboBox()
        for value, label in kind_choices():
            self.kind.addItem(label, value)
        self.kind.currentIndexChanged.connect(self._rebuild_params)
        self.form = QFormLayout()
        self.interval = QComboBox()
        for value, label in strings.ALERT_INTERVAL_CHOICES.items():
            self.interval.addItem(label, value)
        self.form.addRow(strings.ALERT_SYMBOL, self.symbol)
        self.form.addRow(strings.ALERT_INTERVAL, self.interval)
        self.form.addRow(strings.ALERT_CONDITION, self.kind)
        self.editors: dict[str, QSpinBox | QDoubleSpinBox] = {}
        self.preview = QLabel()
        self.preview.setObjectName("detailsSource")
        self.error = QLabel()
        self.error.setObjectName("panelEmpty")
        self.error.setProperty("error", True)
        self.error.setWordWrap(True)
        note = QLabel(strings.ALERT_EOD_NOTE)
        note.setObjectName("detailsSource")
        note.setWordWrap(True)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(strings.ALERT_CREATE)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(strings.DIALOG_CANCEL)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.preview)
        layout.addWidget(note)
        layout.addWidget(self.error)
        layout.addWidget(buttons)
        self._rebuild_params()

    def current_kind(self) -> AlertKind:
        return AlertKind(str(self.kind.currentData()))

    def _rebuild_params(self, _index: int = 0) -> None:
        while self.form.rowCount() > 3:
            self.form.removeRow(3)
        self.editors.clear()
        for param in ALERT_SPECS[self.current_kind()].params:
            editor: QSpinBox | QDoubleSpinBox
            if param.decimals == 0:
                editor = QSpinBox()
                editor.setRange(int(param.minimum), int(param.maximum))
                editor.setValue(int(param.default))
            else:
                editor = QDoubleSpinBox()
                editor.setDecimals(param.decimals)
                editor.setRange(param.minimum, param.maximum)
                editor.setValue(param.default)
            editor.valueChanged.connect(self._update_preview)
            self.editors[param.key] = editor
            self.form.addRow(param.label, editor)
        self._update_preview()

    def params(self) -> dict[str, float]:
        return {key: float(editor.value()) for key, editor in self.editors.items()}

    def _update_preview(self) -> None:
        try:
            params = validate_alert_params(self.current_kind(), self.params())
            self.preview.setText(ALERT_SPECS[self.current_kind()].describe(params))
        except UserError as exc:
            self.preview.setText(exc.user_message)

    def accept(self) -> None:
        try:
            interval = str(self.interval.currentData())
            self.created = self._service.create(self.symbol.text(), self.current_kind(),
                                                self.params(), interval=interval)  # fmt: skip
        except UserError as exc:
            self.error.setText(exc.user_message)
            return
        super().accept()


class AlertsPanel(QWidget):
    #: New alert events from a check (list[AlertEvent]).
    alerts_triggered = Signal(list)

    def __init__(self, service: AlertService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._service = service
        self._workers: set[Worker] = set()
        self._checking = False
        #: Returns the symbol on the chart, used to prefill new alerts.
        self.current_symbol_provider: Callable[[], str | None] | None = None

        self.new_button = QPushButton(strings.ALERT_NEW)
        self.new_button.clicked.connect(self.new_alert)
        self.toggle_button = QPushButton(strings.ALERT_TOGGLE)
        self.toggle_button.clicked.connect(self.toggle_selected)
        self.delete_button = QPushButton(strings.ALERT_DELETE)
        self.delete_button.clicked.connect(self.delete_selected)
        self.check_button = QPushButton(strings.ALERT_CHECK_NOW)
        self.check_button.clicked.connect(self.check_now)
        self.export_button = QPushButton(strings.ALERT_EXPORT)
        self.export_button.setToolTip(strings.ALERT_EXCHANGE_TIP)
        self.export_button.clicked.connect(lambda: self.export_alerts())
        self.import_button = QPushButton(strings.ALERT_IMPORT)
        self.import_button.setToolTip(strings.ALERT_EXCHANGE_TIP)
        self.import_button.clicked.connect(lambda: self.import_alerts())
        buttons = QHBoxLayout()
        for b in (self.new_button, self.toggle_button, self.delete_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        buttons.addWidget(self.export_button)
        buttons.addWidget(self.import_button)
        buttons.addWidget(self.check_button)

        self.table = QTableWidget(0, 3)
        self.table.setObjectName("alertsTable")
        self.table.setHorizontalHeaderLabels(
            [strings.ALERT_COL_CONDITION, strings.ALERT_COL_STATE, strings.ALERT_COL_LAST]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        head.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        head.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self.history = QListWidget()
        self.history.setObjectName("alertHistory")
        self.status = QLabel()
        self.status.setObjectName("detailsSource")
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addLayout(buttons)
        layout.addWidget(self.table, stretch=2)
        title = QLabel(strings.ALERT_HISTORY)
        title.setObjectName("detailsCaption")
        layout.addWidget(title)
        layout.addWidget(self.history, stretch=1)
        layout.addWidget(self.status)

        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self.check_now)
        self.reload()

    # Scheduling --------------------------------------------------------------
    def _update_schedule(self, rules: list[AlertRule]) -> None:
        intraday = any(r.enabled and r.interval != "1D" for r in rules)
        self.timer.setInterval(INTRADAY_CHECK_INTERVAL_MS if intraday else CHECK_INTERVAL_MS)

    def start_schedule(self, first_delay_ms: int = FIRST_CHECK_DELAY_MS) -> None:
        self.timer.start()
        QTimer.singleShot(first_delay_ms, self.check_now)

    def check_now(self) -> None:
        if self._checking or not shiboken6.isValid(self):
            return
        self._checking = True
        self.check_button.setEnabled(False)
        self.status.setText(strings.ALERT_CHECKING)

        def done(summary: CheckSummary) -> None:
            if not shiboken6.isValid(self):
                return
            self._finish()
            self.reload()
            text = strings.ALERT_CHECKED.format(count=summary.checked,
                                                fired=len(summary.events))  # fmt: skip
            if summary.problems:
                text += " " + strings.ALERT_PROBLEMS.format(count=len(summary.problems))
                self.status.setToolTip("\n".join(summary.problems))
            else:
                self.status.setToolTip("")
            self.status.setText(text)
            if summary.events:
                self.alerts_triggered.emit(list(summary.events))

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                self._finish()
                self.status.setText(user_message_for(exc))

        worker = start_worker(self._service.check_all, done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def _finish(self) -> None:
        self._checking = False
        self.check_button.setEnabled(True)

    # Table -------------------------------------------------------------------
    # Exchange with the phone -------------------------------------------------
    def export_alerts(self, path: Path | None = None) -> Path | None:
        if path is None:
            chosen, _ = QFileDialog.getSaveFileName(
                self, strings.ALERT_EXPORT, str(Path.home() / EXPORT_FILE), strings.ALERT_FILES
            )
            if not chosen:
                return None
            path = Path(chosen)
        try:
            path.write_text(self._service.export_json(), encoding="utf-8")
        except OSError as exc:
            self.status.setText(strings.EXPORT_FAILED.format(error=exc))
            return None
        self.status.setText(strings.ALERT_EXPORTED.format(path=path))
        return path

    def import_alerts(self, path: Path | None = None) -> None:
        if path is None:
            chosen, _ = QFileDialog.getOpenFileName(self, strings.ALERT_IMPORT, str(Path.home()),
                                                    strings.ALERT_FILES)  # fmt: skip
            if not chosen:
                return
            path = Path(chosen)
        try:
            text = path.read_text(encoding="utf-8")
            summary = self._service.import_json(text)
        except (OSError, UnicodeDecodeError):
            self.status.setText(strings.ALERT_IMPORT_UNREADABLE)
            return
        except UserError as exc:
            self.status.setText(exc.user_message)
            return
        self.reload()
        text = strings.ALERT_IMPORTED.format(added=summary.added, dup=summary.duplicates)
        if summary.problems:
            text += "\n" + "\n".join(summary.problems)
        self.status.setText(text)

    def reload(self) -> None:
        try:
            rules = self._service.alerts()
            events = self._service.events(50)
        except Exception as exc:  # e.g. closing: never break the UI
            logger.warning("Could not read alerts: %s", exc)
            return
        self._update_schedule(rules)
        self.table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            condition = QTableWidgetItem(rule.description)
            condition.setData(Qt.ItemDataRole.UserRole, rule.id)
            condition.setToolTip(rule.description)
            state = QTableWidgetItem(strings.ALERT_ACTIVE if rule.enabled else strings.ALERT_PAUSED)
            last = QTableWidgetItem(
                rule.last_triggered_at.astimezone().strftime("%d/%m/%Y %H:%M")
                if rule.last_triggered_at else "—"
            )  # fmt: skip
            for col, item in enumerate((condition, state, last)):
                self.table.setItem(row, col, item)
        has_rows = bool(rules)
        self.toggle_button.setEnabled(has_rows)
        self.delete_button.setEnabled(has_rows)
        self.history.clear()
        for event in events:
            self.history.addItem(self.format_event(event))
        if not events:
            self.history.addItem(strings.ALERT_NO_HISTORY)

    @staticmethod
    def format_event(event: AlertEvent) -> str:
        when = event.triggered_at.astimezone().strftime("%d/%m %H:%M")
        return (f"{when} · {event.description} — {event.message} "
                f"(barra {event.bar_date:%d/%m/%Y})")  # fmt: skip

    def selected_id(self) -> int | None:
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        value = item.data(Qt.ItemDataRole.UserRole) if item else None
        return int(value) if value is not None else None

    def new_alert(self) -> None:
        provider = self.current_symbol_provider
        symbol = (provider() if provider else None) or ""
        if symbol.startswith("CSV:"):
            symbol = ""
        dialog = NewAlertDialog(self._service, symbol, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.reload()

    def toggle_selected(self) -> None:
        alert_id = self.selected_id()
        if alert_id is None:
            return
        rule = next((r for r in self._service.alerts() if r.id == alert_id), None)
        if rule is not None:
            self._service.set_enabled(alert_id, not rule.enabled)
            self.reload()

    def delete_selected(self) -> None:
        alert_id = self.selected_id()
        if alert_id is not None:
            self._service.delete(alert_id)
            self.reload()
