"""'Fundamentales' tab: company figures and yearly charts for the symbol on the chart."""

from __future__ import annotations

import logging

import shiboken6
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QStackedLayout, QVBoxLayout, QWidget

from analisis_acciones.models.errors import user_message_for
from analisis_acciones.services.fundamentals_report import fundamentals_html
from analisis_acciones.services.market_data_service import FundamentalsResult, MarketDataService
from analisis_acciones.ui import strings
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)


class FundamentalsPanel(QWidget):
    def __init__(self, market: MarketDataService | None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._market = market
        self._workers: set[Worker] = set()
        self._seq = 0
        self.symbol: str | None = None
        self.result: FundamentalsResult | None = None
        self.html = ""
        self.message = QLabel(strings.FUND_EMPTY)
        self.message.setObjectName("panelEmpty")
        self.message.setWordWrap(True)
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.view = QWebEngineView()
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        message_page = QWidget()
        QVBoxLayout(message_page).addWidget(self.message)
        self._stack = QStackedLayout(self)
        self._stack.addWidget(message_page)
        self._stack.addWidget(self.view)

    def set_symbol(self, symbol: str, name: str = "") -> None:
        """Load figures for ``symbol`` (cache-first, in a worker); stale replies are dropped."""
        if symbol == self.symbol and self.result is not None:
            return
        self.symbol = symbol
        self.result = None
        self._seq += 1
        seq = self._seq
        if self._market is None or symbol.upper().startswith("CSV:"):
            self._show_message(strings.FUND_UNAVAILABLE)
            return
        self._show_message(strings.FUND_LOADING.format(symbol=symbol))
        market = self._market

        def done(result: FundamentalsResult) -> None:
            if shiboken6.isValid(self) and seq == self._seq:
                self.result = result
                self.html = fundamentals_html(result, name)
                self.view.setHtml(self.html, QUrl("about:blank"))
                self._stack.setCurrentIndex(1)

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self) and seq == self._seq:
                self._show_message(user_message_for(exc))

        worker = start_worker(lambda: market.fundamentals(symbol), done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def _show_message(self, text: str) -> None:
        self.message.setText(text)
        self._stack.setCurrentIndex(0)
