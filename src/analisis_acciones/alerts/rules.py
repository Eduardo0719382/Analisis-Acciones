"""Alert kinds, parameters and evaluation on completed daily bars.

Two kinds of condition:

* **Level** conditions (price above/below X, RSI above/below X, daily change
  beyond X %) use hysteresis: they fire when the condition becomes true and
  re-arm only after it has been false again, so a price that stays above X
  does not produce one alert per bar.
* **Event** conditions (crossovers, breakouts) fire on the bar where the
  event happens, at most once per bar.

Only completed bars are evaluated; the caller removes an in-progress session
bar so an alert can never fire on a value that later changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Any

import pandas as pd

from analisis_acciones.indicators import functions as f
from analisis_acciones.models.errors import UserError


class AlertKind(StrEnum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    CHANGE_ABOVE = "change_above"
    CHANGE_BELOW = "change_below"
    RSI_ABOVE = "rsi_above"
    RSI_BELOW = "rsi_below"
    EMA_CROSS_UP = "ema_cross_up"
    EMA_CROSS_DOWN = "ema_cross_down"
    MACD_CROSS_UP = "macd_cross_up"
    MACD_CROSS_DOWN = "macd_cross_down"
    BREAKOUT_HIGH = "breakout_high"
    BREAKDOWN_LOW = "breakdown_low"


@dataclass(frozen=True)
class AlertParam:
    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    decimals: int = 0


@dataclass(frozen=True)
class Check:
    """Outcome of evaluating a condition on the last completed bar."""

    met: bool
    message: str
    bar_date: date


@dataclass(frozen=True)
class AlertSpec:
    kind: AlertKind
    label: str
    params: tuple[AlertParam, ...]
    is_level: bool
    min_bars: Callable[[dict[str, float]], int]
    evaluate: Callable[[pd.DataFrame, dict[str, float]], Check]

    def describe(self, params: dict[str, float]) -> str:
        values = {p.key: _num(params[p.key], p.decimals) for p in self.params}
        return self.label.format(**values)


def _num(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}"


def _day(bars: pd.DataFrame) -> date:
    return pd.Timestamp(bars.index[-1]).date()


def _level(
    bars: pd.DataFrame, op: str, label: str, series: pd.Series, threshold: float,
    decimals: int, unit: str = "",
) -> Check:  # fmt: skip
    value = float(series.iloc[-1])
    met = value > threshold if op == ">" else value < threshold
    sign = op if met else ("≤" if op == ">" else "≥")
    text = f"{label} = {_num(value, decimals)}{unit} {sign} {_num(threshold, decimals)}{unit}"
    return Check(met, text, _day(bars))


def _cross(bars: pd.DataFrame, a: pd.Series, b: pd.Series, up: bool, label: str) -> Check:
    prev_above = a.iloc[-2] > b.iloc[-2]
    now_above = a.iloc[-1] > b.iloc[-1]
    met = (not prev_above and now_above) if up else (prev_above and not now_above)
    direction = "por encima" if up else "por debajo"
    detail = f"{label}: {_num(a.iloc[-1])} vs {_num(b.iloc[-1])}"
    text = f"Cruce {direction} en esta barra ({detail})" if met else f"Sin cruce ({detail})"
    return Check(bool(met), text, _day(bars))


def _change(bars: pd.DataFrame) -> pd.Series:
    return bars["close"].pct_change() * 100.0


def _breakout(bars: pd.DataFrame, n: int, high: bool) -> Check:
    window = bars.iloc[-n - 1 : -1]
    close = float(bars["close"].iloc[-1])
    level = float(window["high"].max() if high else window["low"].min())
    met = close > level if high else close < level
    what = "máximo" if high else "mínimo"
    text = f"Cierre {_num(close)} vs {what} de {n} barras anteriores {_num(level)}"
    return Check(met, text, _day(bars))


def _rsi(b: pd.DataFrame, p: dict[str, float]) -> pd.Series:
    return f.rsi(b["close"], int(p["period"]))


def _emas(b: pd.DataFrame, p: dict[str, float]) -> tuple[pd.Series, pd.Series, str]:
    fast, slow = int(p["fast"]), int(p["slow"])
    return f.ema(b["close"], fast), f.ema(b["close"], slow), f"EMA {fast}/{slow}"


def _ema_cross(b: pd.DataFrame, p: dict[str, float], up: bool) -> Check:
    fast, slow, label = _emas(b, p)
    return _cross(b, fast, slow, up, label)


def _macd_cross(b: pd.DataFrame, up: bool) -> Check:
    m = f.macd(b["close"])
    return _cross(b, m["macd"], m["signal"], up, "MACD/señal")


PERIOD = AlertParam("period", "Periodo", 14, 2, 200)
FAST = AlertParam("fast", "EMA rápida", 20, 1, 400)
SLOW = AlertParam("slow", "EMA lenta", 50, 2, 400)
WINDOW = AlertParam("window", "Barras", 20, 2, 400)


PRICE = AlertParam("value", "Precio", 100, 0.0001, 1e9, 2)


SPECS: tuple[AlertSpec, ...] = (
    AlertSpec(AlertKind.PRICE_ABOVE, "Cierre > {value}", (PRICE,), True, lambda p: 1,
              lambda b, p: _level(b, ">", "Cierre", b["close"], p["value"], 2)),
    AlertSpec(AlertKind.PRICE_BELOW, "Cierre < {value}", (PRICE,), True, lambda p: 1,
              lambda b, p: _level(b, "<", "Cierre", b["close"], p["value"], 2)),
    AlertSpec(AlertKind.CHANGE_ABOVE, "Cambio diario > {value} %",
              (AlertParam("value", "Cambio %", 3, -100, 1000, 2),), True, lambda p: 2,
              lambda b, p: _level(b, ">", "Cambio", _change(b), p["value"], 2, " %")),
    AlertSpec(AlertKind.CHANGE_BELOW, "Cambio diario < {value} %",
              (AlertParam("value", "Cambio %", -3, -100, 1000, 2),), True, lambda p: 2,
              lambda b, p: _level(b, "<", "Cambio", _change(b), p["value"], 2, " %")),
    AlertSpec(AlertKind.RSI_ABOVE, "RSI {period} > {value}",
              (PERIOD, AlertParam("value", "Nivel", 70, 0, 100, 1)), True,
              lambda p: int(p["period"]) + 1,
              lambda b, p: _level(b, ">", f"RSI {int(p['period'])}", _rsi(b, p), p["value"], 1)),
    AlertSpec(AlertKind.RSI_BELOW, "RSI {period} < {value}",
              (PERIOD, AlertParam("value", "Nivel", 30, 0, 100, 1)), True,
              lambda p: int(p["period"]) + 1,
              lambda b, p: _level(b, "<", f"RSI {int(p['period'])}", _rsi(b, p), p["value"], 1)),
    AlertSpec(AlertKind.EMA_CROSS_UP, "EMA {fast} cruza por encima de EMA {slow}",
              (FAST, SLOW), False, lambda p: int(p["slow"]) + 1,
              lambda b, p: _ema_cross(b, p, True)),
    AlertSpec(AlertKind.EMA_CROSS_DOWN, "EMA {fast} cruza por debajo de EMA {slow}",
              (FAST, SLOW), False, lambda p: int(p["slow"]) + 1,
              lambda b, p: _ema_cross(b, p, False)),
    AlertSpec(AlertKind.MACD_CROSS_UP, "MACD (12, 26, 9) cruza por encima de su señal",
              (), False, lambda p: 26 + 9, lambda b, p: _macd_cross(b, True)),
    AlertSpec(AlertKind.MACD_CROSS_DOWN, "MACD (12, 26, 9) cruza por debajo de su señal",
              (), False, lambda p: 26 + 9, lambda b, p: _macd_cross(b, False)),
    AlertSpec(AlertKind.BREAKOUT_HIGH, "Cierre supera el máximo de {window} barras",
              (WINDOW,), False, lambda p: int(p["window"]) + 1,
              lambda b, p: _breakout(b, int(p["window"]), True)),
    AlertSpec(AlertKind.BREAKDOWN_LOW, "Cierre cae bajo el mínimo de {window} barras",
              (WINDOW,), False, lambda p: int(p["window"]) + 1,
              lambda b, p: _breakout(b, int(p["window"]), False)),
)  # fmt: skip

ALERT_SPECS: dict[AlertKind, AlertSpec] = {s.kind: s for s in SPECS}


def validate_alert_params(kind: AlertKind, raw: dict[str, Any]) -> dict[str, float]:
    spec = ALERT_SPECS[kind]
    params: dict[str, float] = {}
    for p in spec.params:
        try:
            value = float(raw.get(p.key, p.default))
        except (TypeError, ValueError):
            raise UserError(
                f"{kind}.{p.key} not numeric",
                user_message=f"{p.label}: el valor debe ser numérico.",
            ) from None
        if not p.minimum <= value <= p.maximum:
            raise UserError(
                f"{kind}.{p.key}={value} out of range",
                user_message=f"{p.label}: el valor debe estar entre {p.minimum:g} y {p.maximum:g}.",
            )
        params[p.key] = round(value) if p.decimals == 0 else value
    if "fast" in params and params["fast"] >= params["slow"]:
        raise UserError(
            "fast >= slow",
            user_message="La EMA rápida debe tener un periodo menor que la lenta.",
        )
    return params


@dataclass
class AlertRule:
    symbol: str
    kind: AlertKind
    params: dict[str, float]
    enabled: bool = True
    #: Level alerts: True when the condition was false at the last check (may fire).
    armed: bool = True
    last_bar: date | None = None
    last_triggered_at: datetime | None = None
    created_at: datetime | None = None
    id: int | None = None

    @property
    def spec(self) -> AlertSpec:
        return ALERT_SPECS[self.kind]

    @property
    def description(self) -> str:
        return f"{self.symbol}: {self.spec.describe(self.params)}"


@dataclass(frozen=True)
class Evaluation:
    fired: bool
    check: Check | None
    #: Reason the rule could not be evaluated (e.g. not enough data).
    skipped: str | None = None


def evaluate(rule: AlertRule, bars: pd.DataFrame) -> Evaluation:
    """Evaluate ``rule`` on completed bars and update its state (armed / last_bar)."""
    spec = rule.spec
    needed = max(spec.min_bars(rule.params), 2 if not spec.is_level else 1)
    if len(bars) < needed:
        return Evaluation(False, None, f"datos insuficientes (requiere {needed} barras)")
    check = spec.evaluate(bars, rule.params)
    if pd.isna(bars["close"].iloc[-1]):
        return Evaluation(False, None, "última barra sin datos")

    fired = False
    if spec.is_level:
        if check.met and rule.armed:
            fired = True
            rule.armed = False
        elif not check.met:
            rule.armed = True
    elif check.met and rule.last_bar != check.bar_date:
        fired = True
    rule.last_bar = check.bar_date
    return Evaluation(fired, check)
