"""Yahoo Finance adapter (via the unofficial ``yfinance`` library).

Notes on the source (see DECISIONS.md D-003/D-004):

* Daily OHLC from Yahoo are split-adjusted but not dividend-adjusted;
  ``Adj Close`` is adjusted for both. Truly raw prices are not available.
* ``yfinance`` uses a shared session with cookies, so calls are serialised.
* All yfinance access goes through ``YahooClient`` so tests can substitute it.
"""

from __future__ import annotations

import logging
import math
import threading
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import pandas as pd

from analisis_acciones.data.validation import validate_bars
from analisis_acciones.models.errors import AppError, NetworkError, ProviderError, UserError
from analisis_acciones.models.market import (
    BarSeries,
    CompanyInfo,
    Interval,
    Quote,
    SearchResult,
    empty_bars,
)
from analisis_acciones.providers.base import MarketDataProvider, normalize_symbol

logger = logging.getLogger(__name__)

SOURCE_NAME = "Yahoo Finance"
REQUEST_TIMEOUT_S = 20
SUPPORTED_ASSET_TYPES = {"EQUITY", "ETF"}

_COLUMN_MAP = {
    "Open": "open",
    "High": "high",
    "Low": "low",
    "Close": "close",
    "Adj Close": "adj_close",
    "Volume": "volume",
    "Dividends": "dividends",
    "Stock Splits": "splits",
}
_NETWORK_ERROR_NAMES = {
    "ConnectionError",
    "ConnectTimeout",
    "ReadTimeout",
    "Timeout",
    "TimeoutError",
    "ProxyError",
    "SSLError",
    "DNSError",
}


class YahooClient(Protocol):
    def history(self, symbol: str, start: date | None, end: date | None) -> pd.DataFrame: ...
    def search(self, query: str, limit: int) -> list[dict[str, Any]]: ...
    def info(self, symbol: str) -> dict[str, Any]: ...


class YFinanceClient:
    """Thin wrapper over yfinance; the only place that imports it."""

    def history(self, symbol: str, start: date | None, end: date | None) -> pd.DataFrame:
        import yfinance as yf

        kwargs: dict[str, Any] = {
            "interval": "1d",
            "auto_adjust": False,
            "actions": True,
            "repair": False,
            "timeout": REQUEST_TIMEOUT_S,
            "raise_errors": True,
        }
        if start is None:
            kwargs["period"] = "max"
        else:
            kwargs["start"] = start.isoformat()
            # yfinance's end is exclusive.
            kwargs["end"] = ((end or date.today()) + timedelta(days=1)).isoformat()
        frame: pd.DataFrame = yf.Ticker(symbol).history(**kwargs)
        return frame

    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        import yfinance as yf

        result = yf.Search(
            query,
            max_results=limit,
            news_count=0,
            lists_count=0,
            include_cb=False,
            timeout=REQUEST_TIMEOUT_S,
            raise_errors=True,
        )
        return list(result.quotes)

    def info(self, symbol: str) -> dict[str, Any]:
        import yfinance as yf

        return dict(yf.Ticker(symbol).info or {})


def _num(value: object) -> float | None:
    """Accept only finite numbers from external data; anything else is unknown."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _first_num(info: dict[str, Any], *keys: str) -> float | None:
    """First key holding a valid number (0 counts as a value, unlike ``or``)."""
    for key in keys:
        number = _num(info.get(key))
        if number is not None:
            return number
    return None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _not_found(symbol: str) -> UserError:
    return UserError(
        f"{symbol}: not found at Yahoo Finance",
        user_message=f"No se encontraron datos para «{symbol}». Compruebe el ticker.",
    )


def map_yahoo_error(exc: Exception, symbol: str) -> AppError:
    if isinstance(exc, AppError):
        return exc
    names = {cls.__name__ for cls in type(exc).__mro__}
    if "YFRateLimitError" in names:
        return ProviderError(
            f"Yahoo rate limit: {exc}",
            user_message="Yahoo Finance ha limitado las peticiones. Espere unos minutos.",
        )
    if names & {"YFPricesMissingError", "YFTickerMissingError", "YFTzMissingError"}:
        return _not_found(symbol)
    if names & _NETWORK_ERROR_NAMES or isinstance(exc, ConnectionError | TimeoutError):
        return NetworkError(f"Yahoo network error for {symbol}: {exc!r}")
    return ProviderError(f"Yahoo error for {symbol}: {exc!r}")


class YahooFinanceProvider(MarketDataProvider):
    name = SOURCE_NAME

    def __init__(self, client: YahooClient | None = None) -> None:
        self._client: YahooClient = client or YFinanceClient()
        self._lock = threading.Lock()

    def get_available_intervals(self) -> list[Interval]:
        # MVP: end-of-day only (PLAN.md Q5). Weekly/monthly are built from daily.
        return [Interval.D1]

    def get_historical_data(
        self, symbol: str, interval: Interval, start: date | None = None, end: date | None = None
    ) -> BarSeries:
        symbol = normalize_symbol(symbol)
        if interval not in self.get_available_intervals():
            raise UserError(
                f"interval {interval} not supported by Yahoo provider",
                user_message=f"El intervalo {interval.value} no está disponible.",
            )
        try:
            with self._lock:
                raw = self._client.history(symbol, start, end)
        except Exception as exc:
            mapped = map_yahoo_error(exc, symbol)
            if start is not None and isinstance(mapped, UserError):
                # A bounded request with no rows (weekend, holiday) is not an error.
                return BarSeries(symbol, interval, empty_bars(), SOURCE_NAME)
            if isinstance(mapped, UserError):
                raise self._confirm_not_found(symbol) from exc
            raise mapped from exc

        if raw is None or raw.empty:
            if start is not None:
                return BarSeries(symbol, interval, empty_bars(), SOURCE_NAME)
            raise self._confirm_not_found(symbol)

        frame = raw.rename(columns=_COLUMN_MAP)
        index = pd.DatetimeIndex(frame.index)
        if index.tz is not None:
            # Daily bars are stamped at exchange-local midnight: keep the calendar date.
            index = index.tz_localize(None)
        frame.index = index.normalize()
        bars, warnings = validate_bars(frame, symbol)
        if end is not None:
            bars = bars[bars.index <= pd.Timestamp(end)]
        return BarSeries(symbol, interval, bars, SOURCE_NAME, tuple(warnings))

    def _confirm_not_found(self, symbol: str) -> AppError:
        """Tell "unknown ticker" apart from "no connection".

        When offline, yfinance may report a missing ticker ("possibly delisted;
        no timezone found") instead of a network error. A cheap search request
        shows whether Yahoo is reachable at all.
        """
        try:
            with self._lock:
                self._client.search(symbol, 1)
        except Exception as exc:
            mapped = map_yahoo_error(exc, symbol)
            if isinstance(mapped, NetworkError | ProviderError):
                return mapped
        return _not_found(symbol)

    def search_symbol(self, query: str, limit: int = 10) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        if len(query) > 64:
            raise UserError("search query too long", user_message="La búsqueda es demasiado larga.")
        try:
            with self._lock:
                quotes = self._client.search(query, limit * 2)
        except Exception as exc:
            raise map_yahoo_error(exc, query) from exc

        results: list[SearchResult] = []
        for item in quotes:
            if not isinstance(item, dict):
                continue
            symbol = _text(item.get("symbol"))
            asset_type = _text(item.get("quoteType")) or ""
            # US listings only (PLAN.md Q4): Yahoo marks foreign listings with a suffix.
            if not symbol or "." in symbol or asset_type not in SUPPORTED_ASSET_TYPES:
                continue
            name = _text(item.get("longname")) or _text(item.get("shortname")) or symbol
            exchange = _text(item.get("exchDisp")) or _text(item.get("exchange")) or ""
            results.append(SearchResult(symbol.upper(), name, exchange, asset_type))
            if len(results) >= limit:
                break
        return results

    def _info(self, symbol: str) -> dict[str, Any]:
        try:
            with self._lock:
                info = self._client.info(symbol)
        except Exception as exc:
            raise map_yahoo_error(exc, symbol) from exc
        if not isinstance(info, dict):
            raise ProviderError(f"{symbol}: unexpected info payload {type(info)}")
        return info

    def get_quote(self, symbol: str) -> Quote:
        symbol = normalize_symbol(symbol)
        info = self._info(symbol)
        price = _first_num(info, "regularMarketPrice", "currentPrice")
        if price is None:
            raise self._confirm_not_found(symbol)
        timestamp = _num(info.get("regularMarketTime"))
        return Quote(
            symbol=symbol,
            price=price,
            previous_close=_first_num(info, "regularMarketPreviousClose", "previousClose"),
            open=_first_num(info, "regularMarketOpen", "open"),
            day_high=_first_num(info, "regularMarketDayHigh", "dayHigh"),
            day_low=_first_num(info, "regularMarketDayLow", "dayLow"),
            volume=_first_num(info, "regularMarketVolume", "volume"),
            currency=_text(info.get("currency")),
            market_state=_text(info.get("marketState")),
            as_of=datetime.fromtimestamp(timestamp, tz=UTC) if timestamp else None,
        )

    def get_company_info(self, symbol: str) -> CompanyInfo:
        symbol = normalize_symbol(symbol)
        info = self._info(symbol)
        name = _text(info.get("longName")) or _text(info.get("shortName"))
        if name is None and _num(info.get("regularMarketPrice")) is None:
            raise self._confirm_not_found(symbol)
        return CompanyInfo(
            symbol=symbol,
            name=name,
            exchange=_text(info.get("fullExchangeName")) or _text(info.get("exchange")),
            currency=_text(info.get("currency")),
            sector=_text(info.get("sector")),
            industry=_text(info.get("industry")),
            fifty_two_week_high=_num(info.get("fiftyTwoWeekHigh")),
            fifty_two_week_low=_num(info.get("fiftyTwoWeekLow")),
        )
