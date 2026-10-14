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


@dataclass(frozen=True)
class ScanRow:
    symbol: str
    close: float
    change_pct: float | None
    rsi14: float | None
    bullish: tuple[str, ...]  # titles of bullish signals and patterns
    bearish: tuple[str, ...]
    patterns: tuple[str, ...]  # "Doble suelo (en formación)", ...
    elliott: str  # possible count in progress, "" when none
    support_pct: float | None  # distance below the close to the nearest support, %
    resistance_pct: float | None  # distance above the close to the nearest resistance, %


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
    patterns: list[str] = []
    recent_from = len(bars) - RECENT_BARS
    for pattern in found.patterns:
        if pattern.status == chart_patterns.FORMING:
            label = f"{pattern.name} (en formación)"
        elif pattern.breakout is not None and pattern.breakout >= recent_from:
            label = f"{pattern.name} (ruptura reciente)"
            (bullish if pattern.bias > 0 else bearish).append(pattern.name)
        else:
            continue
        patterns.append(label)

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
    return ScanRow(
        symbol=symbol,
        close=last,
        change_pct=change if np.isfinite(change) else None,
        rsi14=rsi_value if np.isfinite(rsi_value) else None,
        bullish=tuple(bullish),
        bearish=tuple(bearish),
        patterns=tuple(patterns),
        elliott=wave_text,
        support_pct=(last / max(supports) - 1) * 100 if supports else None,
        resistance_pct=(min(resistances) / last - 1) * 100 if resistances else None,
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
