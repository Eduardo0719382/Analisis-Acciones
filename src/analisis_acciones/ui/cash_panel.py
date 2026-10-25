"""'Efectivo' tab of the paper portfolio: deposits, withdrawals and broker cash movements."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.models.errors import UserError
from analisis_acciones.portfolio.engine import (
    CASH_DIVIDEND,
    DEPOSIT,
    FEE,
    INTEREST,
    WITHDRAWAL,
    CashMovement,
)
from analisis_acciones.services.paper_portfolio import PaperPortfolioService
from analisis_acciones.services.portfolio_report import MOVEMENT_LABELS
from analisis_acciones.services.scan_report import num
from analisis_acciones.ui import strings

ID_ROLE = Qt.ItemDataRole.UserRole


class CashPanel(QWidget):
    #: Movements changed: the portfolio must be recalculated.
    changed = Signal()

    def __init__(self, service: PaperPortfolioService, portfolio_id: Callable[[], int],
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._service = service
        self._portfolio_id = portfolio_id

        intro = QLabel(strings.CASH_INTRO)
        intro.setWordWrap(True)
        intro.setObjectName("detailsSource")
        self.kind = QComboBox()
        for kind in (DEPOSIT, WITHDRAWAL, CASH_DIVIDEND, INTEREST, FEE):
            self.kind.addItem(MOVEMENT_LABELS[kind], kind)
        self.kind.currentIndexChanged.connect(lambda _i: self._kind_changed())
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.setMaximumDate(QDate.currentDate())
        self.day.setDisplayFormat("dd/MM/yyyy")
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0.01, 1e12)
        self.amount.setDecimals(2)
        self.amount.setSuffix(" $")
        self.amount.setValue(1000)
        self.symbol = QLineEdit()
        self.symbol.setPlaceholderText(strings.CASH_SYMBOL_HINT)
        self.symbol.setMaxLength(20)
        self.note = QLineEdit()
        self.note.setMaxLength(500)
        self.add_button = QPushButton(strings.CASH_ADD)
        self.add_button.clicked.connect(self.add)
        form = QGridLayout()
        for i, (label, widget) in enumerate(
            [
                (strings.CASH_KIND, self.kind),
                (strings.PF_DATE, self.day),
                (strings.CASH_AMOUNT, self.amount),
                (strings.PF_SYMBOL, self.symbol),
                (strings.PF_NOTE, self.note),
            ]
        ):
            form.addWidget(QLabel(label), 0, i)
            form.addWidget(widget, 1, i)
        form.addWidget(self.add_button, 1, 5)

        self.table = QTableWidget(0, len(strings.CASH_COLUMNS))
        self.table.setHorizontalHeaderLabels(strings.CASH_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.delete_button = QPushButton(strings.CASH_DELETE)
        self.delete_button.clicked.connect(self.delete_selected)
        self.status = QLabel()
        self.status.setWordWrap(True)
        buttons = QHBoxLayout()
        buttons.addWidget(self.status, stretch=1)
        buttons.addWidget(self.delete_button)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.table, stretch=1)
        layout.addLayout(buttons)
        self._kind_changed()

    def _kind_changed(self) -> None:
        self.symbol.setEnabled(self.kind.currentData() == CASH_DIVIDEND)

    def show_movements(self, movements: list[CashMovement]) -> None:
        rows = list(reversed(movements))
        self.table.setRowCount(len(rows))
        for r, m in enumerate(rows):
            cells = [f"{m.day:%d/%m/%Y}", MOVEMENT_LABELS.get(m.kind, m.kind), m.symbol or "—",
                     num(m.dollars), m.note]  # fmt: skip
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setData(ID_ROLE, m.id)
                self.table.setItem(r, c, item)
        self.delete_button.setEnabled(bool(rows))

    def add(self) -> None:
        day = date.fromisoformat(self.day.date().toString("yyyy-MM-dd"))
        kind = str(self.kind.currentData())
        symbol = self.symbol.text() if kind == CASH_DIVIDEND else ""
        try:
            movement = self._service.make_movement(kind, self.amount.value(), day, symbol,
                                                   self.note.text())  # fmt: skip
            self._service.add_movement(self._portfolio_id(), movement)
        except UserError as exc:
            self.status.setText(exc.user_message)
            return
        self.status.setText("")
        self.note.clear()
        self.changed.emit()

    def delete_selected(self) -> None:
        item = self.table.item(self.table.currentRow(), 0)
        if item is None:
            return
        try:
            self._service.delete_movement(self._portfolio_id(), int(item.data(ID_ROLE)))
        except UserError as exc:
            self.status.setText(exc.user_message)
            return
        self.status.setText("")
        self.changed.emit()
