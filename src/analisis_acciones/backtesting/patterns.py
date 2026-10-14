"""Backtest of chart patterns: trade each confirmed breakout, many assets at once.

No look-ahead
-------------
Pattern detection uses swing pivots and volatility-based thresholds that
change as data arrives, so a pattern found on the full history may not have
been visible at the time. Every candidate is therefore **re-detected using
only the bars up to its breakout bar** (same name, same pivots, breakout on
that same bar). Candidates that fail this check are discarded and counted.
Candidates come from the full history plus analyses on growing prefixes, so
patterns visible only with the thresholds of that time are found as well.

Trade rules
-----------
* signal at the close of the breakout bar; entry at the **next open**;
* bullish patterns buy, bearish patterns sell short (or are skipped when only
  long trades are allowed); symmetric triangles follow the breakout side;
* exit at the pattern's measured target, at its invalidation level (stop), or
  at the close after ``max_bars`` sessions, whichever comes first;
* if the target and the stop are both touched within one daily bar, the stop
  is assumed first (daily data does not tell the order);
* an open beyond the target/stop fills at that open;
* costs: ``commission_pct`` per side and ``slippage_pct`` against each fill.

Returns are per trade, as a percentage of the entry value (no compounding,
no position sizing), so patterns and assets can be compared directly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

from analisis_acciones.models.errors import AppError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.patterns.chart_patterns import ChartPattern, detect
from analisis_acciones.services.market_data_service import MarketDataService

logger = logging.getLogger(__name__)

TARGET, STOP, TIME = "target", "stop", "time"
#: Prefix analyses are run every this many bars to collect candidates.
CANDIDATE_STEP = 40
MIN_BARS = 120
MAX_SYMBOLS = 30
PATTERN_NAMES = (
    "Doble techo",
    "Doble suelo",
    "Hombro-cabeza-hombro",
    "Hombro-cabeza-hombro invertido",
    "Triángulo ascendente",
    "Triángulo descendente",
    "Triángulo simétrico",
    "Bandera alcista",
    "Bandera bajista",
)


@dataclass(frozen=True)
class PatternBacktestConfig:
    max_bars: int = 60
    long_only: bool = False
    commission_pct: float = 0.1
    slippage_pct: float = 0.05
    patterns: tuple[str, ...] = PATTERN_NAMES

    def validate(self) -> None:
        if not 1 <= self.max_bars <= 500:
            raise UserError(
                "bad max_bars", user_message="El plazo máximo debe estar entre 1 y 500 sesiones."
            )
        if not 0 <= self.commission_pct < 10 or not 0 <= self.slippage_pct < 10:
            raise UserError("bad costs", user_message="Comisión o deslizamiento no válidos.")
        if not self.patterns:
            raise UserError("no patterns", user_message="Elija al menos un tipo de patrón.")


@dataclass(frozen=True)
class PatternTrade:
    symbol: str
    pattern: str
    direction: int  # +1 long, -1 short
    signal_date: date
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    exit_reason: str  # TARGET, STOP or TIME
    bars_held: int
    return_pct: float  # after costs
    #: Average return of the same direction and holding period from any start on this
    #: asset (the "no pattern" reference).
    baseline_pct: float | None


@dataclass(frozen=True)
class GroupStats:
    name: str
    trades: int
    win_rate_pct: float
    avg_return_pct: float
    median_return_pct: float
    avg_win_pct: float | None
    avg_loss_pct: float | None
    profit_factor: float | None
    target_pct: float
    stop_pct: float
    time_pct: float
    avg_bars: float
    edge_pct: float | None  # average return minus average baseline


@dataclass(frozen=True)
class PatternBacktestResult:
    config: PatternBacktestConfig
    trades: list[PatternTrade]
    discarded: int  # candidates not visible at their breakout with the data of that day
    skipped_short: int
    problems: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)

    def by_pattern(self) -> list[GroupStats]:
        return _groups(self.trades, lambda t: t.pattern)

    def by_symbol(self) -> list[GroupStats]:
        return _groups(self.trades, lambda t: t.symbol)

    def overall(self) -> GroupStats | None:
        groups = _groups(self.trades, lambda _t: "Todos")
        return groups[0] if groups else None


# ---------------------------------------------------------------------------
# Detection without look-ahead
# ---------------------------------------------------------------------------
def _key(pattern: ChartPattern) -> tuple[str, tuple[int, ...]]:
    return pattern.name, tuple(p.index for p in pattern.points)


def honest_breakouts(
    bars: pd.DataFrame, names: Iterable[str] = PATTERN_NAMES, step: int = CANDIDATE_STEP
) -> tuple[list[ChartPattern], int]:
    """Patterns detectable on their breakout bar using only data up to it, and discards."""
    wanted = set(names)
    candidates: dict[tuple[str, tuple[int, ...]], ChartPattern] = {}
    ends = [*range(MIN_BARS, len(bars), step), len(bars)]
    for end in ends:
        for pattern in detect(bars.iloc[:end]):
            if pattern.breakout is not None and pattern.name in wanted:
                candidates.setdefault(_key(pattern), pattern)
    confirmed: list[ChartPattern] = []
    discarded = 0
    cache: dict[int, set[tuple[str, tuple[int, ...]]]] = {}
    for key, pattern in sorted(candidates.items(), key=lambda kv: kv[1].breakout or 0):
        b = pattern.breakout
        assert b is not None
        if b not in cache:
            cache[b] = {_key(p) for p in detect(bars.iloc[: b + 1]) if p.breakout == b}
        if key in cache[b]:
            confirmed.append(pattern)
        else:
            discarded += 1
    return confirmed, discarded


# ---------------------------------------------------------------------------
# Trade simulation
# ---------------------------------------------------------------------------
def _baseline(open_: np.ndarray, close: np.ndarray, direction: int, held: int) -> float | None:
    """Mean return of entering at any open and exiting ``held`` bars later at the close."""
    if held < 1 or len(open_) <= held:
        return None
    entries = open_[1 : len(open_) - held + 1]
    exits = close[held : len(close)]
    n = min(len(entries), len(exits))
    if n == 0:
        return None
    returns = direction * (exits[:n] / entries[:n] - 1) * 100
    return float(np.nanmean(returns))


def simulate(
    symbol: str, bars: pd.DataFrame, pattern: ChartPattern, config: PatternBacktestConfig
) -> PatternTrade | None:
    """One trade for a confirmed pattern, or None when it cannot be entered (last bar)."""
    b = pattern.breakout
    if b is None or b + 1 >= len(bars) or pattern.invalidation is None or not pattern.targets:
        return None
    direction = 1 if pattern.bias > 0 else -1
    target = pattern.targets[0].price
    stop = pattern.invalidation
    open_ = bars["open"].to_numpy(dtype=float)
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    slip = config.slippage_pct / 100
    entry_i = b + 1
    entry = open_[entry_i] * (1 + direction * slip)
    exit_i, exit_raw, reason = len(bars) - 1, close[-1], TIME
    last_i = min(entry_i + config.max_bars - 1, len(bars) - 1)
    for i in range(entry_i, last_i + 1):
        o = open_[i]
        if direction > 0:
            if i > entry_i and o <= stop:
                exit_i, exit_raw, reason = i, o, STOP
                break
            if i > entry_i and o >= target:
                exit_i, exit_raw, reason = i, o, TARGET
                break
            if low[i] <= stop:
                exit_i, exit_raw, reason = i, stop, STOP
                break
            if high[i] >= target:
                exit_i, exit_raw, reason = i, target, TARGET
                break
        else:
            if i > entry_i and o >= stop:
                exit_i, exit_raw, reason = i, o, STOP
                break
            if i > entry_i and o <= target:
                exit_i, exit_raw, reason = i, o, TARGET
                break
            if high[i] >= stop:
                exit_i, exit_raw, reason = i, stop, STOP
                break
            if low[i] <= target:
                exit_i, exit_raw, reason = i, target, TARGET
                break
        exit_i, exit_raw, reason = i, close[i], TIME
    exit_price = exit_raw * (1 - direction * slip)
    gross = direction * (exit_price / entry - 1)
    net = gross - 2 * config.commission_pct / 100
    held = exit_i - entry_i + 1
    index = pd.DatetimeIndex(bars.index)
    return PatternTrade(
        symbol=symbol,
        pattern=pattern.name,
        direction=direction,
        signal_date=index[b].date(),
        entry_date=index[entry_i].date(),
        entry_price=float(entry),
        exit_date=index[exit_i].date(),
        exit_price=float(exit_price),
        exit_reason=reason,
        bars_held=held,
        return_pct=float(net * 100),
        baseline_pct=_baseline(open_, close, direction, held),
    )


def backtest_symbol(
    symbol: str, bars: pd.DataFrame, config: PatternBacktestConfig
) -> tuple[list[PatternTrade], int, int]:
    """(trades, discarded candidates, skipped short trades) for one asset."""
    if len(bars) < MIN_BARS:
        raise ValueError(f"se necesitan al menos {MIN_BARS} sesiones (hay {len(bars)})")
    patterns, discarded = honest_breakouts(bars, config.patterns)
    trades: list[PatternTrade] = []
    skipped = 0
    for pattern in patterns:
        if config.long_only and pattern.bias < 0:
            skipped += 1
            continue
        trade = simulate(symbol, bars, pattern, config)
        if trade is not None:
            trades.append(trade)
    return trades, discarded, skipped


def run_pattern_backtest(
    market: MarketDataService,
    symbols: list[str],
    config: PatternBacktestConfig,
    progress: Callable[[int, int, str], None] | None = None,
) -> PatternBacktestResult:
    config.validate()
    targets = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))[:MAX_SYMBOLS]
    if not targets:
        raise UserError("no symbols", user_message="Escriba al menos un ticker.")
    trades: list[PatternTrade] = []
    problems: list[str] = []
    done_symbols: list[str] = []
    discarded = skipped = 0
    for n, symbol in enumerate(targets):
        if progress is not None:
            progress(n, len(targets), symbol)
        try:
            loaded = market.load(symbol, Interval.D1)
            bars = loaded.series.bars
            if loaded.session_in_progress:
                bars = bars.iloc[:-1]
            found, d, s = backtest_symbol(loaded.series.symbol, bars, config)
        except AppError as exc:
            problems.append(f"{symbol}: {exc.user_message}")
            continue
        except (ValueError, ArithmeticError, KeyError) as exc:
            logger.exception("Pattern backtest of %s failed", symbol)
            problems.append(f"{symbol}: no se pudo analizar ({exc})")
            continue
        trades += found
        discarded += d
        skipped += s
        done_symbols.append(loaded.series.symbol)
    trades.sort(key=lambda t: (t.entry_date, t.symbol))
    return PatternBacktestResult(config, trades, discarded, skipped, problems, done_symbols)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def _groups(trades: list[PatternTrade], key: Callable[[PatternTrade], str]) -> list[GroupStats]:
    grouped: dict[str, list[PatternTrade]] = {}
    for trade in trades:
        grouped.setdefault(key(trade), []).append(trade)
    stats = [_stats(name, group) for name, group in grouped.items()]
    return sorted(stats, key=lambda g: (-g.trades, g.name))


def _stats(name: str, trades: list[PatternTrade]) -> GroupStats:
    returns = np.array([t.return_pct for t in trades])
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    gross_loss = -losses.sum()
    baselines = [t.baseline_pct for t in trades if t.baseline_pct is not None]
    n = len(trades)

    def share(reason: str) -> float:
        return sum(t.exit_reason == reason for t in trades) / n * 100

    return GroupStats(
        name=name,
        trades=n,
        win_rate_pct=len(wins) / n * 100,
        avg_return_pct=float(returns.mean()),
        median_return_pct=float(np.median(returns)),
        avg_win_pct=float(wins.mean()) if len(wins) else None,
        avg_loss_pct=float(losses.mean()) if len(losses) else None,
        profit_factor=float(wins.sum() / gross_loss) if gross_loss > 0 else None,
        target_pct=share(TARGET),
        stop_pct=share(STOP),
        time_pct=share(TIME),
        avg_bars=float(np.mean([t.bars_held for t in trades])),
        edge_pct=float(returns.mean() - np.mean(baselines)) if baselines else None,
    )
