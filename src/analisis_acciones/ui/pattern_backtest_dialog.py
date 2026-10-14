"""Pattern backtest dialog: run over several assets, show the visual report, export it."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import shiboken6
from PySide6.QtCore import QLocale, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.backtesting.patterns import (
    MAX_SYMBOLS,
    PATTERN_NAMES,
    PatternBacktestConfig,
    PatternBacktestResult,
    run_pattern_backtest,
)
from analisis_acciones.models.errors import user_message_for
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.pattern_report import (
    REASONS,
    pattern_report_html,
    pattern_trades_csv,
)
from analisis_acciones.ui import strings
from analisis_acciones.ui.html_pdf import HtmlPdfWriter
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)


class PatternBacktestDialog(QDialog):
    #: The user asked to open this symbol on the main chart.
    symbol_activated = Signal(str)

    def __init__(self, market: MarketDataService, symbols: list[str],
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._market = market
        self._workers: set[Worker] = set()
        self._pdf_writer: HtmlPdfWriter | None = None
        self.outcome: PatternBacktestResult | None = None
        self.last_export: Path | None = None
        #: Open exported reports with the system's default program (off in tests).
        self.open_after_export = True
        self.setWindowTitle(strings.PBT_TITLE)
        self.resize(1150, 780)

        self.symbols = QLineEdit(", ".join(symbols[:MAX_SYMBOLS]))
        self.symbols.setPlaceholderText(strings.SCAN_PLACEHOLDER.replace("50", str(MAX_SYMBOLS)))
        self.symbols.returnPressed.connect(self.run)
        self.run_button = QPushButton(strings.PBT_RUN)
        self.run_button.clicked.connect(self.run)
        self.export_button = QPushButton(strings.SCAN_EXPORT)
        menu = QMenu(self.export_button)
        menu.addAction(strings.SCAN_EXPORT_HTML, lambda: self._ask_and_export("html"))
        menu.addAction(strings.SCAN_EXPORT_PDF, lambda: self._ask_and_export("pdf"))
        menu.addAction(strings.SCAN_EXPORT_CSV, lambda: self._ask_and_export("csv"))
        self.export_button.setMenu(menu)
        self.export_button.setEnabled(False)
        top = QHBoxLayout()
        top.addWidget(QLabel(strings.SCAN_SYMBOLS))
        top.addWidget(self.symbols, stretch=1)
        top.addWidget(self.run_button)
        top.addWidget(self.export_button)

        self.max_bars = QSpinBox()
        self.max_bars.setRange(1, 500)
        self.max_bars.setValue(60)
        self.max_bars.setSuffix(strings.PROJ_BARS_SUFFIX)
        self.long_only = QCheckBox(strings.PBT_LONG_ONLY)
        self.commission = QDoubleSpinBox()
        self.commission.setRange(0, 5)
        self.commission.setDecimals(2)
        self.commission.setValue(0.1)
        self.slippage = QDoubleSpinBox()
        self.slippage.setRange(0, 5)
        self.slippage.setDecimals(2)
        self.slippage.setValue(0.05)
        options = QHBoxLayout()
        for label, widget in ((strings.PBT_MAX_BARS, self.max_bars),
                              (strings.PBT_COMMISSION, self.commission),
                              (strings.PBT_SLIPPAGE, self.slippage)):  # fmt: skip
            options.addWidget(QLabel(label))
            options.addWidget(widget)
        options.addWidget(self.long_only)
        options.addStretch(1)

        self.pattern_boxes: dict[str, QCheckBox] = {}
        group = QGroupBox(strings.PBT_PATTERNS)
        grid = QGridLayout(group)
        for i, name in enumerate(PATTERN_NAMES):
            box = QCheckBox(name)
            box.setChecked(True)
            self.pattern_boxes[name] = box
            grid.addWidget(box, i // 3, i % 3)

        self.view = QWebEngineView()
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.trades = QTableWidget(0, len(strings.PBT_TRADE_COLUMNS))
        self.trades.setHorizontalHeaderLabels(strings.PBT_TRADE_COLUMNS)
        self.trades.verticalHeader().setVisible(False)
        self.trades.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.trades.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.trades.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.trades.cellDoubleClicked.connect(self._activate)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.view, strings.PBT_TAB_SUMMARY)
        self.tabs.addTab(self.trades, strings.PBT_TAB_TRADES)
        self.status = QLabel()
        self.status.setObjectName("detailsSource")
        self.status.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addLayout(options)
        layout.addWidget(group)
        layout.addWidget(self.tabs, stretch=1)
        layout.addWidget(self.status)

    # Run -----------------------------------------------------------------------
    def parsed_symbols(self) -> list[str]:
        raw = [s.strip().upper() for s in self.symbols.text().replace(";", ",").split(",")]
        return list(dict.fromkeys(s for s in raw if s))[:MAX_SYMBOLS]

    def config(self) -> PatternBacktestConfig:
        return PatternBacktestConfig(
            max_bars=self.max_bars.value(), long_only=self.long_only.isChecked(),
            commission_pct=self.commission.value(), slippage_pct=self.slippage.value(),
            patterns=tuple(n for n, box in self.pattern_boxes.items() if box.isChecked()),
        )  # fmt: skip

    def run(self) -> None:
        symbols = self.parsed_symbols()
        if not symbols:
            self.status.setText(strings.SCAN_EMPTY)
            return
        config = self.config()
        self.run_button.setEnabled(False)
        self.status.setText(strings.PBT_RUNNING.format(count=len(symbols)))
        market = self._market

        def done(result: PatternBacktestResult) -> None:
            if shiboken6.isValid(self):
                self.run_button.setEnabled(True)
                self.show_result(result)

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                self.run_button.setEnabled(True)
                self.status.setText(user_message_for(exc))

        worker = start_worker(lambda: run_pattern_backtest(market, symbols, config), done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def show_result(self, result: PatternBacktestResult) -> None:
        self.outcome = result
        self.export_button.setEnabled(True)
        self.view.setHtml(pattern_report_html(result, datetime.now()), QUrl("about:blank"))
        loc = QLocale()
        rows = list(reversed(result.trades))
        self.trades.setRowCount(len(rows))
        for r, t in enumerate(rows):
            cells = [
                t.symbol, t.pattern, "Compra ▲" if t.direction > 0 else "Venta corta ▼",
                f"{t.entry_date:%d/%m/%Y}", loc.toString(t.entry_price, "f", 2),
                f"{t.exit_date:%d/%m/%Y}", loc.toString(t.exit_price, "f", 2),
                REASONS.get(t.exit_reason, t.exit_reason),
                ("+" if t.return_pct > 0 else "") + loc.toString(t.return_pct, "f", 2),
            ]  # fmt: skip
            for c, text in enumerate(cells):
                self.trades.setItem(r, c, QTableWidgetItem(text))
        text = strings.PBT_DONE.format(trades=len(result.trades), symbols=len(result.symbols))
        if result.problems:
            text += "\n" + "\n".join(result.problems)
        self.status.setText(text)

    def _activate(self, row: int, _column: int) -> None:
        item = self.trades.item(row, 0)
        if item is not None:
            self.symbol_activated.emit(item.text())

    # Export ------------------------------------------------------------------
    def _ask_and_export(self, kind: str) -> None:
        filters = {"html": "Página web (*.html)", "pdf": "PDF (*.pdf)", "csv": "CSV (*.csv)"}
        suggested = str(Path.home() / f"patrones_{datetime.now():%Y-%m-%d}.{kind}")
        path, _ = QFileDialog.getSaveFileName(self, strings.SCAN_EXPORT, suggested, filters[kind])
        if path:
            self.export(kind, Path(path))

    def export(self, kind: str, path: Path) -> None:
        if self.outcome is None:
            return
        if path.suffix.lower() != f".{kind}":
            path = path.with_name(path.name + f".{kind}")
        try:
            if kind == "csv":
                path.write_text(pattern_trades_csv(self.outcome), encoding="utf-8-sig")
                self._exported(path, open_it=False)
                return
            html = pattern_report_html(self.outcome, datetime.now())
            if kind == "html":
                path.write_text(html, encoding="utf-8")
                self._exported(path)
                return
        except OSError as exc:
            self.status.setText(strings.SCAN_EXPORT_FAILED.format(error=exc))
            return
        self.status.setText(strings.SCAN_EXPORT_WORKING)
        self.export_button.setEnabled(False)

        def written(ok: bool) -> None:
            self._pdf_writer = None
            if not shiboken6.isValid(self):
                return
            self.export_button.setEnabled(True)
            if ok and path.exists():
                self._exported(path)
            else:
                self.status.setText(strings.SCAN_EXPORT_FAILED.format(error="PDF"))

        self._pdf_writer = HtmlPdfWriter(html, path, written, self)

    def _exported(self, path: Path, open_it: bool = True) -> None:
        self.status.setText(strings.SCAN_EXPORT_SAVED.format(path=path))
        self.last_export = path
        if open_it and self.open_after_export:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
