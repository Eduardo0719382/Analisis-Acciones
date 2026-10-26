"""Choose the price source per kind of asset at each call.

Stocks/funds and cryptocurrencies each have a chosen source (read from the settings at every
call, so a change applies at once). CSV series, indices and currency pairs, and any
interval the chosen source does not offer (intraday), always use the primary source
(Yahoo Finance). Search always uses the primary source too.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date

from analisis_acciones.data.freshness import is_crypto
from analisis_acciones.models.market import (
    BarSeries,
    CompanyInfo,
    Fundamentals,
    Interval,
    Quote,
    SearchResult,
)
from analisis_acciones.providers.base import MarketDataProvider


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
    ) -> None:
        self._primary = primary
        self._sources = dict(sources)
        self._stock = stock_source
        self._crypto = crypto_source
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

    def get_historical_data(
        self, symbol: str, interval: Interval, start: date | None = None, end: date | None = None
    ) -> BarSeries:
        return self.provider_for(symbol, interval).get_historical_data(symbol, interval, start, end)

    def search_symbol(self, query: str, limit: int = 10) -> list[SearchResult]:
        return self._primary.search_symbol(query, limit)

    def get_quote(self, symbol: str) -> Quote:
        return self.provider_for(symbol).get_quote(symbol)

    def get_company_info(self, symbol: str) -> CompanyInfo:
        return self.provider_for(symbol).get_company_info(symbol)

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        return self._primary.get_fundamentals(symbol)

    def get_currency(self, symbol: str) -> str | None:
        return self.provider_for(symbol).get_currency(symbol)
