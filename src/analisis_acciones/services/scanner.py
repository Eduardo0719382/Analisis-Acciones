"""Scan many symbols with the same deterministic tools used on the chart.

For each symbol (completed daily bars only): last close and change, RSI 14,
the rule-based analysis signals, chart patterns forming or confirmed in the
last few bars, the possible Elliott count in progress and the distance to
the nearest support and resistance. It describes the data; it does not rank
symbols by expected return.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from analisis_acciones.analysis.engine import analyze as analyze_signals
from analisis_acciones.analysis.model import Direction
from analisis_acciones.indicators.functions import rsi
from analisis_acciones.models.errors import AppError
from analisis_acciones.models.market import Interval
from analisis_acciones.patterns import chart_patterns, elliott
from analisis_acciones.services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

MAX_SYMBOLS = 50
#: A confirmed pattern counts as "recent" if its breakout is within this many bars.
RECENT_BARS = 10
MIN_BARS = 60
#: Closes kept per row for the report's mini chart.
HISTORY_BARS = 120
FORMING_NOTE, BREAKOUT_NOTE = "en formación", "ruptura reciente"


@dataclass(frozen=True)
class PatternNote:
    name: str
    state: str  # FORMING_NOTE or BREAKOUT_NOTE
    bias: int  # +1 bullish, -1 bearish, 0 undecided

    def __str__(self) -> str:
        return f"{self.name} ({self.state})"


@dataclass(frozen=True)
class ScanRow:
    symbol: str
    close: float
    change_pct: float | None
    rsi14: float | None
    bullish: tuple[str, ...]  # titles of bullish signals and patterns
    bearish: tuple[str, ...]
    pattern_notes: tuple[PatternNote, ...]
    elliott: str  # possible count in progress, "" when none
    support_pct: float | None  # distance below the close to the nearest support, %
    resistance_pct: float | None  # distance above the close to the nearest resistance, %
    support: float | None = None
    resistance: float | None = None
    elliott_direction: int = 0
    as_of: date | None = None
    #: Last closes (oldest first) and the date of the first one, for the mini chart.
    history: tuple[float, ...] = ()
    history_start: date | None = None

    @property
    def patterns(self) -> tuple[str, ...]:
        return tuple(str(note) for note in self.pattern_notes)


@dataclass(frozen=True)
class ScanResult:
    rows: list[ScanRow] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def scan_bars(symbol: str, bars: pd.DataFrame) -> ScanRow:
    """Scan one symbol's completed daily bars."""
    if len(bars) < MIN_BARS:
        raise ValueError(f"se necesitan al menos {MIN_BARS} sesiones (hay {len(bars)})")
    close = bars["close"]
    last = float(close.iloc[-1])
    change = float(close.iloc[-1] / close.iloc[-2] - 1) * 100
    rsi_value = float(rsi(close, 14).iloc[-1])

    bullish: list[str] = []
    bearish: list[str] = []
    for signal in analyze_signals(symbol, bars).signals:
        if signal.direction is Direction.BULLISH:
            bullish.append(signal.title)
        elif signal.direction is Direction.BEARISH:
            bearish.append(signal.title)

    found = chart_patterns.analyze(bars)
    patterns: list[PatternNote] = []
    recent_from = len(bars) - RECENT_BARS
    for pattern in found.patterns:
        if pattern.status == chart_patterns.FORMING:
            patterns.append(PatternNote(pattern.name, FORMING_NOTE, pattern.bias))
        elif pattern.breakout is not None and pattern.breakout >= recent_from:
            patterns.append(PatternNote(pattern.name, BREAKOUT_NOTE, pattern.bias))
            (bullish if pattern.bias > 0 else bearish).append(pattern.name)

    waves = elliott.analyze(bars)
    current = waves.current[0] if waves.current else None
    wave_text = ""
    if current is not None:
        direction = "alcista" if current.direction > 0 else "bajista"
        kind = "impulso" if current.kind == elliott.IMPULSE else "corrección"
        labels = "-".join(lbl for lbl in current.labels if lbl and lbl != "0")
        wave_text = f"{kind} {direction} {labels}"

    supports = [lv.price for lv in found.levels if lv.price < last]
    resistances = [lv.price for lv in found.levels if lv.price >= last]
    support = max(supports) if supports else None
    resistance = min(resistances) if resistances else None
    recent = close.tail(HISTORY_BARS)
    return ScanRow(
        symbol=symbol,
        close=last,
        change_pct=change if np.isfinite(change) else None,
        rsi14=rsi_value if np.isfinite(rsi_value) else None,
        bullish=tuple(bullish),
        bearish=tuple(bearish),
        pattern_notes=tuple(patterns),
        elliott=wave_text,
        support_pct=(last / support - 1) * 100 if support else None,
        resistance_pct=(resistance / last - 1) * 100 if resistance else None,
        support=support,
        resistance=resistance,
        elliott_direction=current.direction if current is not None else 0,
        as_of=pd.Timestamp(bars.index[-1]).date(),
        history=tuple(float(v) for v in recent),
        history_start=pd.Timestamp(recent.index[0]).date(),
    )


def run_scan(market: MarketDataService, symbols: list[str],
             progress: Callable[[int, int, str], None] | None = None) -> ScanResult:  # fmt: skip
    """Scan ``symbols`` (cache-first loads). Problems are reported per symbol, never raised."""
    result = ScanResult()
    targets = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))[:MAX_SYMBOLS]
    for done, symbol in enumerate(targets):
        if progress is not None:
            progress(done, len(targets), symbol)
        try:
            loaded = market.load(symbol, Interval.D1)
            bars = loaded.series.bars
            if loaded.session_in_progress:
                bars = bars.iloc[:-1]  # same rule as alerts and analysis: completed bars only
            result.rows.append(scan_bars(loaded.series.symbol, bars))
        except AppError as exc:
            result.problems.append(f"{symbol}: {exc.user_message}")
        except (ValueError, ArithmeticError, KeyError) as exc:
            logger.exception("Scan of %s failed", symbol)
            result.problems.append(f"{symbol}: no se pudo analizar ({exc})")
    return result
