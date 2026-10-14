"""'Resumen del día' window: the watchlist at a glance, recent alerts and scan news."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import unquote

import shiboken6
from PySide6.QtCore import QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from analisis_acciones.alerts.service import AlertEvent, AlertService
from analisis_acciones.data.freshness import market_open
from analisis_acciones.models.errors import user_message_for
from analisis_acciones.services.company_calendar import CalendarEntry
from analisis_acciones.services.day_summary import (
    OPEN_PREFIX,
    SummaryItem,
    load_calendar,
    load_items,
    summary_html,
)
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.ui import strings
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

RECENT_EVENTS = timedelta(days=3)


class _LinkPage(QWebEnginePage):
    """Static page: ticker links become a signal; any other navigation is blocked."""

    symbol_clicked = Signal(str)

    def acceptNavigationRequest(self, url: QUrl | str, nav_type: QWebEnginePage.NavigationType,
                                is_main_frame: bool) -> bool:  # fmt: skip
        target = QUrl(url).toString()
        if target.startswith(OPEN_PREFIX):
            symbol = unquote(target[len(OPEN_PREFIX) :]).strip()
            if symbol and len(symbol) <= 40:
                self.symbol_clicked.emit(symbol)
            return False
        # Only the page's own content (set with setHtml) may load.
        return nav_type != QWebEnginePage.NavigationType.NavigationTypeLinkClicked and (
            target in ("about:blank", "") or target.startswith("data:")
        )


class DaySummaryDialog(QDialog):
    symbol_activated = Signal(str)

    def __init__(self, market: MarketDataService, settings: SettingsService,
                 symbols: Callable[[], list[str]], alerts: AlertService | None = None,
                 list_name: Callable[[], str] = lambda: "",
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 parent: QWidget | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._market = market
        self._settings = settings
        self._symbols = symbols
        self._alerts = alerts
        self._list_name = list_name
        self._clock = clock
        self._workers: set[Worker] = set()
        self.items: list[SummaryItem] | None = None
        self.calendar: list[CalendarEntry] = []
        self.html = ""
        self.setWindowTitle(strings.SUMMARY_TITLE)
        self.resize(1000, 760)

        self.view = QWebEngineView()
        self.page = _LinkPage(self.view)
        self.view.setPage(self.page)
        settings_ = self.page.settings()
        settings_.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, False)
        settings_.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False
        )
        self.page.symbol_clicked.connect(self.symbol_activated)
        self.show_on_start = QCheckBox(strings.SUMMARY_ON_START)
        self.show_on_start.setChecked(settings.summary_on_start())
        self.show_on_start.toggled.connect(settings.set_summary_on_start)
        self.refresh_button = QPushButton(strings.SUMMARY_REFRESH)
        self.refresh_button.clicked.connect(self.refresh)
        self.status = QLabel()
        self.status.setObjectName("detailsSource")
        bottom = QHBoxLayout()
        bottom.addWidget(self.show_on_start)
        bottom.addWidget(self.status, stretch=1)
        bottom.addWidget(self.refresh_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.addWidget(self.view, stretch=1)
        layout.addLayout(bottom)

    def recent_events(self) -> list[AlertEvent]:
        if self._alerts is None:
            return []
        try:
            events = self._alerts.events(100)
        except Exception as exc:  # e.g. closing: the summary must still show
            logger.warning("Could not read alert events: %s", exc)
            return []
        since = self._clock() - RECENT_EVENTS
        return [e for e in events if e.triggered_at >= since]

    def refresh(self) -> None:
        symbols = self._symbols()
        self.refresh_button.setEnabled(False)
        self.status.setText(strings.SUMMARY_LOADING.format(count=len(symbols)))
        market = self._market

        today = self._clock().astimezone().date()

        def job() -> tuple[list[SummaryItem], list[CalendarEntry]]:
            return load_items(market, symbols), load_calendar(market, symbols, today)

        def done(loaded: tuple[list[SummaryItem], list[CalendarEntry]]) -> None:
            if not shiboken6.isValid(self):
                return
            self.refresh_button.setEnabled(True)
            self.status.setText("")
            self.show_items(*loaded)

        def fail(exc: BaseException) -> None:
            if shiboken6.isValid(self):
                self.refresh_button.setEnabled(True)
                self.status.setText(user_message_for(exc))

        worker = start_worker(job, done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))

    def show_items(self, items: list[SummaryItem],
                   calendar: list[CalendarEntry] | None = None) -> None:  # fmt: skip
        self.items = items
        self.calendar = calendar or []
        now = self._clock()
        self.html = summary_html(items, self.recent_events(), now, market_open(now),
                                 self._list_name(), self.calendar)  # fmt: skip
        self.view.setHtml(self.html, QUrl("about:blank"))
