"""Deterministic SYNTHETIC market data for tests.

These numbers are generated, not real prices. They only exercise parsing,
validation, caching and resampling logic.
"""

from __future__ import annotations

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

    def history(self, symbol: str, start: date | None, end: date | None) -> pd.DataFrame:
        self.history_calls.append((symbol, start, end))
        if self.error:
            raise self.error
        if symbol not in self.known:
            return pd.DataFrame()
        bars = self.bars
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
