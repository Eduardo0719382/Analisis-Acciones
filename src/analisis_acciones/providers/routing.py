"""Choose the price source for cryptocurrencies (Yahoo Finance or CoinGecko) at each call.

Stocks, funds and indices always come from the primary source (Yahoo). For crypto pairs,
``use_coingecko()`` decides; it is read on every call so a change in the settings applies
at once. CoinGecko has daily data only, so intraday crypto bars still come from Yahoo.
"""

from __future__ import annotations

from collections.abc import Callable
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


class CryptoSourceRouter(MarketDataProvider):
    def __init__(self, primary: MarketDataProvider, crypto: MarketDataProvider,
                 use_crypto_source: Callable[[], bool]) -> None:  # fmt: skip
        self._primary = primary
        self._crypto = crypto
        self._use = use_crypto_source
        self.name = primary.name

    def _for(self, symbol: str, interval: Interval = Interval.D1) -> MarketDataProvider:
        if (is_crypto(symbol) and self._use()
                and interval in self._crypto.get_available_intervals()):  # fmt: skip
            return self._crypto
        return self._primary

    def source_for(self, symbol: str, interval: Interval = Interval.D1) -> str:
        return self._for(symbol, interval).name

    def get_available_intervals(self) -> list[Interval]:
        return self._primary.get_available_intervals()

    def get_historical_data(
        self, symbol: str, interval: Interval, start: date | None = None, end: date | None = None
    ) -> BarSeries:
        return self._for(symbol, interval).get_historical_data(symbol, interval, start, end)

    def search_symbol(self, query: str, limit: int = 10) -> list[SearchResult]:
        return self._primary.search_symbol(query, limit)

    def get_quote(self, symbol: str) -> Quote:
        return self._for(symbol).get_quote(symbol)

    def get_company_info(self, symbol: str) -> CompanyInfo:
        return self._for(symbol).get_company_info(symbol)

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        return self._primary.get_fundamentals(symbol)

    def get_currency(self, symbol: str) -> str | None:
        return self._for(symbol).get_currency(symbol)
