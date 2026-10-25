"""Paper portfolio window: record simulated trades and see how the portfolio is doing."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.models.errors import UserError, user_message_for
from analisis_acciones.portfolio.engine import BUY, SELL
from analisis_acciones.services.paper_portfolio import (
    PaperPortfolioService,
    Portfolio,
    PortfolioReport,
)
from analisis_acciones.services.portfolio_report import (
    local_price,
    portfolio_html,
    portfolio_trades_csv,
    qty,
)
from analisis_acciones.services.scan_report import num
from analisis_acciones.ui import strings
from analisis_acciones.ui.html_pdf import HtmlPdfWriter
from analisis_acciones.ui.rebalance_panel import RebalancePanel
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

TRADE_ROLE = Qt.ItemDataRole.UserRole
SHARES, DOLLARS = "shares", "dollars"


def costs_text(p: Portfolio) -> str:
    parts = []
    if p.commission_fixed:
        parts.append(f"{num(p.commission_fixed)} $")
    if p.commission_pct:
        parts.append(f"{num(p.commission_pct, 3).rstrip('0').rstrip(',')} %")
    text = " + ".join(parts)
    if p.commission_min:
        text += f" (mínimo {num(p.commission_min)} $)"
    return strings.PF_COSTS_SUMMARY.format(text=text.strip() or strings.PF_COSTS_NONE)


class CostsDialog(QDialog):
    """Commission schedule and dividend option of one portfolio."""

    def __init__(self, portfolio: Portfolio, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(strings.PF_COSTS_TITLE)
        self.fixed = QDoubleSpinBox()
        self.fixed.setRange(0, 1e4)
        self.fixed.setDecimals(2)
        self.fixed.setValue(portfolio.commission_fixed)
        self.pct = QDoubleSpinBox()
        self.pct.setRange(0, 9.999)
        self.pct.setDecimals(3)
        self.pct.setValue(portfolio.commission_pct)
        self.minimum = QDoubleSpinBox()
        self.minimum.setRange(0, 1e4)
        self.minimum.setDecimals(2)
        self.minimum.setValue(portfolio.commission_min)
        self.dividends = QCheckBox(strings.PF_COSTS_DIVIDENDS)
        self.dividends.setChecked(portfolio.apply_dividends)
        self.withholding = QDoubleSpinBox()
        self.withholding.setRange(0, 60)
        self.withholding.setDecimals(1)
        self.withholding.setSuffix(" %")
        self.withholding.setValue(portfolio.dividend_withholding_pct)
        self.gains_tax = QDoubleSpinBox()
        self.gains_tax.setRange(0, 60)
        self.gains_tax.setDecimals(1)
        self.gains_tax.setSuffix(" %")
        self.gains_tax.setValue(portfolio.capital_gains_tax_pct)
        taxes = QGroupBox(strings.PF_TAXES_TITLE)
        taxes_form = QFormLayout(taxes)
        taxes_intro = QLabel(strings.PF_TAXES_INTRO)
        taxes_intro.setWordWrap(True)
        taxes_form.addRow(taxes_intro)
        taxes_form.addRow(strings.PF_TAXES_WITHHOLDING, self.withholding)
        taxes_form.addRow(strings.PF_TAXES_GAINS, self.gains_tax)
        intro = QLabel(strings.PF_COSTS_INTRO)
        intro.setWordWrap(True)
        form = QFormLayout()
        form.addRow(strings.PF_COSTS_FIXED, self.fixed)
        form.addRow(strings.PF_COSTS_PCT, self.pct)
        form.addRow(strings.PF_COSTS_MIN, self.minimum)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.dividends)
        layout.addWidget(taxes)
        layout.addWidget(buttons)


class PortfolioDialog(QDialog):
    symbol_activated = Signal(str)

    def __init__(self, service: PaperPortfolioService, benchmark: Callable[[], str],
                 symbol: str = "", parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._service = service
        self._benchmark = benchmark
        self._workers: set[Worker] = set()
        self._pdf_writer: HtmlPdfWriter | None = None
        self.report: PortfolioReport | None = None
        self.last_export: Path | None = None
        self.open_after_export = True
        self.setWindowTitle(strings.PF_TITLE)
        self.resize(1150, 820)

        # Portfolio selector
        self.portfolio = QComboBox()
        self.portfolio.currentIndexChanged.connect(lambda _i: self.refresh())
        new_button = QPushButton(strings.PF_NEW)
        new_button.clicked.connect(self._ask_new_portfolio)
        self.delete_portfolio_button = QPushButton(strings.PF_DELETE)
        self.delete_portfolio_button.clicked.connect(self._ask_delete_portfolio)
        self.costs_button = QPushButton(strings.PF_COSTS)
        self.costs_button.clicked.connect(self._ask_costs)
        self.export_button = QPushButton(strings.SCAN_EXPORT)
        menu = QMenu(self.export_button)
        menu.addAction(strings.SCAN_EXPORT_HTML, lambda: self._ask_and_export("html"))
        menu.addAction(strings.SCAN_EXPORT_PDF, lambda: self._ask_and_export("pdf"))
        menu.addAction(strings.SCAN_EXPORT_CSV, lambda: self._ask_and_export("csv"))
        self.export_button.setMenu(menu)
        top = QHBoxLayout()
        top.addWidget(QLabel(strings.PF_PORTFOLIO))
        top.addWidget(self.portfolio, stretch=1)
        top.addWidget(new_button)
        top.addWidget(self.delete_portfolio_button)
        top.addWidget(self.costs_button)
        top.addWidget(self.export_button)

        # Trade form
        self.symbol = QLineEdit(symbol)
        self.symbol.setPlaceholderText("AAPL")
        self.side = QComboBox()
        self.side.addItem(strings.PF_BUY, BUY)
        self.side.addItem(strings.PF_SELL, SELL)
        self.mode = QComboBox()
        self.mode.addItem(strings.PF_MODE_SHARES, SHARES)
        self.mode.addItem(strings.PF_MODE_DOLLARS, DOLLARS)
        self.mode.currentIndexChanged.connect(lambda _i: self._mode_changed())
        self.quantity_label = QLabel(strings.PF_QUANTITY)
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0.0001, 1e9)
        self.quantity.setDecimals(4)
        self.quantity.setValue(1)
        self.price = QDoubleSpinBox()
        self.price.setRange(0, 1e9)
        self.price.setDecimals(4)
        self.price.setSpecialValueText(strings.PF_PRICE_CLOSE)
        self.price.setToolTip(strings.PF_PRICE_TIP)
        self.trade_date = QDateEdit(QDate.currentDate())
        self.trade_date.setCalendarPopup(True)
        self.trade_date.setMaximumDate(QDate.currentDate())
        self.trade_date.setDisplayFormat("dd/MM/yyyy")
        self.commission = QDoubleSpinBox()
        self.commission.setRange(0, 1e6)
        self.commission.setDecimals(2)
        self.commission.setSuffix(" $")
        self.commission_auto = QCheckBox(strings.PF_COMMISSION_AUTO)
        self.commission_auto.setToolTip(strings.PF_COMMISSION_AUTO_TIP)
        self.commission_auto.toggled.connect(lambda on: self.commission.setEnabled(not on))
        self.commission_auto.setChecked(True)
        commission_box = QWidget()
        commission_row = QHBoxLayout(commission_box)
        commission_row.setContentsMargins(0, 0, 0, 0)
        commission_row.addWidget(self.commission_auto)
        commission_row.addWidget(self.commission, stretch=1)
        self.note = QLineEdit()
        self.note.setMaxLength(500)
        self.note.setPlaceholderText(strings.PF_NOTE_PLACEHOLDER)
        self.costs_label = QLabel()
        self.costs_label.setObjectName("detailsSource")
        self.add_button = QPushButton(strings.PF_ADD)
        self.add_button.clicked.connect(self.add_trade)
        form_box = QGroupBox(strings.PF_NEW_TRADE)
        grid = QGridLayout(form_box)
        fields: list[tuple[QLabel, QWidget]] = [
            (QLabel(strings.PF_SYMBOL), self.symbol), (QLabel(strings.PF_SIDE), self.side),
            (QLabel(strings.PF_MODE_SHARES + " / $"), self.mode),
            (self.quantity_label, self.quantity), (QLabel(strings.PF_PRICE), self.price),
            (QLabel(strings.PF_DATE), self.trade_date),
            (QLabel(strings.PF_COMMISSION), commission_box),
        ]  # fmt: skip
        for i, (label, widget) in enumerate(fields):
            grid.addWidget(label, 0, i)
            grid.addWidget(widget, 1, i)
        note_row = QFormLayout()
        note_row.addRow(strings.PF_NOTE, self.note)
        grid.addLayout(note_row, 2, 0, 1, 6)
        grid.addWidget(self.add_button, 2, 6)
        grid.addWidget(self.costs_label, 3, 0, 1, 7)

        # Results
        self.view = QWebEngineView()
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.trades = QTableWidget(0, len(strings.PF_TRADE_COLUMNS))
        self.trades.setHorizontalHeaderLabels(strings.PF_TRADE_COLUMNS)
        self.trades.verticalHeader().setVisible(False)
        self.trades.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trades.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.trades.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.trades.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.trades.horizontalHeader().setStretchLastSection(True)
        self.trades.cellDoubleClicked.connect(self._activate)
        self.delete_trade_button = QPushButton(strings.PF_DELETE_TRADE)
        self.delete_trade_button.clicked.connect(self.delete_selected_trade)
        self.review_button = QPushButton(strings.PF_REVIEW)
        self.review_button.clicked.connect(self._ask_review)
        trades_page = QWidget()
        trades_layout = QVBoxLayout(trades_page)
        trades_layout.addWidget(self.trades, stretch=1)
        trade_buttons = QHBoxLayout()
        trade_buttons.addStretch(1)
        trade_buttons.addWidget(self.review_button)
        trade_buttons.addWidget(self.delete_trade_button)
        trades_layout.addLayout(trade_buttons)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.view, strings.PF_TAB_SUMMARY)
        self.tabs.addTab(trades_page, strings.PF_TAB_TRADES)
        self.rebalance = RebalancePanel(service, lambda: self.portfolio_id, self._run, self)
        self.rebalance.applied.connect(self.refresh)
        self.tabs.addTab(self.rebalance, strings.PF_TAB_REBALANCE)

        self.status = QLabel()
        self.status.setObjectName("detailsSource")
        self.status.setWordWrap(True)
        disclaimer = QLabel(strings.PF_DISCLAIMER)
        disclaimer.setObjectName("detailsSource")
        disclaimer.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(form_box)
        layout.addWidget(self.tabs, stretch=1)
        layout.addWidget(self.status)
        layout.addWidget(disclaimer)
        self._fill_portfolios()

    # Portfolios ------------------------------------------------------------------
    def _fill_portfolios(self, select: int | None = None) -> None:
        self.portfolio.blockSignals(True)
        self.portfolio.clear()
        for p in self._service.portfolios():
            self.portfolio.addItem(
                strings.PF_ITEM.format(name=p.name, cash=num(p.initial_cash)), p.id
            )
        if select is not None:
            self.portfolio.setCurrentIndex(max(self.portfolio.findData(select), 0))
        self.portfolio.blockSignals(False)
        self.refresh()

    @property
    def portfolio_id(self) -> int:
        return int(self.portfolio.currentData())

    def _ask_new_portfolio(self) -> None:
        name, ok = QInputDialog.getText(self, strings.PF_NEW, strings.PF_NEW_NAME)
        if not ok:
            return
        cash, ok = QInputDialog.getDouble(self, strings.PF_NEW, strings.PF_NEW_CASH, 10_000,
                                          1, 1e12, 2)  # fmt: skip
        if ok:
            self.new_portfolio(name, cash)

    def new_portfolio(self, name: str, cash: float) -> bool:
        try:
            created = self._service.create(name, cash)
        except UserError as exc:
            self.status.setText(exc.user_message)
            return False
        self._fill_portfolios(select=created.id)
        return True

    def _ask_delete_portfolio(self) -> None:
        answer = QMessageBox.question(self, strings.PF_DELETE,
                                      strings.PF_DELETE_CONFIRM.format(
                                          name=self.portfolio.currentText()))  # fmt: skip
        if answer == QMessageBox.StandardButton.Yes:
            self._service.delete(self.portfolio_id)
            self._fill_portfolios()

    def current_portfolio(self) -> Portfolio | None:
        pid = self.portfolio.currentData()
        return next((p for p in self._service.portfolios() if p.id == pid), None)

    def _ask_costs(self) -> None:
        current = self.current_portfolio()
        if current is None:
            return
        dialog = CostsDialog(current, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_costs(dialog.fixed.value(), dialog.pct.value(), dialog.minimum.value(),
                           dialog.dividends.isChecked(), dialog.withholding.value(),
                           dialog.gains_tax.value())  # fmt: skip

    def set_costs(
        self,
        fixed: float,
        pct: float,
        minimum: float,
        dividends: bool,
        withholding: float | None = None,
        gains_tax: float | None = None,
    ) -> None:
        try:
            current = self._service.set_costs(self.portfolio_id, fixed, pct, minimum, dividends)
            self._service.set_taxes(
                self.portfolio_id,
                current.dividend_withholding_pct if withholding is None else withholding,
                current.capital_gains_tax_pct if gains_tax is None else gains_tax,
            )
        except UserError as exc:
            self.status.setText(exc.user_message)
            return
        self.refresh()

    # Trades ----------------------------------------------------------------------
    def _mode_changed(self) -> None:
        dollars = self.mode.currentData() == DOLLARS
        self.quantity_label.setText(strings.PF_AMOUNT if dollars else strings.PF_QUANTITY)
        self.quantity.setDecimals(2 if dollars else 4)
        self.quantity.setMinimum(0.01 if dollars else 0.0001)
        self.quantity.setSuffix(" $" if dollars else "")

    def _run(self, job: Callable[[], Any], done: Callable[[Any], None]) -> None:
        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                self.add_button.setEnabled(True)
                self.status.setText(user_message_for(exc))

        def ok(result: Any) -> None:
            if shiboken6.isValid(self):
                done(result)

        worker = start_worker(job, ok, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def add_trade(self) -> None:
        pid = self.portfolio_id
        symbol, side = self.symbol.text(), str(self.side.currentData())
        size = self.quantity.value()
        dollars = self.mode.currentData() == DOLLARS
        quantity, amount = (None, size) if dollars else (size, None)
        commission = None if self.commission_auto.isChecked() else self.commission.value()
        price = self.price.value() or None
        day = date.fromisoformat(self.trade_date.date().toString("yyyy-MM-dd"))
        note = self.note.text()
        self.add_button.setEnabled(False)
        self.status.setText(strings.PF_SAVING)

        def done(_trade: object) -> None:
            self.add_button.setEnabled(True)
            self.note.clear()
            self.refresh()

        self._run(lambda: self._service.add_trade(pid, symbol, side, quantity, price, day,
                                                  commission, note, amount), done)  # fmt: skip

    def _ask_review(self) -> None:
        item = self.trades.item(self.trades.currentRow(), 0)
        if item is None or self.report is None:
            return
        trade_id = int(item.data(TRADE_ROLE))
        current = next((t.review for t in self.report.trades if t.id == trade_id), "")
        text, ok = QInputDialog.getMultiLineText(self, strings.PF_REVIEW,
                                                 strings.PF_REVIEW_PROMPT, current)  # fmt: skip
        if ok:
            self.set_review(trade_id, text)

    def set_review(self, trade_id: int, text: str) -> None:
        self._service.set_review(self.portfolio_id, trade_id, text)
        self.refresh()

    def delete_selected_trade(self) -> None:
        item = self.trades.item(self.trades.currentRow(), 0)
        if item is None:
            return
        try:
            self._service.delete_trade(self.portfolio_id, int(item.data(TRADE_ROLE)))
        except UserError as exc:
            self.status.setText(exc.user_message)
            return
        self.refresh()

    def _activate(self, row: int, _column: int) -> None:
        item = self.trades.item(row, 1)
        if item is not None:
            self.symbol_activated.emit(item.text())

    # Report ----------------------------------------------------------------------
    def refresh(self) -> None:
        if self.portfolio.currentData() is None:
            return
        pid, bench = self.portfolio_id, self._benchmark()
        self.status.setText(strings.PF_LOADING)
        self._run(lambda: self._service.report(pid, bench), self.show_report)

    def show_report(self, report: PortfolioReport) -> None:
        if self.portfolio.currentData() != report.portfolio.id:
            return  # another portfolio was selected meanwhile
        self.report = report
        self.status.setText("")
        self.costs_label.setText(costs_text(report.portfolio))
        self.view.setHtml(portfolio_html(report, datetime.now()), QUrl("about:blank"))
        rows = list(reversed(report.trades))
        results = {c.trade.id: c.result for c in report.closed if c.trade.id is not None}
        self.trades.setRowCount(len(rows))
        for r, t in enumerate(rows):
            cells = [f"{t.trade_date:%d/%m/%Y}", t.symbol,
                     strings.PF_BUY if t.side == BUY else strings.PF_SELL, qty(t.quantity),
                     local_price(t), num(t.commission),
                     num(t.value * t.fx_rate),
                     num(results[t.id], sign=True) if t.id in results else "",
                     t.note, t.review]  # fmt: skip
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setData(TRADE_ROLE, t.id)
                self.trades.setItem(r, c, item)
        self.delete_trade_button.setEnabled(bool(rows))
        self.review_button.setEnabled(bool(rows))
        self.rebalance.set_report(report)

    # Export ------------------------------------------------------------------
    def _ask_and_export(self, kind: str) -> None:
        filters = {"html": "Página web (*.html)", "pdf": "PDF (*.pdf)", "csv": "CSV (*.csv)"}
        suggested = str(Path.home() / f"cartera_{datetime.now():%Y-%m-%d}.{kind}")
        path, _ = QFileDialog.getSaveFileName(self, strings.SCAN_EXPORT, suggested, filters[kind])
        if path:
            self.export(kind, Path(path))

    def export(self, kind: str, path: Path) -> None:
        if self.report is None:
            return
        if path.suffix.lower() != f".{kind}":
            path = path.with_name(path.name + f".{kind}")
        try:
            if kind == "csv":
                path.write_text(portfolio_trades_csv(self.report), encoding="utf-8-sig")
                self._exported(path, open_it=False)
                return
            html = portfolio_html(self.report, datetime.now())
            if kind == "html":
                path.write_text(html, encoding="utf-8")
                self._exported(path)
                return
        except OSError as exc:
            self.status.setText(strings.SCAN_EXPORT_FAILED.format(error=exc))
            return

        def written(ok: bool) -> None:
            self._pdf_writer = None
            if shiboken6.isValid(self):
                if ok and path.exists():
                    self._exported(path)
                else:
                    self.status.setText(strings.SCAN_EXPORT_FAILED.format(error="PDF"))

        self.status.setText(strings.SCAN_EXPORT_WORKING)
        self._pdf_writer = HtmlPdfWriter(html, path, written, self)

    def _exported(self, path: Path, open_it: bool = True) -> None:
        self.status.setText(strings.SCAN_EXPORT_SAVED.format(path=path))
        self.last_export = path
        if open_it and self.open_after_export:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
