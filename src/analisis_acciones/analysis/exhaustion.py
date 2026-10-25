"""Exhaustion signs of a trend, and what happened after them in the asset's own history.

This is a description of the data, not a forecast: a trend can stay "overbought"
for a long time. To show how much the signs meant in the past, every earlier bar
with the same situation is found (using only data available at that bar) and the
price change N bars later is compared with that of any bar in the same trend.

Up-trend exhaustion (possible end of a rise) — prerequisite: close above its
50-bar SMA and the SMA higher than 10 bars ago. Conditions, each explained:

1. RSI 14 at or above 70 in the last 5 bars (overbought).
2. Bearish divergence: close at a 20-bar high while RSI is at least 5 points
   below its highest value of the previous 20 bars (which was 65 or more).
3. Stretched: close more than 3 ATR(14) above the 50-bar SMA.
4. Fading volume: 10-bar average volume below 80 % of the 50-bar average while
   the close is higher than 10 bars ago (only when the source has volume).
5. Close above the upper Bollinger band (20, 2).
6. Unusually fast rise: 20-bar return more than 2 standard deviations above the
   mean 20-bar return of the previous 500 bars.

Down-trend exhaustion (possible end of a fall) mirrors every rule.

The numbers above are the defaults; ``Params`` lets the user change the RSI
levels, the ATR multiple, the volume ratio, the unusual-move limit and the
number of conditions needed (the divergence keeps its 5-point margin relative
to the RSI level).
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field, fields
from typing import Any

import numpy as np
import pandas as pd

from analisis_acciones.indicators.functions import atr, bollinger, rsi, sma

UP, DOWN = "up", "down"  # exhaustion of an up-trend / of a down-trend
MIN_BARS = 120
THRESHOLD = 3  # conditions needed to call it "signs of exhaustion"
HORIZONS = (10, 20)
SMALL_SAMPLE = 10
SIGNIFICANCE = 0.05
Z_WINDOW = 500


@dataclass(frozen=True)
class Params:
    """Thresholds of the six conditions and how many must be met."""

    rsi_high: float = 70.0  # overbought RSI level (up-trend)
    rsi_low: float = 30.0  # oversold RSI level (down-trend)
    atr_multiple: float = 3.0  # distance from the 50 SMA, in ATR(14)
    volume_ratio: float = 0.8  # 10-bar volume below this share of the 50-bar volume
    z_limit: float = 2.0  # 20-bar move, in standard deviations of the usual one
    threshold: int = 3  # conditions needed to call it "signs of exhaustion"

    def __post_init__(self) -> None:
        for f in fields(self):
            low, high = LIMITS[f.name]
            value = getattr(self, f.name)
            if not isinstance(value, int | float) or not low <= value <= high:
                raise ValueError(f"{f.name}={value!r} outside {low}..{high}")
        if self.rsi_low >= self.rsi_high:
            raise ValueError("rsi_low must be below rsi_high")

    def to_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> Params:
        """Stored settings (external data): anything invalid falls back to the defaults."""
        if not isinstance(raw, dict):
            return cls()
        values: dict[str, Any] = {}
        for f in fields(cls):
            v = raw.get(f.name)
            if isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v):
                values[f.name] = int(v) if f.name == "threshold" else float(v)
        try:
            return cls(**values)
        except (TypeError, ValueError):
            return cls()


LIMITS: dict[str, tuple[float, float]] = {
    "rsi_high": (55.0, 95.0),
    "rsi_low": (5.0, 45.0),
    "atr_multiple": (0.5, 10.0),
    "volume_ratio": (0.1, 1.0),
    "z_limit": (0.5, 5.0),
    "threshold": (1, 6),
}
DEFAULT_PARAMS = Params()


def condition_names(direction: str, params: Params = DEFAULT_PARAMS) -> tuple[str, ...]:
    if direction == UP:
        return (
            f"RSI en sobrecompra (≥ {_fmt(params.rsi_high, 0)})",
            "Divergencia bajista del RSI",
            "Precio muy alejado de su media de 50",
            "Volumen que se apaga en la subida",
            "Cierre por encima de la banda de Bollinger",
            "Subida inusualmente rápida",
        )
    return (
        f"RSI en sobreventa (≤ {_fmt(params.rsi_low, 0)})",
        "Divergencia alcista del RSI",
        "Precio muy alejado por debajo de su media de 50",
        "Volumen que se apaga en la bajada",
        "Cierre por debajo de la banda de Bollinger",
        "Bajada inusualmente rápida",
    )


@dataclass(frozen=True)
class Condition:
    name: str
    met: bool | None  # None = cannot be evaluated (e.g. no volume)
    detail: str


@dataclass(frozen=True)
class Outcome:
    horizon: int
    events: int
    against: int  # times the price moved against the trend (fell after up-exhaustion)
    median_return: float | None  # % after ``horizon`` bars, events only
    baseline_events: int
    baseline_against_pct: float | None  # same measure on any bar of the same trend

    @property
    def against_pct(self) -> float | None:
        return self.against / self.events * 100 if self.events else None

    @property
    def p_value(self) -> float | None:
        """Chance of a difference at least this large from the baseline rate by luck alone.

        Exact one-sided binomial test of ``against`` out of ``events`` against the baseline
        proportion, in the direction of the observed difference.
        """
        if not self.events or self.baseline_against_pct is None:
            return None
        p = min(max(self.baseline_against_pct / 100, 1e-9), 1 - 1e-9)
        n, k = self.events, self.against

        def pmf(i: int) -> float:
            return math.comb(n, i) * p**i * (1 - p) ** (n - i)

        if k >= n * p:
            return min(sum(pmf(i) for i in range(k, n + 1)), 1.0)
        return min(sum(pmf(i) for i in range(0, k + 1)), 1.0)


@dataclass(frozen=True)
class Assessment:
    direction: str | None  # UP, DOWN or None (no trend)
    conditions: list[Condition] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)
    as_of: pd.Timestamp | None = None
    reason: str = ""  # why there is no assessment
    threshold: int = THRESHOLD

    @property
    def met(self) -> int:
        return sum(1 for c in self.conditions if c.met)

    @property
    def available(self) -> int:
        return sum(1 for c in self.conditions if c.met is not None)

    @property
    def signalled(self) -> bool:
        return self.direction is not None and self.met >= self.threshold

    @property
    def small_sample(self) -> bool:
        return any(o.events < SMALL_SAMPLE for o in self.outcomes)


def _fmt(value: float, decimals: int = 1) -> str:
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass(frozen=True)
class _Frame:
    close: pd.Series
    sma50: pd.Series
    rsi: pd.Series
    atr: pd.Series
    upper: pd.Series
    lower: pd.Series
    vol10: pd.Series | None
    vol50: pd.Series | None
    ret20: pd.Series
    zret: pd.Series


def _frame(bars: pd.DataFrame) -> _Frame:
    close = bars["close"].astype(float)
    bands = bollinger(close, 20, 2.0)
    volume = bars.get("volume")
    has_volume = volume is not None and volume.notna().sum() > len(volume) * 0.8
    ret20 = close / close.shift(20) - 1
    prior = ret20.shift(1).rolling(Z_WINDOW, min_periods=120)
    zret = (ret20 - prior.mean()) / prior.std()
    return _Frame(
        close=close,
        sma50=sma(close, 50),
        rsi=rsi(close, 14),
        atr=atr(bars["high"], bars["low"], close, 14),
        upper=bands["upper"],
        lower=bands["lower"],
        vol10=sma(volume.astype(float), 10) if has_volume and volume is not None else None,
        vol50=sma(volume.astype(float), 50) if has_volume and volume is not None else None,
        ret20=ret20,
        zret=zret,
    )


def _trends(f: _Frame) -> tuple[pd.Series, pd.Series]:
    rising = f.sma50 > f.sma50.shift(10)
    falling = f.sma50 < f.sma50.shift(10)
    return (f.close > f.sma50) & rising, (f.close < f.sma50) & falling


def _condition_table(f: _Frame, direction: str, params: Params = DEFAULT_PARAMS) -> pd.DataFrame:
    """Boolean table: one column per condition, one row per bar (NaN = not evaluable)."""
    up = direction == UP
    close, r = f.close, f.rsi
    if up:
        extreme = r.rolling(5).max() >= params.rsi_high
        at_extreme = close >= close.rolling(20).max()
        prev = r.shift(1).rolling(20).max()
        divergence = at_extreme & (prev >= params.rsi_high - 5) & (r <= prev - 5)
        stretched = (close - f.sma50) / f.atr > params.atr_multiple
        band = close > f.upper
        fast = f.zret > params.z_limit
        moved = close > close.shift(10)
    else:
        extreme = r.rolling(5).min() <= params.rsi_low
        at_extreme = close <= close.rolling(20).min()
        prev = r.shift(1).rolling(20).min()
        divergence = at_extreme & (prev <= params.rsi_low + 5) & (r >= prev + 5)
        stretched = (f.sma50 - close) / f.atr > params.atr_multiple
        band = close < f.lower
        fast = f.zret < -params.z_limit
        moved = close < close.shift(10)
    if f.vol10 is not None and f.vol50 is not None:
        fading = ((f.vol10 < params.volume_ratio * f.vol50) & moved).astype(float)
    else:
        fading = pd.Series(np.nan, index=close.index)
    table = pd.DataFrame(
        {
            "extreme": extreme.astype(float),
            "divergence": divergence.astype(float),
            "stretched": stretched.astype(float),
            "fading": fading,
            "band": band.astype(float),
            "fast": fast.astype(float),
        }
    )
    # Comparisons with undefined indicator values are False ("not met"); only a missing
    # volume source is reported as "cannot be evaluated" (NaN).
    return table


def _details(f: _Frame, direction: str, i: int) -> list[str]:
    up = direction == UP
    close, r = f.close.iloc[i], f.rsi.iloc[i]
    window = f.rsi.iloc[max(i - 4, 0) : i + 1]
    extreme = window.max() if up else window.min()
    prev_window = f.rsi.iloc[max(i - 20, 0) : i]
    prev = prev_window.max() if up else prev_window.min()
    dist = ((close - f.sma50.iloc[i]) if up else (f.sma50.iloc[i] - close)) / f.atr.iloc[i]
    band = f.upper.iloc[i] if up else f.lower.iloc[i]
    vol = (
        f"volumen medio 10 sesiones = {_fmt(f.vol10.iloc[i] / f.vol50.iloc[i] * 100, 0)} % "
        "del de 50"
        if f.vol10 is not None and f.vol50 is not None
        else "la fuente no ofrece volumen"
    )
    z = f.zret.iloc[i]
    return [
        f"RSI {'máximo' if up else 'mínimo'} de las últimas 5 sesiones: {_fmt(extreme)}",
        f"RSI actual {_fmt(r)} frente a {'máximo' if up else 'mínimo'} previo {_fmt(prev)}",
        f"{_fmt(dist)} ATR {'por encima' if up else 'por debajo'} de la media de 50",
        vol,
        f"cierre {_fmt(close, 2)} · banda {'superior' if up else 'inferior'} {_fmt(band, 2)}",
        f"variación de 20 sesiones {_fmt(f.ret20.iloc[i] * 100)} % "
        + (f"({_fmt(z)} desviaciones de lo habitual)" if z == z else "(historial insuficiente)"),
    ]


def _outcomes(f: _Frame, trend: pd.Series, score: pd.Series, direction: str,
              threshold: int = THRESHOLD) -> list[Outcome]:  # fmt: skip
    close = f.close.to_numpy(dtype=float)
    in_trend = trend.to_numpy(dtype=bool)
    events_mask = (score >= threshold).to_numpy() & in_trend
    n = len(close)
    out = []
    for horizon in HORIZONS:
        returns: list[float] = []
        last = -horizon
        for i in np.flatnonzero(events_mask):
            if i + horizon >= n or i - last < horizon:
                continue  # no outcome yet, or overlapping with the previous event
            returns.append(close[i + horizon] / close[i] - 1)
            last = int(i)
        idx = np.flatnonzero(in_trend[: max(n - horizon, 0)])
        base = close[idx + horizon] / close[idx] - 1 if len(idx) else np.array([])
        against = sum(1 for x in returns if (x < 0 if direction == UP else x > 0))
        base_against = (base < 0).mean() * 100 if direction == UP else (base > 0).mean() * 100
        out.append(
            Outcome(
                horizon,
                len(returns),
                against,
                float(np.median(returns) * 100) if returns else None,
                len(base),
                float(base_against) if len(base) else None,
            )
        )
    return out


def assess(bars: pd.DataFrame, params: Params = DEFAULT_PARAMS) -> Assessment:
    """Exhaustion signs at the last bar of ``bars`` (completed bars only)."""
    if len(bars) < MIN_BARS:
        return Assessment(None, reason=f"Se necesitan al menos {MIN_BARS} sesiones.",
                          threshold=params.threshold)  # fmt: skip
    f = _frame(bars)
    up_trend, down_trend = _trends(f)
    last = len(bars) - 1
    if bool(up_trend.iloc[last]):
        direction, trend = UP, up_trend
    elif bool(down_trend.iloc[last]):
        direction, trend = DOWN, down_trend
    else:
        return Assessment(
            None,
            as_of=pd.Timestamp(bars.index[-1]),
            reason="Sin tendencia clara: el precio no está a la vez por encima (o por debajo) "
            "de su media de 50 sesiones y con la media subiendo (o bajando).",
            threshold=params.threshold,
        )
    table = _condition_table(f, direction, params)
    row = table.iloc[last]
    details = _details(f, direction, last)
    conditions = [
        Condition(name, None if np.isnan(row.iloc[k]) else bool(row.iloc[k]), details[k])
        for k, name in enumerate(condition_names(direction, params))
    ]
    score = table.fillna(0).sum(axis=1)
    return Assessment(
        direction,
        conditions,
        _outcomes(f, trend, score, direction, params.threshold),
        pd.Timestamp(bars.index[-1]),
        threshold=params.threshold,
    )


def signal_series(bars: pd.DataFrame, params: Params = DEFAULT_PARAMS) -> pd.Series:
    """For every bar: +n up-trend exhaustion score, -n down-trend (n ≥ threshold), else 0.

    Each value uses only the data up to that bar.
    """
    if len(bars) < MIN_BARS:
        return pd.Series(0, index=bars.index)
    f = _frame(bars)
    up_trend, down_trend = _trends(f)
    up = _condition_table(f, UP, params).fillna(0).sum(axis=1).where(up_trend, 0)
    down = _condition_table(f, DOWN, params).fillna(0).sum(axis=1).where(down_trend, 0)
    t = params.threshold
    return (up.where(up >= t, 0) - down.where(down >= t, 0)).astype(int)
