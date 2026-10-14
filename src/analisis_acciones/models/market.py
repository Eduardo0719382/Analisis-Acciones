"""Market-data domain models.

Bars are carried as a pandas DataFrame with a fixed schema (see ``BAR_COLUMNS``):

* index: ``DatetimeIndex`` named ``date``. For daily and longer intervals each
  label is the session date (tz-naive, exchange-local calendar date).
* ``open``, ``high``, ``low``, ``close``: prices as reported by the source.
  For Yahoo these are already split-adjusted, not dividend-adjusted.
* ``adj_close``: split- and dividend-adjusted close (NaN when unknown).
* ``volume``: shares traded (NaN when the source has no volume; never 0-filled).
* ``dividends``, ``splits``: corporate-action amounts on that date (0 = none).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

import pandas as pd

PRICE_COLUMNS = ("open", "high", "low", "close")
BAR_COLUMNS = (*PRICE_COLUMNS, "adj_close", "volume", "dividends", "splits")


class Interval(StrEnum):
    """Bar intervals. Only those a provider reports as available are shown."""

    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1D"
    W1 = "1W"
    MN1 = "1M"

    @property
    def is_intraday(self) -> bool:
        return self not in (Interval.D1, Interval.W1, Interval.MN1)


@dataclass(frozen=True)
class SearchResult:
    symbol: str
    name: str
    exchange: str = ""
    asset_type: str = ""


@dataclass(frozen=True)
class Quote:
    symbol: str
    price: float | None
    previous_close: float | None
    open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: float | None = None
    currency: str | None = None
    market_state: str | None = None
    as_of: datetime | None = None

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


@dataclass(frozen=True)
class CompanyInfo:
    symbol: str
    name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    sector: str | None = None
    industry: str | None = None
    fifty_two_week_high: float | None = None
    fifty_two_week_low: float | None = None


@dataclass(frozen=True)
class BarSeries:
    symbol: str
    interval: Interval
    bars: pd.DataFrame
    source: str
    warnings: tuple[str, ...] = field(default=())

    def __len__(self) -> int:
        return len(self.bars)

    @property
    def first_date(self) -> date | None:
        return None if self.bars.empty else self.bars.index[0].date()

    @property
    def last_date(self) -> date | None:
        return None if self.bars.empty else self.bars.index[-1].date()


def empty_bars() -> pd.DataFrame:
    frame = pd.DataFrame({c: pd.Series(dtype="float64") for c in BAR_COLUMNS})
    frame.index = pd.DatetimeIndex([], name="date")
    return frame


@dataclass(frozen=True)
class AnnualFigures:
    year: int  # fiscal year (year of the period end)
    revenue: float | None = None
    net_income: float | None = None
    operating_income: float | None = None
    eps: float | None = None  # diluted earnings per share


@dataclass(frozen=True)
class Fundamentals:
    """Company figures as reported by the data source. Missing values stay None."""

    symbol: str
    currency: str | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    trailing_eps: float | None = None
    price_to_book: float | None = None
    dividend_rate: float | None = None  # annual dividend per share
    dividend_yield: float | None = None  # fraction (0.02 = 2 %)
    payout_ratio: float | None = None  # fraction
    profit_margin: float | None = None  # fraction
    operating_margin: float | None = None  # fraction
    return_on_equity: float | None = None  # fraction
    revenue_growth: float | None = None  # fraction, year over year
    earnings_growth: float | None = None  # fraction, year over year
    beta: float | None = None
    annual: tuple[AnnualFigures, ...] = ()  # oldest first
    # Calendar as published by the source (may be past dates; the source can change them).
    earnings_date: date | None = None  # next results date, or start of the expected window
    earnings_date_end: date | None = None  # end of the window when it is a range
    earnings_estimated: bool | None = None  # True = not yet confirmed by the company
    ex_dividend_date: date | None = None  # latest announced ex-dividend date
    dividend_payment_date: date | None = None
