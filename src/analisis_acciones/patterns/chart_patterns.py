"""Classic chart patterns detected on ZigZag swing pivots.

Patterns: double top/bottom, head and shoulders (and inverse), ascending,
descending and symmetric triangles, and bull/bear flags. Every pattern lists
the conditions it was required to meet, with the measured values.

A pattern only counts once price **closes beyond its breakout line**
(neckline, triangle side, flag channel). Before that it is reported as
"forming", and only while it is the latest structure on the chart. After the
breakout, each pattern is followed until price reaches the classic measured
target or the invalidation level, whichever comes first; this gives a simple
track record of how the pattern worked on this asset.

Tolerances scale with the asset's volatility (``tolerance`` = median
ATR/close), so a 1 % difference means more for a utility than for a small
biotech.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from analisis_acciones.patterns.elliott import Check, Target
from analisis_acciones.patterns.levels import Level, price_tolerance, support_resistance
from analisis_acciones.patterns.zigzag import HIGH, LOW, Pivot, auto_threshold, zigzag

FORMING, CONFIRMED, TARGET_HIT, INVALIDATED = "forming", "confirmed", "target", "invalidated"
MAX_PATTERNS = 20
#: Support/resistance only from swings of roughly the last two years of daily bars.
LEVEL_LOOKBACK = 500


@dataclass(frozen=True)
class Segment:
    start: int
    start_price: float
    end: int
    end_price: float


@dataclass(frozen=True)
class ChartPattern:
    family: str  # double, hs, triangle, flag
    name: str
    bias: int  # +1 bullish, -1 bearish, 0 undecided (symmetric triangle before breakout)
    points: tuple[Pivot, ...]
    labels: tuple[str, ...]
    lines: tuple[Segment, ...]
    checks: tuple[Check, ...]
    status: str
    breakout: int | None = None
    targets: tuple[Target, ...] = ()
    invalidation: float | None = None

    @property
    def start(self) -> int:
        return self.points[0].index

    @property
    def end(self) -> int:
        return self.points[-1].index


@dataclass(frozen=True)
class PatternResult:
    threshold: float
    tolerance: float
    close: float
    pivots: list[Pivot]
    levels: list[Level] = field(default_factory=list)
    patterns: list[ChartPattern] = field(default_factory=list)

    def track_record(self) -> tuple[int, int, int]:
        """(confirmed patterns with an outcome, targets reached, invalidated)."""
        hit = sum(p.status == TARGET_HIT for p in self.patterns)
        failed = sum(p.status == INVALIDATED for p in self.patterns)
        return hit + failed, hit, failed


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %".replace(".", ",")


class _Bars:
    def __init__(self, bars: pd.DataFrame) -> None:
        self.close = bars["close"].to_numpy(dtype=float)
        self.high = bars["high"].to_numpy(dtype=float)
        self.low = bars["low"].to_numpy(dtype=float)
        self.n = len(self.close)

    def breakout(
        self, after: int, line: Callable[[int], float], side: int, max_bars: int
    ) -> int | None:
        """First bar after ``after`` closing beyond ``line`` on ``side`` (+1 above, −1 below)."""
        for i in range(after + 1, min(self.n, after + 1 + max_bars)):
            if side * (self.close[i] - line(i)) > 0:
                return i
        return None

    def outcome(self, breakout: int, target: float, invalidation: float, side: int) -> str:
        """Which comes first after the breakout: the target or the invalidation level.

        If both are touched on the same bar the outcome counts as invalidated
        (daily bars do not tell which happened first).
        """
        for i in range(breakout + 1, self.n):
            if side > 0:
                if self.low[i] <= invalidation:
                    return INVALIDATED
                if self.high[i] >= target:
                    return TARGET_HIT
            else:
                if self.high[i] >= invalidation:
                    return INVALIDATED
                if self.low[i] <= target:
                    return TARGET_HIT
        return CONFIRMED

    def violated_since(self, after: int, level: float, side: int) -> bool:
        """Has any close after ``after`` gone beyond ``level`` on ``side``?"""
        segment = self.close[after + 1 :]
        return bool((side * (segment - level) > 0).any())


def _line(a: Pivot, b: Pivot) -> Callable[[int], float]:
    slope = (b.price - a.price) / (b.index - a.index)
    return lambda i: a.price + slope * (i - a.index)


def _is_latest(window: list[Pivot], pivots: list[Pivot]) -> bool:
    """The window ends at one of the last two pivots (a structure still on screen)."""
    return window[-1].index >= pivots[max(len(pivots) - 2, 0)].index


def _finish(
    ctx: _Bars,
    *,
    family: str,
    name: str,
    side: int,
    window: list[Pivot],
    labels: tuple[str, ...],
    lines_until: Callable[[int], tuple[Segment, ...]],
    checks: list[Check],
    neckline: Callable[[int], float],
    max_bars: int,
    target_from: Callable[[int], float],
    invalidation: float,
    latest: bool,
) -> ChartPattern | None:
    """Common tail: require all checks, find the breakout and follow the outcome."""
    if not all(c.passed for c in checks):
        return None
    last = window[-1].index
    breakout = ctx.breakout(last, neckline, side, max_bars)
    if breakout is None:
        # Not confirmed: only keep it while it is the latest structure and still intact.
        if not latest or ctx.violated_since(last, invalidation, -side):
            return None
        target = target_from(ctx.n - 1)
        return ChartPattern(
            family,
            name,
            side,
            tuple(window),
            labels,
            lines_until(ctx.n - 1),
            tuple(checks),
            FORMING,
            None,
            (Target("Objetivo si se confirma", target),),
            invalidation,
        )
    target = target_from(breakout)
    status = ctx.outcome(breakout, target, invalidation, side)
    return ChartPattern(
        family,
        name,
        side,
        tuple(window),
        labels,
        lines_until(breakout),
        tuple(checks),
        status,
        breakout,
        (Target("Objetivo", target),),
        invalidation,
    )


# ---------------------------------------------------------------------------
# Double top / bottom
# ---------------------------------------------------------------------------
def _double(ctx: _Bars, pivots: list[Pivot], i: int, tol: float) -> ChartPattern | None:
    window = pivots[i : i + 3]
    first, valley, second = window
    side = -1 if first.kind == HIGH else 1  # top -> bearish
    extreme = max(first.price, second.price) if side < 0 else min(first.price, second.price)
    inner = min(first.price, second.price) if side < 0 else max(first.price, second.price)
    similar = max(1.5 * tol, 0.01)
    depth_min = max(3 * tol, 0.03)
    diff = abs(second.price - first.price) / extreme
    depth = abs(inner - valley.price) / inner
    word = "máximos" if side < 0 else "mínimos"
    checks = [
        Check(
            f"Dos {word} a altura similar (diferencia ≤ {_pct(similar)})",
            diff <= similar,
            _pct(diff),
        ),
        Check(
            f"{'Valle' if side < 0 else 'Pico'} intermedio de al menos {_pct(depth_min)}",
            depth >= depth_min,
            _pct(depth),
        ),
        Check(
            "Separación de al menos 10 barras",
            second.index - first.index >= 10,
            f"{second.index - first.index} barras",
        ),
    ]
    if i > 0:
        before = pivots[i - 1]
        checks.append(
            Check(
                "Precedido de una " + ("subida" if side < 0 else "bajada"),
                side * (before.price - valley.price) > 0,
                f"giro anterior en {before.price:.2f}".replace(".", ","),
            )
        )
    neck = valley.price
    height = abs(extreme - neck)

    def lines(until: int) -> tuple[Segment, ...]:
        return (Segment(first.index, neck, until, neck),)

    name = "Doble techo" if side < 0 else "Doble suelo"
    labels = ("T1", "", "T2") if side < 0 else ("S1", "", "S2")
    return _finish(
        ctx,
        family="double",
        name=name,
        side=side,
        window=window,
        labels=labels,
        lines_until=lines,
        checks=checks,
        neckline=lambda _i: neck,
        max_bars=second.index - first.index,
        target_from=lambda _b: neck + side * height,
        invalidation=extreme,
        latest=_is_latest(window, pivots),
    )


# ---------------------------------------------------------------------------
# Head and shoulders
# ---------------------------------------------------------------------------
def _head_shoulders(ctx: _Bars, pivots: list[Pivot], i: int, tol: float) -> ChartPattern | None:
    window = pivots[i : i + 5]
    ls, n1, head, n2, rs = window
    side = -1 if ls.kind == HIGH else 1
    s = -side  # +1 when the shoulders/head are highs
    shoulder_gap = max(3 * tol, 0.02)
    head_margin = max(tol, 0.01)
    outer = max(ls.price, rs.price) if s > 0 else min(ls.price, rs.price)
    head_excess = s * (head.price - outer) / outer
    shoulders_diff = abs(ls.price - rs.price) / outer
    neck = _line(n1, n2)
    neck_slope = abs(n2.price - n1.price) / n1.price
    checks = [
        Check(
            f"La cabeza sobresale de ambos hombros (≥ {_pct(head_margin)})",
            head_excess >= head_margin,
            _pct(head_excess),
        ),
        Check(
            f"Hombros a altura parecida (diferencia ≤ {_pct(shoulder_gap)})",
            shoulders_diff <= shoulder_gap,
            _pct(shoulders_diff),
        ),
        Check(
            f"Línea clavicular poco inclinada (≤ {_pct(shoulder_gap)})",
            neck_slope <= shoulder_gap,
            _pct(neck_slope),
        ),
        Check(
            "Hombros por " + ("encima" if s > 0 else "debajo") + " de la línea clavicular",
            s * (ls.price - neck(ls.index)) > 0 and s * (rs.price - neck(rs.index)) > 0,
            "",
        ),
    ]
    if i > 0:
        before = pivots[i - 1]
        checks.append(
            Check(
                "Precedido de una " + ("subida" if s > 0 else "bajada"),
                s * (n1.price - before.price) > 0,
                f"giro anterior en {before.price:.2f}".replace(".", ","),
            )
        )
    height = abs(head.price - neck(head.index))

    def lines(until: int) -> tuple[Segment, ...]:
        return (Segment(ls.index, neck(ls.index), until, neck(until)),)

    name = "Hombro-cabeza-hombro" if side < 0 else "Hombro-cabeza-hombro invertido"
    return _finish(
        ctx,
        family="hs",
        name=name,
        side=side,
        window=window,
        labels=("HI", "", "C", "", "HD"),
        lines_until=lines,
        checks=checks,
        neckline=neck,
        max_bars=rs.index - ls.index,
        target_from=lambda b: neck(b) + side * height,
        invalidation=rs.price,
        latest=_is_latest(window, pivots),
    )


# ---------------------------------------------------------------------------
# Triangles
# ---------------------------------------------------------------------------
def _triangle(
    ctx: _Bars, pivots: list[Pivot], i: int, size: int, tol: float
) -> ChartPattern | None:
    window = pivots[i : i + size]
    highs = [p for p in window if p.kind == HIGH]
    lows = [p for p in window if p.kind == LOW]
    if len(highs) < 2 or len(lows) < 2:
        return None
    upper, lower = _line(highs[0], highs[-1]), _line(lows[0], lows[-1])
    flat = max(tol, 0.01)
    h_change = (highs[-1].price - highs[0].price) / highs[0].price
    l_change = (lows[-1].price - lows[0].price) / lows[0].price
    if abs(h_change) <= flat and l_change > flat:
        name, bias = "Triángulo ascendente", 1
    elif abs(l_change) <= flat and h_change < -flat:
        name, bias = "Triángulo descendente", -1
    elif h_change < -flat and l_change > flat:
        name, bias = "Triángulo simétrico", 0
    else:
        return None
    start, last = window[0].index, window[-1].index
    width_start = upper(start) - lower(start)
    width_end = upper(last) - lower(last)
    inside = all(
        abs(p.price - (upper if p.kind == HIGH else lower)(p.index)) <= flat * p.price
        for p in window
    )
    checks = [
        Check("Máximos " + ("planos" if bias > 0 else "descendentes"), True, _pct(h_change)),
        Check("Mínimos " + ("planos" if bias < 0 else "ascendentes"), True, _pct(l_change)),
        Check(
            "Las líneas convergen (anchura final < 75 % de la inicial)",
            width_start > 0 and width_end < 0.75 * width_start,
            _pct(width_end / width_start) if width_start > 0 else "—",
        ),
        Check(f"Todos los giros tocan su línea (± {_pct(flat)})", inside, ""),
    ]
    if not all(c.passed for c in checks):
        return None
    span = last - start
    breakout_up = ctx.breakout(last, upper, 1, span)
    breakout_down = ctx.breakout(last, lower, -1, span)
    candidates = [(b, s) for b, s in ((breakout_up, 1), (breakout_down, -1)) if b is not None]
    latest = _is_latest(window, pivots)

    def lines(until: int) -> tuple[Segment, ...]:
        return (
            Segment(start, upper(start), until, upper(until)),
            Segment(start, lower(start), until, lower(until)),
        )

    if not candidates:
        if not latest:
            return None
        end = ctx.n - 1
        if ctx.close[end] > upper(end) or ctx.close[end] < lower(end):
            return None
        targets = []
        if bias >= 0:
            targets.append(Target("Objetivo si rompe al alza", upper(end) + width_start))
        if bias <= 0:
            targets.append(Target("Objetivo si rompe a la baja", lower(end) - width_start))
        return ChartPattern(
            "triangle",
            name,
            bias,
            tuple(window),
            (),
            lines(end),
            tuple(checks),
            FORMING,
            None,
            tuple(targets),
            lower(end) if bias > 0 else upper(end) if bias < 0 else None,
        )
    breakout, side = min(candidates)
    target = (upper if side > 0 else lower)(breakout) + side * width_start
    invalidation = (lower if side > 0 else upper)(breakout)
    status = ctx.outcome(breakout, target, invalidation, side)
    direction = "al alza" if side > 0 else "a la baja"
    checks.append(Check(f"Ruptura {direction}", True, ""))
    return ChartPattern(
        "triangle",
        name,
        side,
        tuple(window),
        (),
        lines(breakout),
        tuple(checks),
        status,
        breakout,
        (Target("Objetivo", target),),
        invalidation,
    )


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
def _flag(ctx: _Bars, pivots: list[Pivot], i: int, tol: float) -> ChartPattern | None:
    window = pivots[i : i + 4]
    base, top, pullback, retest = window
    side = 1 if base.kind == LOW else -1
    pole = abs(top.price - base.price)
    pole_pct = pole / base.price
    pole_bars = top.index - base.index
    retrace = abs(top.price - pullback.price) / pole
    pole_min = max(4 * tol, 0.06)
    checks = [
        Check(
            f"Mástil fuerte: movimiento ≥ {_pct(pole_min)} en ≤ 25 barras",
            pole_pct >= pole_min and pole_bars <= 25,
            f"{_pct(pole_pct)} en {pole_bars} barras",
        ),
        Check(
            "Retroceso de la bandera entre 15 y 50 % del mástil",
            0.15 <= retrace <= 0.5,
            _pct(retrace),
        ),
        Check(
            "El rebote no supera el extremo del mástil",
            side * (retest.price - top.price) <= max(tol, 0.005) * top.price,
            f"{retest.price:.2f} frente a {top.price:.2f}".replace(".", ","),
        ),
        Check(
            "Bandera más corta que 3 × el mástil",
            retest.index - top.index <= 3 * pole_bars,
            f"{retest.index - top.index} barras",
        ),
    ]
    upper = _line(top, retest)

    def channel(i: int) -> float:
        return upper(i)

    def lines(until: int) -> tuple[Segment, ...]:
        offset = pullback.price - upper(pullback.index)
        return (
            Segment(base.index, base.price, top.index, top.price),
            Segment(top.index, upper(top.index), until, upper(until)),
            Segment(top.index, upper(top.index) + offset, until, upper(until) + offset),
        )

    name = "Bandera alcista" if side > 0 else "Bandera bajista"
    return _finish(
        ctx,
        family="flag",
        name=name,
        side=side,
        window=window,
        labels=("", "", "", ""),
        lines_until=lines,
        checks=checks,
        neckline=channel,
        max_bars=retest.index - top.index + pole_bars,
        target_from=lambda b: channel(b) + side * pole,
        invalidation=pullback.price,
        latest=_is_latest(window, pivots),
    )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------
def _non_overlapping(candidates: list[ChartPattern]) -> list[ChartPattern]:
    chosen: list[ChartPattern] = []
    for pattern in sorted(candidates, key=lambda p: p.end, reverse=True):
        if all(pattern.end <= other.start or pattern.start >= other.end for other in chosen):
            chosen.append(pattern)
    return chosen


def find_patterns(bars: pd.DataFrame, pivots: list[Pivot], tol: float,
                  limit: int | None = MAX_PATTERNS) -> list[ChartPattern]:  # fmt: skip
    ctx = _Bars(bars)
    # Overlap is only resolved within one pattern type: a double top and the
    # double bottom right after it can both be real.
    by_name: dict[str, list[ChartPattern]] = {}
    for i in range(len(pivots)):
        found = [
            _double(ctx, pivots, i, tol) if i + 3 <= len(pivots) else None,
            _head_shoulders(ctx, pivots, i, tol) if i + 5 <= len(pivots) else None,
            _flag(ctx, pivots, i, tol) if i + 4 <= len(pivots) else None,
            *(
                _triangle(ctx, pivots, i, size, tol) if i + size <= len(pivots) else None
                for size in (6, 5)
            ),
        ]
        for pattern in found:
            if pattern is not None:
                by_name.setdefault(pattern.name, []).append(pattern)
    patterns = [p for group in by_name.values() for p in _non_overlapping(group)]
    patterns.sort(key=lambda p: p.end)
    return patterns if limit is None else patterns[-limit:]


def analyze(bars: pd.DataFrame, threshold: float | None = None) -> PatternResult:
    """Support/resistance levels and chart patterns for ``bars``."""
    tol = price_tolerance(bars)
    threshold = auto_threshold(bars, multiple=2.0) if threshold is None else threshold
    pivots = zigzag(bars["high"], bars["low"], threshold)
    close = float(bars["close"].iloc[-1]) if len(bars) else float("nan")
    recent = [p for p in pivots if p.index >= len(bars) - LEVEL_LOOKBACK]
    levels = support_resistance(recent, close, tol) if np.isfinite(close) else []
    return PatternResult(threshold, tol, close, pivots, levels, find_patterns(bars, pivots, tol))


def detect(bars: pd.DataFrame, limit: int | None = None) -> list[ChartPattern]:
    """Patterns only (automatic threshold and tolerance from ``bars`` itself)."""
    pivots = zigzag(bars["high"], bars["low"], auto_threshold(bars, multiple=2.0))
    return find_patterns(bars, pivots, price_tolerance(bars), limit)
