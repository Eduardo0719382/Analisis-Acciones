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
    QComboBox,
    QDateEdit,
    QDialog,
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
from analisis_acciones.services.paper_portfolio import PaperPortfolioService, PortfolioReport
from analisis_acciones.services.portfolio_report import (
    portfolio_html,
    portfolio_trades_csv,
    qty,
)
from analisis_acciones.services.scan_report import num
from analisis_acciones.ui import strings
from analisis_acciones.ui.html_pdf import HtmlPdfWriter
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

TRADE_ROLE = Qt.ItemDataRole.UserRole


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
        top.addWidget(self.export_button)

        # Trade form
        self.symbol = QLineEdit(symbol)
        self.symbol.setPlaceholderText("AAPL")
        self.side = QComboBox()
        self.side.addItem(strings.PF_BUY, BUY)
        self.side.addItem(strings.PF_SELL, SELL)
        self.quantity = QDoubleSpinBox()
        self.quantity.setRange(0.0001, 1e9)
        self.quantity.setDecimals(4)
        self.quantity.setValue(1)
        self.price = QDoubleSpinBox()
        self.price.setRange(0, 1e9)
        self.price.setDecimals(4)
        self.price.setSpecialValueText(strings.PF_PRICE_CLOSE)
        self.trade_date = QDateEdit(QDate.currentDate())
        self.trade_date.setCalendarPopup(True)
        self.trade_date.setMaximumDate(QDate.currentDate())
        self.trade_date.setDisplayFormat("dd/MM/yyyy")
        self.commission = QDoubleSpinBox()
        self.commission.setRange(0, 1e6)
        self.commission.setDecimals(2)
        self.note = QLineEdit()
        self.note.setMaxLength(120)
        self.add_button = QPushButton(strings.PF_ADD)
        self.add_button.clicked.connect(self.add_trade)
        form_box = QGroupBox(strings.PF_NEW_TRADE)
        grid = QGridLayout(form_box)
        fields: list[tuple[str, QWidget]] = [
            (strings.PF_SYMBOL, self.symbol), (strings.PF_SIDE, self.side),
            (strings.PF_QUANTITY, self.quantity), (strings.PF_PRICE, self.price),
            (strings.PF_DATE, self.trade_date), (strings.PF_COMMISSION, self.commission),
        ]  # fmt: skip
        for i, (label, widget) in enumerate(fields):
            grid.addWidget(QLabel(label), 0, i)
            grid.addWidget(widget, 1, i)
        note_row = QFormLayout()
        note_row.addRow(strings.PF_NOTE, self.note)
        grid.addLayout(note_row, 2, 0, 1, 5)
        grid.addWidget(self.add_button, 2, 5)

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
        trades_page = QWidget()
        trades_layout = QVBoxLayout(trades_page)
        trades_layout.addWidget(self.trades, stretch=1)
        trades_layout.addWidget(self.delete_trade_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.view, strings.PF_TAB_SUMMARY)
        self.tabs.addTab(trades_page, strings.PF_TAB_TRADES)

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

    # Trades ----------------------------------------------------------------------
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
        quantity, commission = self.quantity.value(), self.commission.value()
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
                                                  commission, note), done)  # fmt: skip

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
        self.view.setHtml(portfolio_html(report, datetime.now()), QUrl("about:blank"))
        rows = list(reversed(report.trades))
        self.trades.setRowCount(len(rows))
        for r, t in enumerate(rows):
            cells = [f"{t.trade_date:%d/%m/%Y}", t.symbol,
                     strings.PF_BUY if t.side == BUY else strings.PF_SELL, qty(t.quantity),
                     num(t.price, 4).rstrip("0").rstrip(","), num(t.commission),
                     num(t.value), t.note]  # fmt: skip
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c == 0:
                    item.setData(TRADE_ROLE, t.id)
                self.trades.setItem(r, c, item)
        self.delete_trade_button.setEnabled(bool(rows))

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
