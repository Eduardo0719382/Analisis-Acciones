"""Build the asset-details summary from cached bars plus (optional) live quote data.

Bar-derived values are always available offline and are fully reproducible.
Quote/company data from the provider are used only when the request
succeeded; nothing is estimated when a value is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta

import pandas as pd

from analisis_acciones.models.market import CompanyInfo, Quote

#: Minimum history (calendar days) needed to compute a 52-week range from bars.
FIFTY_TWO_WEEKS = timedelta(days=365)


@dataclass(frozen=True)
class AssetDetails:
    symbol: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    sector: str | None = None
    industry: str | None = None
    price: float | None = None
    previous_close: float | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    #: "quote" when price fields come from the provider's live quote,
    #: "bars" when they come from the last cached daily bar.
    price_source: str = "bars"
    #: Date of the last bar, or the quote timestamp.
    as_of: date | datetime | None = None
    market_state: str | None = None
    #: Source of the live quote (e.g. "Finnhub"), when known.
    quote_source: str | None = None
    #: Reason live data could not be fetched (shown to the user), if any.
    notice: str | None = None

    @property
    def change(self) -> float | None:
        if self.price is None or self.previous_close is None:
            return None
        return self.price - self.previous_close

    @property
    def change_pct(self) -> float | None:
        change = self.change
        if change is None or not self.previous_close:
            return None
        return change / self.previous_close * 100.0


def _value(series: pd.Series, position: int) -> float | None:
    if len(series) < abs(position):
        return None
    value = series.iloc[position]
    return None if pd.isna(value) else float(value)


def week52_range(daily: pd.DataFrame) -> tuple[float | None, float | None]:
    """High/low over the 365 calendar days ending at the last bar (needs a full year)."""
    if daily.empty:
        return None, None
    last = pd.Timestamp(daily.index[-1])
    start = last - FIFTY_TWO_WEEKS
    if pd.Timestamp(daily.index[0]) > start:
        return None, None  # history shorter than 52 weeks: do not pretend
    window = daily[daily.index > start]
    return float(window["high"].max()), float(window["low"].min())


def build_details(
    symbol: str,
    daily: pd.DataFrame,
    quote: Quote | None = None,
    info: CompanyInfo | None = None,
    fallback_name: str | None = None,
    notice: str | None = None,
) -> AssetDetails:
    high52, low52 = week52_range(daily)
    if high52 is None and info is not None:
        high52, low52 = info.fifty_two_week_high, info.fifty_two_week_low

    base = AssetDetails(
        symbol=symbol,
        name=(info.name if info else None) or fallback_name,
        exchange=info.exchange if info else None,
        currency=(quote.currency if quote else None) or (info.currency if info else None),
        sector=info.sector if info else None,
        industry=info.industry if info else None,
        week52_high=high52,
        week52_low=low52,
        notice=notice,
    )

    if quote is not None and quote.price is not None:
        return replace(
            base,
            price=quote.price,
            previous_close=quote.previous_close,
            open=quote.open,
            high=quote.day_high,
            low=quote.day_low,
            volume=quote.volume,
            price_source="quote",
            as_of=quote.as_of,
            market_state=quote.market_state,
            quote_source=quote.source,
        )

    if daily.empty:
        return base
    last = daily.iloc[-1]
    return replace(
        base,
        price=float(last["close"]),
        previous_close=_value(daily["close"], -2),
        open=float(last["open"]),
        high=float(last["high"]),
        low=float(last["low"]),
        volume=None if pd.isna(last["volume"]) else float(last["volume"]),
        price_source="bars",
        as_of=pd.Timestamp(daily.index[-1]).date(),
    )
