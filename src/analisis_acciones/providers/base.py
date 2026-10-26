"""Provider-independent market-data interface.

Adapters translate a source's API into the domain models and map every failure
to the error taxonomy (UserError, NetworkError, DataError, ProviderError).
They never invent values: anything the source does not supply stays ``None``/NaN.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import date

from analisis_acciones.models.errors import UserError
from analisis_acciones.models.market import (
    BarSeries,
    CompanyInfo,
    Fundamentals,
    Interval,
    Quote,
    SearchResult,
)

_SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=]{0,14}$")


def normalize_symbol(raw: str) -> str:
    """Upper-case and validate a ticker; raises UserError when malformed."""
    symbol = raw.strip().upper()
    if not _SYMBOL.match(symbol):
        raise UserError(
            f"invalid symbol {raw!r}",
            user_message=f"«{raw.strip()}» no es un ticker válido.",
        )
    return symbol


class MarketDataProvider(ABC):
    #: Human-readable name shown in the status bar.
    name: str = "?"

    @abstractmethod
    def search_symbol(self, query: str, limit: int = 10) -> list[SearchResult]: ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Quote: ...

    @abstractmethod
    def get_historical_data(
        self, symbol: str, interval: Interval, start: date | None = None, end: date | None = None
    ) -> BarSeries:
        """Bars from ``start`` (inclusive) to ``end`` (inclusive); ``None`` = unbounded."""

    @abstractmethod
    def get_company_info(self, symbol: str) -> CompanyInfo: ...

    def get_fundamentals(self, symbol: str) -> Fundamentals:
        """Company figures; providers without them raise UserError."""
        raise UserError(
            f"{self.name} has no fundamentals",
            user_message=f"{self.name} no ofrece datos fundamentales.",
        )

    def get_currency(self, symbol: str) -> str | None:
        """Trading currency of ``symbol`` (ISO code as the source reports it), None if unknown."""
        return None

    def source_for(self, symbol: str, interval: Interval = Interval.D1) -> str:
        """Name of the source that serves ``symbol`` (cached data from another is refetched)."""
        return self.name

    @abstractmethod
    def get_available_intervals(self) -> list[Interval]:
        """Intervals this provider can return directly from get_historical_data()."""
