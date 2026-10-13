"""Cache-first access to market data.

Flow for ``load(symbol, interval)``:

1. Read cached daily bars. If they are current (fetched after the last session
   close) return them without touching the network.
2. Otherwise fetch from the provider: the full history when nothing is cached,
   or only the recent ``OVERLAP_DAYS`` when something is. If the overlap does
   not match the cache (a split or dividend re-adjusted history) the full
   history is fetched again and replaces the cache.
3. If the provider fails with a network or provider error and a cache exists,
   the cached data is returned marked as stale. Nothing is ever fabricated.
4. Weekly/monthly bars are derived from daily bars.

All methods are blocking and thread-safe; the UI calls them from workers.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from analisis_acciones.data.csv_import import read_csv_bars
from analisis_acciones.data.details import AssetDetails, build_details
from analisis_acciones.data.freshness import needs_refresh, session_in_progress
from analisis_acciones.data.resample import resample_daily
from analisis_acciones.models.errors import (
    AppError,
    DataError,
    InternalError,
    NetworkError,
    ProviderError,
    UserError,
)
from analisis_acciones.models.market import BarSeries, CompanyInfo, Interval, Quote, SearchResult
from analisis_acciones.providers.base import MarketDataProvider, normalize_symbol
from analisis_acciones.storage.bar_repository import BarRepository
from analisis_acciones.storage.recent_repository import RecentSymbolRepository

logger = logging.getLogger(__name__)

CSV_PREFIX = "CSV:"
CSV_SOURCE = "Archivo CSV"
OVERLAP_DAYS = 30
OVERLAP_TOLERANCE = 1e-4  # relative difference in close prices
SEARCH_CACHE_TTL = timedelta(minutes=10)
DERIVED_INTERVALS = (Interval.W1, Interval.MN1)


@dataclass(frozen=True)
class LoadResult:
    series: BarSeries
    fetched_at: datetime | None
    from_cache: bool
    stale: bool = False
    session_in_progress: bool = False
    notices: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class WatchRow:
    symbol: str
    last_close: float | None
    change_pct: float | None
    as_of: date | None
    stale: bool = False
    error: str | None = None


def is_csv_symbol(symbol: str) -> bool:
    return symbol.upper().startswith(CSV_PREFIX)


class MarketDataService:
    def __init__(
        self,
        provider: MarketDataProvider,
        conn: sqlite3.Connection,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._provider = provider
        self._bars = BarRepository(conn)
        self._recent = RecentSymbolRepository(conn)
        self._clock = clock
        self._lock = threading.RLock()  # one connection shared by worker threads
        self._conn = conn
        self._closed = False
        self._search_cache: dict[str, tuple[datetime, list[SearchResult]]] = {}

    @contextmanager
    def _db(self) -> Iterator[None]:
        """Serialise database access; refuse it once the service is closed."""
        with self._lock:
            if self._closed:
                raise InternalError(
                    "market data service is closed",
                    user_message="La aplicación se está cerrando.",
                )
            yield

    def close(self) -> None:
        """Close the connection without racing worker threads that are using it."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._conn.close()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def available_intervals(self) -> list[Interval]:
        native = self._provider.get_available_intervals()
        derived = [i for i in DERIVED_INTERVALS if Interval.D1 in native and i not in native]
        return [*native, *derived]

    # Search ----------------------------------------------------------------
    def search(self, query: str, limit: int = 10) -> list[SearchResult]:
        key = query.strip().lower()
        if not key:
            return []
        now = self._clock()
        with self._db():
            cached = self._search_cache.get(key)
        if cached and now - cached[0] < SEARCH_CACHE_TTL:
            return cached[1]
        results = self._provider.search_symbol(query, limit)
        with self._db():
            self._search_cache[key] = (now, results)
        return results

    def recent(self, limit: int = 10) -> list[SearchResult]:
        with self._db():
            return self._recent.list(limit)

    def remember(self, symbol: str, name: str | None = None) -> None:
        with self._db():
            self._recent.add(symbol, name, self._clock())

    # Bars ------------------------------------------------------------------
    def load(self, symbol: str, interval: Interval) -> LoadResult:
        if interval not in self.available_intervals():
            raise UserError(
                f"interval {interval} not available",
                user_message=f"El intervalo {interval.value} no está disponible.",
            )
        daily = self._load_daily(symbol)
        if interval is Interval.D1:
            return daily
        bars = resample_daily(daily.series.bars, interval)
        series = BarSeries(
            daily.series.symbol, interval, bars, daily.series.source, daily.series.warnings
        )
        return LoadResult(
            series,
            daily.fetched_at,
            daily.from_cache,
            daily.stale,
            daily.session_in_progress,
            daily.notices,
        )

    def _load_daily(self, raw_symbol: str) -> LoadResult:
        if is_csv_symbol(raw_symbol):
            return self._load_csv(raw_symbol)
        symbol = normalize_symbol(raw_symbol)
        now = self._clock()
        with self._db():
            meta = self._bars.meta(symbol)
            cached = self._bars.load(symbol) if meta else None

        if meta is not None and cached is not None and not cached.empty:
            if not needs_refresh(meta.fetched_at, now):
                return self._result(symbol, cached, meta.source, meta.fetched_at, now, True)
            try:
                bars, source = self._refresh(symbol, cached, now)
            except (NetworkError, ProviderError, DataError) as exc:
                logger.warning("Refresh of %s failed, serving cache: %s", symbol, exc)
                return self._result(
                    symbol, cached, meta.source, meta.fetched_at, now, True,
                    stale=True, notices=(exc.user_message,),
                )  # fmt: skip
            return self._result(symbol, bars, source, now, now, False)

        series = self._provider.get_historical_data(symbol, Interval.D1)
        with self._db():
            self._bars.replace(symbol, series.source, series.bars, now)
        return self._result(
            symbol, series.bars, series.source, now, now, False, notices=series.warnings
        )

    def _refresh(
        self, symbol: str, cached: pd.DataFrame, now: datetime
    ) -> tuple[pd.DataFrame, str]:
        last_cached: date = cached.index[-1].date()
        start = last_cached - timedelta(days=OVERLAP_DAYS)
        recent = self._provider.get_historical_data(symbol, Interval.D1, start=start)
        new = recent.bars

        if new.empty:
            with self._db():
                self._bars.touch(symbol, now)
            return cached, recent.source

        if self._history_changed(cached, new):
            logger.info("%s: history re-adjusted at source; refetching all", symbol)
            full = self._provider.get_historical_data(symbol, Interval.D1)
            with self._db():
                self._bars.replace(symbol, full.source, full.bars, now)
                return self._bars.load(symbol), full.source

        with self._db():
            self._bars.upsert(symbol, recent.source, new, now)
            return self._bars.load(symbol), recent.source

    @staticmethod
    def _history_changed(cached: pd.DataFrame, new: pd.DataFrame) -> bool:
        """Did the source re-adjust past prices (split) or past adj_close (dividend)?"""
        after_cache = new[new.index > cached.index[-1]]
        if (after_cache["splits"] > 0).any() or (after_cache["dividends"] > 0).any():
            return True
        # Compare overlapping sessions except the last cached one, which may have
        # been a partial (in-progress) bar when it was stored.
        common = cached.index[:-1].intersection(new.index)
        if common.empty:
            return True  # no overlap to verify continuity
        old_close = cached.loc[common, "close"].to_numpy()
        new_close = new.loc[common, "close"].to_numpy()
        rel = np.abs(new_close - old_close) / np.maximum(np.abs(old_close), 1e-12)
        return bool((rel > OVERLAP_TOLERANCE).any())

    def _result(
        self,
        symbol: str,
        bars: pd.DataFrame,
        source: str,
        fetched_at: datetime | None,
        now: datetime,
        from_cache: bool,
        *,
        stale: bool = False,
        notices: tuple[str, ...] = (),
    ) -> LoadResult:
        last = None if bars.empty else bars.index[-1].date()
        series = BarSeries(symbol, Interval.D1, bars, source, tuple(notices))
        return LoadResult(
            series,
            fetched_at,
            from_cache,
            stale,
            session_in_progress(last, now) and not is_csv_symbol(symbol),
            tuple(notices),
        )

    # Watchlist rows ----------------------------------------------------------
    def snapshot(self, symbols: list[str]) -> list[WatchRow]:
        """Last close and daily change for each symbol (cache-first; never raises)."""
        rows: list[WatchRow] = []
        for symbol in symbols:
            try:
                result = self.load(symbol, Interval.D1)
            except Exception as exc:  # one bad symbol must not hide the others
                message = exc.user_message if isinstance(exc, AppError) else str(exc)
                logger.info("Watchlist row %s unavailable: %s", symbol, exc)
                rows.append(WatchRow(symbol, None, None, None, error=message))
                continue
            closes = result.series.bars["close"]
            last = float(closes.iloc[-1])
            previous = float(closes.iloc[-2]) if len(closes) > 1 else None
            change = (last / previous - 1.0) * 100.0 if previous else None
            rows.append(WatchRow(symbol, last, change, result.series.last_date, stale=result.stale))
        return rows

    # Details ---------------------------------------------------------------
    def details(self, raw_symbol: str) -> AssetDetails:
        """Details for the info panel: cached bars plus a live quote when reachable.

        Network failures never raise here: the bar-based values are returned with
        a notice explaining that live data is unavailable.
        """
        csv = is_csv_symbol(raw_symbol)
        symbol = raw_symbol.strip().upper() if csv else normalize_symbol(raw_symbol)
        with self._db():
            daily = self._bars.load(symbol)
            names = {r.symbol: r.name for r in self._recent.list(50)}
        fallback_name = names.get(symbol) if names.get(symbol) != symbol else None
        if csv:
            return build_details(symbol, daily, fallback_name=fallback_name)

        quote: Quote | None = None
        info: CompanyInfo | None = None
        notice: str | None = None
        try:
            quote = self._provider.get_quote(symbol)
            info = self._provider.get_company_info(symbol)
        except (NetworkError, ProviderError, DataError, UserError) as exc:
            logger.info("Live details for %s unavailable: %s", symbol, exc)
            notice = exc.user_message
        return build_details(symbol, daily, quote, info, fallback_name, notice)

    # CSV -------------------------------------------------------------------
    def import_csv(self, path: Path, name: str) -> LoadResult:
        label = name.strip().upper()
        if not label or len(label) > 30 or not all(ch.isalnum() or ch in "-_." for ch in label):
            raise UserError(
                f"invalid CSV series name {name!r}",
                user_message="El nombre debe tener entre 1 y 30 letras, números, '-', '_' o '.'.",
            )
        symbol = f"{CSV_PREFIX}{label}"
        bars, warnings = read_csv_bars(path, symbol)
        now = self._clock()
        with self._db():
            self._bars.replace(symbol, CSV_SOURCE, bars, now)
        logger.info("Imported %d bars from %s as %s", len(bars), path, symbol)
        return self._result(symbol, bars, CSV_SOURCE, now, now, False, notices=tuple(warnings))

    def _load_csv(self, raw_symbol: str) -> LoadResult:
        symbol = raw_symbol.strip().upper()
        with self._db():
            meta = self._bars.meta(symbol)
            bars = self._bars.load(symbol)
        if meta is None or bars.empty:
            raise UserError(
                f"{symbol} not imported",
                user_message=f"No hay datos importados con el nombre «{symbol}».",
            )
        return self._result(symbol, bars, meta.source, meta.fetched_at, self._clock(), True)
