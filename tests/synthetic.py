"""Deterministic SYNTHETIC market data for tests.

These numbers are generated, not real prices. They only exercise parsing,
validation, caching and resampling logic.
"""

from __future__ import annotations

import itertools
from datetime import date

import numpy as np
import pandas as pd


def synthetic_daily(start: str = "2024-01-01", sessions: int = 300, seed: int = 7) -> pd.DataFrame:
    """Canonical-schema daily bars on weekdays (business days)."""
    rng = np.random.default_rng(seed)
    index = pd.bdate_range(start=start, periods=sessions, name="date")
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, sessions)))
    open_ = np.concatenate([[100.0], close[:-1]]) * (1 + rng.normal(0, 0.002, sessions))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, sessions)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, sessions)))
    volume = rng.integers(1_000_000, 5_000_000, sessions).astype(float)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "adj_close": close * 0.98,
            "volume": volume,
            "dividends": 0.0,
            "splits": 0.0,
        },
        index=index,
    )


def to_yfinance_frame(bars: pd.DataFrame) -> pd.DataFrame:
    """Shape canonical bars like ``yfinance.Ticker.history(auto_adjust=False)`` output."""
    frame = bars.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "adj_close": "Adj Close",
            "volume": "Volume",
            "dividends": "Dividends",
            "splits": "Stock Splits",
        }
    )
    frame.index = pd.DatetimeIndex(frame.index).tz_localize("America/New_York")
    frame.index.name = "Date"
    return frame


def synthetic_intraday(start: str | None = None, days: int = 40, minutes: int = 60,
                       seed: int = 11) -> pd.DataFrame:  # fmt: skip
    """Regular-session bars (9:30–16:00 New York wall time) on business days.

    By default the series ends a few days before today, inside Yahoo's intraday window.
    """
    if start is None:
        start = (pd.Timestamp.today().normalize() - pd.offsets.BDay(days + 3)).strftime("%Y-%m-%d")
    stamps: list[pd.Timestamp] = []
    for day in pd.bdate_range(start, periods=days):
        t = day + pd.Timedelta(hours=9, minutes=30)
        while t < day + pd.Timedelta(hours=16):
            stamps.append(t)
            t += pd.Timedelta(minutes=minutes)
    rng = np.random.default_rng(seed)
    n = len(stamps)
    close = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.003, n)))
    open_ = np.concatenate([[100.0], close[:-1]])
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.001, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.001, n)))
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "adj_close": close,
         "volume": rng.integers(10_000, 50_000, n).astype(float), "dividends": 0.0,
         "splits": 0.0},
        index=pd.DatetimeIndex(stamps, name="date"),
    )  # fmt: skip


class FakeYahooClient:
    """Stands in for YFinanceClient. Serves slices of a synthetic series."""

    def __init__(self, bars: pd.DataFrame | None = None) -> None:
        self.bars = synthetic_daily() if bars is None else bars
        self.history_calls: list[tuple[str, date | None, date | None]] = []
        self.search_payload: list[dict[str, object]] = []
        self.info_payload: dict[str, object] = {}
        self.error: Exception | None = None
        self.search_error: Exception | None = None
        self.known = {"TEST"}
        self.intraday_calls: list[tuple[str, date | None, date | None, str]] = []
        #: interval code ("1h", "15m") -> canonical bars with exchange-local times.
        self.intraday: dict[str, pd.DataFrame] = {
            "1h": synthetic_intraday(), "15m": synthetic_intraday(minutes=15),
        }  # fmt: skip

    def history(self, symbol: str, start: date | None, end: date | None,
                interval: str = "1d") -> pd.DataFrame:  # fmt: skip
        if interval != "1d":
            self.intraday_calls.append((symbol, start, end, interval))
        else:
            self.history_calls.append((symbol, start, end))
        if self.error:
            raise self.error
        if symbol not in self.known:
            return pd.DataFrame()
        bars = self.bars if interval == "1d" else self.intraday.get(interval, pd.DataFrame())
        if bars.empty:
            return pd.DataFrame()
        if start is not None:
            bars = bars[bars.index >= pd.Timestamp(start)]
        if end is not None:
            bars = bars[bars.index <= pd.Timestamp(end)]
        return to_yfinance_frame(bars)

    def search(self, query: str, limit: int) -> list[dict[str, object]]:
        if self.error or self.search_error:
            raise self.error or self.search_error  # type: ignore[misc]
        return self.search_payload

    def info(self, symbol: str) -> dict[str, object]:
        if self.error:
            raise self.error
        return self.info_payload


def path(*prices: float, leg: int = 10, start: str = "2024-01-01") -> pd.DataFrame:
    """Bars moving linearly between the given turning points (high = low = close)."""
    values = [float(prices[0])]
    for a, b in itertools.pairwise(prices):
        values += list(np.linspace(a, b, leg + 1)[1:])
    index = pd.bdate_range(start, periods=len(values), name="date")
    close = pd.Series(values, index=index)
    return pd.DataFrame({"open": close, "high": close, "low": close, "close": close,
                         "adj_close": close, "volume": 1_000.0, "dividends": 0.0,
                         "splits": 0.0})  # fmt: skip
