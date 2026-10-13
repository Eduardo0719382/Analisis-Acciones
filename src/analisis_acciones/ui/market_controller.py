"""Bridges the UI and MarketDataService: runs requests in workers and drops stale replies.

Only the most recent search and the most recent load are delivered: if the user
types or switches symbols quickly, replies to older requests are discarded.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

from analisis_acciones.models.errors import user_message_for
from analisis_acciones.models.market import Interval
from analisis_acciones.services.market_data_service import LoadResult, MarketDataService
from analisis_acciones.ui.workers import Worker, start_worker

logger = logging.getLogger(__name__)


class MarketController(QObject):
    search_finished = Signal(str, list)  # query, list[SearchResult]
    search_failed = Signal(str, str)  # query, user message
    load_started = Signal(str, object)  # symbol, Interval
    load_finished = Signal(object)  # LoadResult
    load_failed = Signal(str, str)  # symbol, user message

    def __init__(self, service: MarketDataService, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self._search_seq = 0
        self._load_seq = 0
        self._workers: set[Worker] = set()

    def _start(
        self,
        fn: Callable[[], object],
        on_success: Callable[[Any], None],
        on_failure: Callable[[BaseException], None],
    ) -> None:
        holder: list[Worker] = []

        def done_ok(result: object) -> None:
            self._workers.discard(holder[0])
            on_success(result)

        def done_err(exc: BaseException) -> None:
            self._workers.discard(holder[0])
            on_failure(exc)

        worker = start_worker(fn, done_ok, done_err)
        holder.append(worker)
        self._workers.add(worker)

    # Search ----------------------------------------------------------------
    def search(self, query: str) -> None:
        self._search_seq += 1
        seq = self._search_seq
        if not query:
            return

        def ok(results: object) -> None:
            if seq == self._search_seq:
                self.search_finished.emit(query, results)

        def fail(exc: BaseException) -> None:
            if seq == self._search_seq:
                self.search_failed.emit(query, user_message_for(exc))

        self._start(lambda: self.service.search(query), ok, fail)

    # Loading ---------------------------------------------------------------
    def load(self, symbol: str, interval: Interval) -> None:
        self._load_seq += 1
        seq = self._load_seq
        self.load_started.emit(symbol, interval)

        def ok(result: object) -> None:
            if seq != self._load_seq:
                return
            assert isinstance(result, LoadResult)
            self.load_finished.emit(result)

        def fail(exc: BaseException) -> None:
            if seq == self._load_seq:
                self.load_failed.emit(symbol, user_message_for(exc))

        self._start(lambda: self.service.load(symbol, interval), ok, fail)

    def import_csv(self, path: Path, name: str) -> None:
        self._load_seq += 1
        seq = self._load_seq
        self.load_started.emit(name, Interval.D1)

        def ok(result: object) -> None:
            if seq == self._load_seq:
                assert isinstance(result, LoadResult)
                self.load_finished.emit(result)

        def fail(exc: BaseException) -> None:
            if seq == self._load_seq:
                self.load_failed.emit(name, user_message_for(exc))

        self._start(lambda: self.service.import_csv(path, name), ok, fail)

    def remember(self, symbol: str, name: str | None) -> None:
        try:
            self.service.remember(symbol, name)
        except Exception:
            logger.exception("Could not store recent symbol %s", symbol)
