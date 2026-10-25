"""'Rebalanceo' tab of the paper portfolio: target weights, plan and one-click recording."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.models.errors import UserError
from analisis_acciones.portfolio.engine import BUY
from analisis_acciones.portfolio.rebalance import RebalancePlan
from analisis_acciones.services.paper_portfolio import PaperPortfolioService, PortfolioReport
from analisis_acciones.services.portfolio_report import qty
from analisis_acciones.services.scan_report import num
from analisis_acciones.ui import strings

logger = logging.getLogger(__name__)

Runner = Callable[[Callable[[], Any], Callable[[Any], None]], None]


class RebalancePanel(QWidget):
    #: Trades were recorded; the portfolio must be recalculated.
    applied = Signal()

    def __init__(self, service: PaperPortfolioService, portfolio_id: Callable[[], int],
                 run: Runner, parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._service = service
        self._portfolio_id = portfolio_id
        self._run = run
        self.report: PortfolioReport | None = None
        self.plan: RebalancePlan | None = None

        intro = QLabel(strings.RB_INTRO)
        intro.setWordWrap(True)
        intro.setObjectName("detailsSource")
        self.targets = QTableWidget(0, 2)
        self.targets.setHorizontalHeaderLabels(strings.RB_TARGET_COLUMNS)
        self.targets.verticalHeader().setVisible(False)
        self.targets.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.targets.setMaximumWidth(320)
        add_row = QPushButton(strings.RB_ADD_ROW)
        add_row.clicked.connect(lambda: self.add_target_row())
        remove_row = QPushButton(strings.RB_REMOVE_ROW)
        remove_row.clicked.connect(self._remove_row)
        self.save_button = QPushButton(strings.RB_SAVE)
        self.save_button.clicked.connect(self.save_targets)
        self.total_label = QLabel()
        left = QVBoxLayout()
        left.addWidget(self.targets, stretch=1)
        row_buttons = QHBoxLayout()
        row_buttons.addWidget(add_row)
        row_buttons.addWidget(remove_row)
        left.addLayout(row_buttons)
        left.addWidget(self.total_label)
        left.addWidget(self.save_button)

        self.plan_table = QTableWidget(0, len(strings.RB_PLAN_COLUMNS))
        self.plan_table.setHorizontalHeaderLabels(strings.RB_PLAN_COLUMNS)
        self.plan_table.verticalHeader().setVisible(False)
        self.plan_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.plan_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.plan_table.horizontalHeader().setStretchLastSection(True)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.apply_button = QPushButton(strings.RB_APPLY)
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self._ask_apply)
        right = QVBoxLayout()
        right.addWidget(QLabel(strings.RB_PLAN_TITLE))
        right.addWidget(self.plan_table, stretch=1)
        right.addWidget(self.summary)
        right.addWidget(self.apply_button)

        body = QHBoxLayout()
        body.addLayout(left)
        body.addLayout(right, stretch=1)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(body, stretch=1)
        self.targets.itemChanged.connect(lambda _i: self._update_total())

    # Targets -----------------------------------------------------------------
    def add_target_row(self, symbol: str = "", weight: float | None = None) -> None:
        row = self.targets.rowCount()
        self.targets.insertRow(row)
        self.targets.setItem(row, 0, QTableWidgetItem(symbol))
        self.targets.setItem(row, 1, QTableWidgetItem("" if weight is None else f"{weight:g}"))

    def _remove_row(self) -> None:
        row = self.targets.currentRow()
        if row >= 0:
            self.targets.removeRow(row)
            self._update_total()

    def entered_targets(self) -> dict[str, float]:
        """Rows with a ticker; raises UserError for an unreadable weight."""
        found: dict[str, float] = {}
        for row in range(self.targets.rowCount()):
            symbol_item, weight_item = self.targets.item(row, 0), self.targets.item(row, 1)
            symbol = symbol_item.text().strip().upper() if symbol_item else ""
            if not symbol:
                continue
            text = (weight_item.text() if weight_item else "").strip().replace(",", ".")
            text = text.rstrip("%").strip()
            try:
                found[symbol] = found.get(symbol, 0.0) + float(text)
            except ValueError as exc:
                raise UserError(
                    f"bad weight {text!r}",
                    user_message=strings.RB_BAD_WEIGHT.format(symbol=symbol),
                ) from exc
        return found

    def _update_total(self) -> None:
        try:
            total = sum(self.entered_targets().values())
        except UserError:
            self.total_label.setText(strings.RB_TOTAL_INVALID)
            return
        self.total_label.setText(strings.RB_TOTAL.format(total=num(total, 1),
                                                         cash=num(100 - total, 1)))  # fmt: skip

    def save_targets(self) -> None:
        try:
            self._service.set_targets(self._portfolio_id(), self.entered_targets())
        except UserError as exc:
            self.summary.setText(exc.user_message)
            return
        self.calculate()

    # Plan ----------------------------------------------------------------------
    def set_report(self, report: PortfolioReport) -> None:
        self.report = report
        self.targets.blockSignals(True)
        self.targets.setRowCount(0)
        for symbol, weight in self._service.targets(report.portfolio.id).items():
            self.add_target_row(symbol, weight)
        self.targets.blockSignals(False)
        self._update_total()
        self.calculate()

    def calculate(self) -> None:
        report = self.report
        if report is None:
            return
        self.summary.setText(strings.RB_CALCULATING)
        self.apply_button.setEnabled(False)
        self._run(lambda: self._service.rebalance_plan(report), self.show_plan)

    def show_plan(self, plan: RebalancePlan) -> None:
        self.plan = plan
        self.plan_table.setRowCount(len(plan.orders))
        for r, o in enumerate(plan.orders):
            cells = [o.symbol, f"{num(o.current_pct, 1)} %", f"{num(o.target_pct, 1)} %",
                     strings.PF_BUY if o.side == BUY else strings.PF_SELL, qty(o.quantity),
                     num(o.price), num(o.value)]  # fmt: skip
            for c, text in enumerate(cells):
                self.plan_table.setItem(r, c, QTableWidgetItem(text))
        if plan.problems:
            self.summary.setText("\n".join(plan.problems))
        elif not plan.orders:
            self.summary.setText(strings.RB_NOTHING)
        else:
            text = strings.RB_SUMMARY.format(
                count=len(plan.orders), commissions=num(plan.commissions),
                cash=num(plan.cash_after), cash_pct=num(plan.cash_target_pct, 1),
            )  # fmt: skip
            if plan.scaled:
                text += " " + strings.RB_SCALED
            self.summary.setText(text)
        self.apply_button.setEnabled(bool(plan.orders) and not plan.problems)

    def _ask_apply(self) -> None:
        if self.plan is None:
            return
        question = strings.RB_APPLY_CONFIRM.format(count=len(self.plan.orders))
        answer = QMessageBox.question(self, strings.RB_APPLY, question)
        if answer == QMessageBox.StandardButton.Yes:
            self.apply()

    def apply(self) -> None:
        plan, pid = self.plan, self._portfolio_id()
        if plan is None:
            return
        self.apply_button.setEnabled(False)
        self.summary.setText(strings.RB_APPLYING)
        self._run(lambda: self._service.apply_rebalance(pid, plan), lambda _t: self.applied.emit())
