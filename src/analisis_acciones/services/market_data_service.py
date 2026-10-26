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
5. Intraday bars (1h, 15m) have their own cache, refreshed when older than a
   few minutes and merged with what is stored, so history accumulates beyond
   the provider's window (Yahoo: 60 days of 15m bars, 730 days of 1h bars).

All methods are blocking and thread-safe; the UI calls them from workers.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from analisis_acciones.data.csv_import import read_csv_bars
from analisis_acciones.data.details import AssetDetails, build_details
from analisis_acciones.data.freshness import (
    NEW_YORK,
    SESSION_CLOSE,
    is_crypto,
    needs_refresh,
    session_in_progress,
)
from analisis_acciones.data.resample import resample_daily
from analisis_acciones.models.errors import (
    AppError,
    DataError,
    InternalError,
    NetworkError,
    ProviderError,
    UserError,
)
from analisis_acciones.models.market import (
    AnnualFigures,
    BarSeries,
    CompanyInfo,
    Fundamentals,
    Interval,
    Quote,
    SearchResult,
)
from analisis_acciones.providers.base import MarketDataProvider, normalize_symbol
from analisis_acciones.providers.coingecko import CLOSE_ONLY_NOTE
from analisis_acciones.providers.coingecko import SOURCE_NAME as COINGECKO
from analisis_acciones.storage.bar_repository import BarRepository
from analisis_acciones.storage.intraday_repository import IntradayRepository
from analisis_acciones.storage.recent_repository import RecentSymbolRepository

logger = logging.getLogger(__name__)

CSV_PREFIX = "CSV:"
CSV_SOURCE = "Archivo CSV"
OVERLAP_DAYS = 30
OVERLAP_TOLERANCE = 1e-4  # relative difference in close prices
SEARCH_CACHE_TTL = timedelta(minutes=10)
DERIVED_INTERVALS = (Interval.W1, Interval.MN1)
#: Display order of intervals (shortest first).
INTERVAL_ORDER = (Interval.M1, Interval.M5, Interval.M15, Interval.M30, Interval.H1,
                  Interval.H4, Interval.D1, Interval.W1, Interval.MN1)  # fmt: skip
#: Intraday bar length and how long a cached intraday series counts as current.
INTRADAY_STEP = {Interval.H1: timedelta(hours=1), Interval.M15: timedelta(minutes=15)}
INTRADAY_REFRESH = {Interval.H1: timedelta(minutes=10), Interval.M15: timedelta(minutes=3)}
INTRADAY_OVERLAP_DAYS = 3


FUNDAMENTALS_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class FundamentalsResult:
    data: Fundamentals
    fetched_at: datetime
    stale: bool = False
    notice: str | None = None
    #: Dividends per share by calendar year, from the cached daily bars (oldest first).
    dividends: tuple[tuple[int, float], ...] = ()


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


#: Notices shown with every series of a source (what it lacks), also when served from cache.
SOURCE_NOTES = {COINGECKO: CLOSE_ONLY_NOTE}


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
        self._intraday = IntradayRepository(conn)
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
        return sorted({*native, *derived}, key=INTERVAL_ORDER.index)

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
        if interval.is_intraday:
            return self._load_intraday(symbol, interval)
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

    def _load_intraday(self, raw_symbol: str, interval: Interval) -> LoadResult:
        if is_csv_symbol(raw_symbol) or interval not in INTRADAY_STEP:
            raise UserError(
                f"intraday not available for {raw_symbol}",
                user_message="Los intervalos intradía solo están disponibles para tickers de "
                "Yahoo Finance (no para series importadas de CSV).",
            )
        symbol = normalize_symbol(raw_symbol)
        now = self._clock()
        with self._db():
            meta = self._intraday.meta(symbol, interval.value)
            cached = self._intraday.load(symbol, interval.value)
        have_cache = meta is not None and not cached.empty
        if have_cache and meta is not None and now - meta.fetched_at < INTRADAY_REFRESH[interval]:
            return self._intraday_result(symbol, interval, cached, meta.source, meta.fetched_at,
                                         now, True)  # fmt: skip
        start = cached.index[-1].date() - timedelta(days=INTRADAY_OVERLAP_DAYS) \
            if have_cache else None  # fmt: skip
        try:
            series = self._provider.get_historical_data(symbol, interval, start=start)
        except (NetworkError, ProviderError, DataError) as exc:
            if not have_cache or meta is None:
                raise
            logger.warning("Intraday refresh of %s failed, serving cache: %s", symbol, exc)
            return self._intraday_result(symbol, interval, cached, meta.source,
                                         meta.fetched_at, now, True, stale=True,
                                         notices=(exc.user_message,))  # fmt: skip
        new = series.bars
        # A split re-adjusts past prices at the source: then the stored series is replaced.
        replace = not have_cache or (not new.empty and self._intraday_rescaled(cached, new))
        with self._db():
            if new.empty:
                self._intraday.touch(symbol, interval.value, series.source, now)
            else:
                self._intraday.upsert(symbol, interval.value, series.source, new, now,
                                      replace=replace)  # fmt: skip
            bars = self._intraday.load(symbol, interval.value)
        if bars.empty:
            raise DataError(f"{symbol}: no intraday bars",
                            user_message=f"No hay datos intradía para {symbol}.")  # fmt: skip
        return self._intraday_result(symbol, interval, bars, series.source, now, now, False,
                                     notices=series.warnings)  # fmt: skip

    @staticmethod
    def _intraday_result(
        symbol: str, interval: Interval, bars: pd.DataFrame, source: str,
        fetched_at: datetime | None, now: datetime, from_cache: bool, *,
        stale: bool = False, notices: tuple[str, ...] = (),
    ) -> LoadResult:  # fmt: skip
        series = BarSeries(symbol, interval, bars, source, tuple(notices))
        last = pd.Timestamp(bars.index[-1]).to_pydatetime() if not bars.empty else None
        in_progress = intraday_bar_in_progress(last, interval, now, is_crypto(symbol))
        return LoadResult(series, fetched_at, from_cache, stale, in_progress, tuple(notices))

    @staticmethod
    def _intraday_rescaled(cached: pd.DataFrame, new: pd.DataFrame) -> bool:
        """Do overlapping closes differ (split re-adjustment)? The last cached bar may
        have been partial, so it is not compared. No overlap is not a change."""
        common = cached.index[:-1].intersection(new.index)
        if common.empty:
            return False
        old = cached.loc[common, "close"].to_numpy()
        rel = np.abs(new.loc[common, "close"].to_numpy() - old) / np.maximum(np.abs(old), 1e-12)
        return bool((rel > OVERLAP_TOLERANCE).any())

    def _load_daily(self, raw_symbol: str) -> LoadResult:
        if is_csv_symbol(raw_symbol):
            return self._load_csv(raw_symbol)
        symbol = normalize_symbol(raw_symbol)
        now = self._clock()
        with self._db():
            meta = self._bars.meta(symbol)
            cached = self._bars.load(symbol) if meta else None

        if meta is not None and meta.source != self._provider.source_for(symbol):
            # The source was changed (e.g. Yahoo -> CoinGecko for crypto): never mix the two.
            logger.info("%s: source changed from %s; refetching", symbol, meta.source)
            meta, cached = None, None
        if meta is not None and cached is not None and not cached.empty:
            if not needs_refresh(meta.fetched_at, now, is_crypto(symbol)):
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
        note = SOURCE_NOTES.get(source)
        if note and note not in notices:
            notices = (note, *notices)
        series = BarSeries(symbol, Interval.D1, bars, source, tuple(notices))
        return LoadResult(
            series,
            fetched_at,
            from_cache,
            stale,
            session_in_progress(last, now, is_crypto(symbol)) and not is_csv_symbol(symbol),
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

    # Fundamentals ------------------------------------------------------------
    def currency(self, raw_symbol: str) -> str | None:
        """Trading currency (cached once known; it practically never changes). None if unknown."""
        if is_csv_symbol(raw_symbol):
            return None
        symbol = normalize_symbol(raw_symbol)
        with self._db():
            row = self._conn.execute(
                "SELECT currency FROM symbol_currency WHERE symbol = ?", (symbol,)
            ).fetchone()
        if row:
            return str(row["currency"])
        try:
            currency = self._provider.get_currency(symbol)
        except AppError as exc:
            logger.info("Currency of %s unknown: %s", symbol, exc)
            return None
        if currency:
            with self._db():
                self._conn.execute(
                    "INSERT OR REPLACE INTO symbol_currency (symbol, currency, fetched_at) "
                    "VALUES (?, ?, ?)",
                    (symbol, currency, self._clock().isoformat()),
                )
        return currency

    def cached_fundamentals(self, symbols: list[str]) -> dict[str, Fundamentals]:
        """Stored fundamentals only (no network), for overviews such as the day summary."""
        found: dict[str, Fundamentals] = {}
        with self._db():
            for symbol in symbols:
                row = self._conn.execute(
                    "SELECT payload FROM fundamentals_cache WHERE symbol = ?", (symbol,)
                ).fetchone()
                data = _fundamentals_from_json(row["payload"]) if row else None
                if data is not None:
                    found[symbol] = data
        return found

    def fundamentals(self, raw_symbol: str) -> FundamentalsResult:
        """Company figures, refreshed daily; the last stored copy is served when offline."""
        if is_csv_symbol(raw_symbol):
            raise UserError(
                "no fundamentals for CSV",
                user_message="No hay datos fundamentales para series importadas.",
            )
        symbol = normalize_symbol(raw_symbol)
        if is_crypto(symbol):
            raise UserError(
                "no fundamentals for crypto",
                user_message="Las criptomonedas no tienen datos fundamentales de empresa "
                "(beneficios, PER, márgenes ni dividendos).",
            )
        now = self._clock()
        with self._db():
            row = self._conn.execute(
                "SELECT fetched_at, payload FROM fundamentals_cache WHERE symbol = ?", (symbol,)
            ).fetchone()
            daily = self._bars.load(symbol)
        cached = _fundamentals_from_json(row["payload"]) if row else None
        fetched = datetime.fromisoformat(row["fetched_at"]) if row else None
        dividends = annual_dividends(daily)
        if cached is not None and fetched is not None and now - fetched < FUNDAMENTALS_TTL:
            return FundamentalsResult(cached, fetched, dividends=dividends)
        try:
            data = self._provider.get_fundamentals(symbol)
        except (NetworkError, ProviderError) as exc:
            if cached is None or fetched is None:
                raise
            return FundamentalsResult(cached, fetched, True, exc.user_message, dividends)
        with self._db():
            self._conn.execute(
                "INSERT INTO fundamentals_cache (symbol, fetched_at, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(symbol) DO UPDATE SET fetched_at = excluded.fetched_at, "
                "payload = excluded.payload",
                (symbol, now.isoformat(), json.dumps(asdict(data), allow_nan=False, default=_iso)),
            )
        return FundamentalsResult(data, now, dividends=dividends)

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


def intraday_bar_in_progress(last_start: datetime | None, interval: Interval,
                             now: datetime, crypto: bool = False) -> bool:  # fmt: skip
    """Is the bar starting at ``last_start`` (exchange wall time) still being formed?

    A stock bar (New York time) ends ``interval`` later or at the 16:00 close,
    whichever is first; a crypto bar (UTC, round the clock) ends ``interval`` later.
    """
    if last_start is None or interval not in INTRADAY_STEP:
        return False
    if crypto:
        return now.astimezone(UTC).replace(tzinfo=None) < last_start + INTRADAY_STEP[interval]
    close = datetime.combine(last_start.date(), SESSION_CLOSE)
    end = min(last_start + INTRADAY_STEP[interval], close)
    return now.astimezone(NEW_YORK).replace(tzinfo=None) < end


def annual_dividends(daily: pd.DataFrame) -> tuple[tuple[int, float], ...]:
    """Dividends per share summed per calendar year (years with none are left out)."""
    if daily.empty or "dividends" not in daily:
        return ()
    paid = daily["dividends"][daily["dividends"] > 0]
    if paid.empty:
        return ()
    years = pd.DatetimeIndex(paid.index).year
    by_year = paid.groupby(years).sum()
    return tuple(
        (int(year), float(total)) for year, total in zip(by_year.index, by_year, strict=True)
    )


DATE_FIELDS = ("earnings_date", "earnings_date_end", "ex_dividend_date", "dividend_payment_date")


def _iso(value: object) -> str:
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"not serializable: {type(value).__name__}")


def _fundamentals_from_json(payload: str) -> Fundamentals | None:
    """Rebuild stored fundamentals; anything malformed is treated as not cached."""
    try:
        raw = json.loads(payload)
        annual = tuple(AnnualFigures(**item) for item in raw.pop("annual", []))
        for key in DATE_FIELDS:
            if raw.get(key) is not None:
                raw[key] = date.fromisoformat(raw[key])
        return Fundamentals(**raw, annual=annual)
    except (ValueError, TypeError):
        logger.warning("Ignoring malformed cached fundamentals")
        return None
