"""Analysis result types."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Category(StrEnum):
    TREND = "trend"
    MOMENTUM = "momentum"
    CROSSOVER = "crossover"
    VOLUME = "volume"
    VOLATILITY = "volatility"
    BREAKOUT = "breakout"


class Direction(StrEnum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class Signal:
    rule_id: str
    category: Category
    direction: Direction
    title: str
    #: Each line states one condition with its actual values.
    evidence: tuple[str, ...]
    bar_date: date


@dataclass(frozen=True)
class AnalysisReport:
    symbol: str
    as_of: date | None
    bars_used: int
    signals: tuple[Signal, ...]
    #: Rules that could not run (e.g. not enough history) and why.
    skipped: tuple[str, ...] = field(default=())
    #: True when the last bar of the series was excluded because its session is still open.
    excluded_partial_bar: bool = False


#: Formats a number for display (the UI passes a locale-aware formatter).
NumberFormat = Callable[[float, int], str]


def default_format(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}"
