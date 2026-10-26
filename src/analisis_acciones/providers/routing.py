"""Choose the price source per kind of asset at each call.

Stocks/funds and cryptocurrencies each have a chosen source (read from the settings at every
call, so a change applies at once). CSV series, indices and currency pairs, and any
interval the chosen source does not offer (intraday), always use the primary source
(Yahoo Finance). Search always uses the primary source too.

Automatic fallback (optional, on by default): when a whole daily history cannot be loaded
from the chosen source, the primary source and then the configured alternatives are
tried, and the series says plainly which source answered and why. Partial refreshes never
fall back, so one cached series is never built from two sources. A live quote falls back
the same way. With a Finnhub key, quotes of US stocks can come from Finnhub in real time.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date

from analisis_acciones.data.freshness import is_crypto
from analisis_acciones.models.errors import AppError, DataError, NetworkError, ProviderError
from analisis_acciones.models.market import (
    BarSeries,
    CompanyInfo,
    Fundamentals,
    Interval,
    Quote,
    SearchResult,
)
from analisis_acciones.providers.base import MarketDataProvider

logger = logging.getLogger(__name__)
#: Failures of the primary source that justify asking another one. A "not found" from
#: Yahoo is not one of them (another source would only spend the user's free quota).
TRANSIENT = (NetworkError, ProviderError, DataError)


def plain_stock(symbol: str) -> bool:
    """US stock/ETF ticker (not an index ``^GSPC``, currency ``EURUSD=X`` or crypto pair)."""
    s = symbol.strip().upper()
    return bool(s) and not is_crypto(s) and not s.startswith("^") and "=" not in s \
        and not s.startswith("CSV:")  # fmt: skip


class SourceRouter(MarketDataProvider):
    def __init__(
        self,
        primary: MarketDataProvider,
        sources: Mapping[str, MarketDataProvider],
        stock_source: Callable[[], str],
        crypto_source: Callable[[], str],
        *,
        fallback: Callable[[], bool] = lambda: False,
        stock_fallbacks: Sequence[str] = (),
        crypto_fallbacks: Sequence[str] = (),
        quote_source: Callable[[], str | None] = lambda: None,
    ) -> None:
        self._primary = primary
        self._sources = dict(sources)
        self._stock = stock_source
        self._crypto = crypto_source
        self._fallback = fallback
        self._stock_fallbacks = tuple(stock_fallbacks)
        self._crypto_fallbacks = tuple(crypto_fallbacks)
        self._quote_source = quote_source
        self.name = primary.name

    def provider_for(self, symbol: str, interval: Interval = Interval.D1) -> MarketDataProvider:
        if is_crypto(symbol):
            chosen = self._sources.get(self._crypto())
        elif plain_stock(symbol):
            chosen = self._sources.get(self._stock())
        else:
            chosen = None
        if chosen is not None and interval in chosen.get_available_intervals():
            return chosen
        return self._primary

    def source_for(self, symbol: str, interval: Interval = Interval.D1) -> str:
        return self.provider_for(symbol, interval).name

    def get_available_intervals(self) -> list[Interval]:
        return self._primary.get_available_intervals()

    def alternatives(self, symbol: str, interval: Interval,
                     chosen: MarketDataProvider) -> list[MarketDataProvider]:  # fmt: skip
        """Sources to try, in order, when ``chosen`` fails (none for indices, FX, CSV)."""
        if is_crypto(symbol):
            keys = self._crypto_fallbacks
        elif plain_stock(symbol):
            keys = self._stock_fallbacks
        else:
            return []
        out = [self._primary] if chosen is not self._primary else []
        for key in keys:
            alt = self._sources.get(key)
            if alt is not None and alt is not chosen and alt not in out \
                    and interval in alt.get_available_intervals():  # fmt: skip
                out.append(alt)
        return out

    def _worth_retrying(self, chosen: MarketDataProvider, exc: AppError) -> bool:
        # Any failure of an optional source (missing key, plan limits, symbol it lacks)
        # sends the request to Yahoo; Yahoo itself only on transient failures.
        return self._fallback() and (chosen is not self._primary or isinstance(exc, TRANSIENT))

    def get_historical_data(
        self, symbol: str, interval: Interval, start: date | None = None, end: date | None = None
    ) -> BarSeries:
        chosen = self.provider_for(symbol, interval)
        try:
            return chosen.get_historical_data(symbol, interval, start, end)
        except AppError as exc:
            if start is not None or not self._worth_retrying(chosen, exc):
                raise
            for alt in self.alternatives(symbol, interval, chosen):
                try:
                    series = alt.get_historical_data(symbol, interval, start, end)
                except AppError as alt_exc:
                    logger.info("Fallback %s for %s failed: %s", alt.name, symbol, alt_exc)
                    continue
                logger.info("%s: %s failed (%s); served by %s", symbol, chosen.name, exc,
                            alt.name)  # fmt: skip
                note = fallback_note(chosen.name, alt.name, exc.user_message)
                return replace(series, warnings=(note, *series.warnings))
            raise

    def search_symbol(self, query: str, limit: int = 10) -> list[SearchResult]:
        return self._primary.search_symbol(query, limit)

    def get_quote(self, symbol: str) -> Quote:
        chosen = self.provider_for(symbol)
        realtime = self._sources.get(self._quote_source() or "")
        if realtime is not None and plain_stock(symbol) and realtime is not chosen:
            try:
                return replace(realtime.get_quote(symbol), source=realtime.name)
            except AppError as exc:  # the regular quote is still available
                logger.info("Real-time quote of %s from %s failed: %s", symbol, realtime.name,
                            exc)  # fmt: skip
        try:
            return replace(chosen.get_quote(symbol), source=chosen.name)
        except AppError as exc:
            if not self._worth_retrying(chosen, exc):
                raise
            for alt in self.alternatives(symbol, Interval.D1, chosen):
                try:
                    return replace(alt.get_quote(symbol), source=alt.name)
                except AppError:
                    continue
            raise

    def get_company_info(self, symbol: str) -> CompanyInfo:
        return self.provider_for(symbol).get_company_info(symbol)

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        return self._primary.get_fundamentals(symbol)

    def get_currency(self, symbol: str) -> str | None:
        return self.provider_for(symbol).get_currency(symbol)


def fallback_note(chosen: str, used: str, reason: str) -> str:
    return f"{chosen} no pudo dar estos datos ({reason.rstrip('.')}). Se usaron los de {used}."
