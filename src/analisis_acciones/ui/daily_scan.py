"""Runs the watchlist scan once per completed session while the program is open."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime

import shiboken6
from PySide6.QtCore import QObject, QTimer, Signal

from analisis_acciones.services.daily_scan import (
    find_novelties,
    is_due,
    make_snapshot,
    previous_items,
    session_of,
)
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scanner import ScanResult, run_scan
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)

CHECK_INTERVAL_MS = 30 * 60 * 1000
FIRST_CHECK_DELAY_MS = 20_000


class DailyScanController(QObject):
    #: (ScanResult, list[Novelty]) after each automatic scan.
    finished = Signal(object, list)

    def __init__(self, settings: SettingsService, market: MarketDataService,
                 symbols: Callable[[], list[str]],
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC),
                 parent: QObject | None = None) -> None:  # fmt: skip
        super().__init__(parent)
        self._settings = settings
        self._market = market
        self._symbols = symbols
        self._clock = clock
        self._workers: set[Worker] = set()
        self.running = False
        self.last_result: ScanResult | None = None
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self.maybe_run)

    def start(self, first_delay_ms: int = FIRST_CHECK_DELAY_MS) -> None:
        self.timer.start()
        QTimer.singleShot(first_delay_ms, self.maybe_run)

    def maybe_run(self, force: bool = False) -> bool:
        """Start a scan if enabled and due (or ``force``). Returns True when one started."""
        if self.running or not shiboken6.isValid(self):
            return False
        if not force:
            if not self._settings.daily_scan_enabled():
                return False
            if not is_due(self._clock(), self._settings.scan_snapshot()):
                return False
        symbols = self._symbols()
        if not symbols:
            return False
        self.running = True
        market = self._market

        def done(result: ScanResult) -> None:
            self.running = False
            if shiboken6.isValid(self):
                self._finish(result)

        def fail(exc: BaseException) -> None:
            self.running = False
            logger.error("Daily scan failed: %s", exc, exc_info=exc)

        worker = start_worker(lambda: run_scan(market, symbols), done, fail)
        self._workers.add(worker)
        worker.signals.succeeded.connect(lambda _r: self._workers.discard(worker))
        worker.signals.failed.connect(lambda _e: self._workers.discard(worker))
        return True

    def _finish(self, result: ScanResult) -> None:
        self.last_result = result
        if not result.rows:
            # Nothing analysed (offline?): try again later instead of marking the session done.
            logger.warning("Daily scan produced no rows: %s", result.problems)
            self.finished.emit(result, [])
            return
        snapshot = self._settings.scan_snapshot()
        previous = previous_items(snapshot)
        novelties = find_novelties(previous, result)
        self._settings.set_scan_snapshot(make_snapshot(result, session_of(self._clock()), previous))
        logger.info("Daily scan: %d symbols, %d novelties", len(result.rows), len(novelties))
        self.finished.emit(result, novelties)
