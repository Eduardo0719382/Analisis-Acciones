"""Available strategies and their parameters."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from analisis_acciones.analysis.exhaustion import Params as ExhaustionParams
from analisis_acciones.analysis.exhaustion import signal_series
from analisis_acciones.indicators import functions as f
from analisis_acciones.indicators.registry import ParamSpec
from analisis_acciones.models.errors import UserError


def crosses_above(a: pd.Series, b: pd.Series | float) -> pd.Series:
    """True on bars where ``a`` moves from <= b to > b (both bars defined)."""
    b_series = b if isinstance(b, pd.Series) else pd.Series(b, index=a.index)
    prev_a, prev_b = a.shift(1), b_series.shift(1)
    valid = a.notna() & b_series.notna() & prev_a.notna() & prev_b.notna()
    return (valid & (prev_a <= prev_b) & (a > b_series)).astype(bool)


def crosses_below(a: pd.Series, b: pd.Series | float) -> pd.Series:
    b_series = b if isinstance(b, pd.Series) else pd.Series(b, index=a.index)
    prev_a, prev_b = a.shift(1), b_series.shift(1)
    valid = a.notna() & b_series.notna() & prev_a.notna() & prev_b.notna()
    return (valid & (prev_a >= prev_b) & (a < b_series)).astype(bool)


def _signals(entry: pd.Series, exit_: pd.Series) -> pd.DataFrame:
    return pd.DataFrame({"entry": entry.astype(bool), "exit": exit_.astype(bool)})


def ema_cross(bars: pd.DataFrame, p: dict[str, Any]) -> pd.DataFrame:
    fast = f.ema(bars["close"], int(p["fast"]))
    slow = f.ema(bars["close"], int(p["slow"]))
    return _signals(crosses_above(fast, slow), crosses_below(fast, slow))


def rsi_reversion(bars: pd.DataFrame, p: dict[str, Any]) -> pd.DataFrame:
    rsi = f.rsi(bars["close"], int(p["period"]))
    return _signals(crosses_above(rsi, float(p["low"])), crosses_above(rsi, float(p["high"])))


def trend_only(bars: pd.DataFrame, p: dict[str, Any]) -> pd.DataFrame:
    """Close crosses above / below its simple moving average."""
    close = bars["close"]
    average = f.sma(close, int(p["period"]))
    return _signals(crosses_above(close, average), crosses_below(close, average))


def exhaustion_exit(bars: pd.DataFrame, p: dict[str, Any]) -> pd.Series:
    """Bars where the up-trend shows exhaustion signs (only data up to each bar is used)."""
    params = ExhaustionParams(rsi_high=float(p["rsi_high"]), threshold=int(p["conditions"]))
    return signal_series(bars, params) > 0


def exhaustion_variants(bars: pd.DataFrame, period: int,
                        exhausted: pd.Series) -> dict[str, pd.DataFrame]:  # fmt: skip
    """Signals of the trend strategy without / with the exhaustion exit / with re-entry.

    ``exhausted``: bars with up-trend exhaustion signs. Keys: ``trend``, ``exit``, ``reentry``.
    """
    close = bars["close"]
    average = f.sma(close, period)
    base = trend_only(bars, {"period": period})
    faded = exhausted.shift(1, fill_value=False) & ~exhausted & (close > average)
    return {
        "trend": base,
        "exit": _signals(base["entry"], base["exit"] | exhausted),
        "reentry": _signals(base["entry"] | faded, base["exit"] | exhausted),
    }


def trend_exhaustion(bars: pd.DataFrame, p: dict[str, Any]) -> pd.DataFrame:
    """``trend_only`` that also exits as soon as the rise shows exhaustion signs."""
    return exhaustion_variants(bars, int(p["period"]), exhaustion_exit(bars, p))["exit"]


def trend_exhaustion_reentry(bars: pd.DataFrame, p: dict[str, Any]) -> pd.DataFrame:
    """``trend_exhaustion`` that buys again when the exhaustion signs fade while the close is
    still above its average (instead of waiting for a new cross)."""
    return exhaustion_variants(bars, int(p["period"]), exhaustion_exit(bars, p))["reentry"]


@dataclass(frozen=True)
class StrategySpec:
    id: str
    name: str
    entry_rule: str
    exit_rule: str
    params: tuple[ParamSpec, ...]
    signals: Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]
    #: The same strategy without the rule under test, run alongside for comparison.
    reference: Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame] | None = None
    reference_name: str = ""

    def defaults(self) -> dict[str, int | float]:
        return {p.key: p.default for p in self.params}

    def describe(self, params: dict[str, Any]) -> tuple[str, str]:
        values = {k: (int(v) if float(v).is_integer() else v) for k, v in params.items()}
        return self.entry_rule.format(**values), self.exit_rule.format(**values)


STRATEGIES: tuple[StrategySpec, ...] = (
    StrategySpec(
        id="ema_cross",
        name="Cruce de medias exponenciales",
        entry_rule="Entrada: EMA {fast} cruza por encima de EMA {slow}",
        exit_rule="Salida: EMA {fast} cruza por debajo de EMA {slow}",
        params=(
            ParamSpec("fast", "EMA rápida", 20, 1, 400),
            ParamSpec("slow", "EMA lenta", 50, 2, 400),
        ),
        signals=ema_cross,
    ),
    StrategySpec(
        id="rsi_reversion",
        name="Reversión con RSI",
        entry_rule="Entrada: RSI {period} cruza al alza el nivel {low}",
        exit_rule="Salida: RSI {period} cruza al alza el nivel {high}",
        params=(
            ParamSpec("period", "Periodo RSI", 14, 2, 200),
            ParamSpec("low", "Nivel de entrada", 30, 1, 99),
            ParamSpec("high", "Nivel de salida", 70, 1, 99),
        ),
        signals=rsi_reversion,
    ),
    StrategySpec(
        id="trend_exhaustion",
        name="Tendencia con salida por agotamiento",
        entry_rule="Entrada: el cierre cruza al alza su media de {period}",
        exit_rule="Salida: el cierre cruza a la baja su media de {period}, o antes si la subida "
        "muestra {conditions} o más señales de agotamiento (RSI de sobrecompra {rsi_high})",
        params=(
            ParamSpec("period", "Media simple", 50, 5, 400),
            ParamSpec("conditions", "Señales de agotamiento", 3, 1, 6),
            ParamSpec("rsi_high", "RSI de sobrecompra", 70, 55, 95),
        ),
        signals=trend_exhaustion,
        reference=trend_only,
        reference_name="Misma tendencia sin salida por agotamiento",
    ),
    StrategySpec(
        id="trend_exhaustion_reentry",
        name="Tendencia con salida por agotamiento y re-entrada",
        entry_rule="Entrada: el cierre cruza al alza su media de {period}, o vuelve a comprar "
        "cuando desaparecen las señales de agotamiento con el cierre aún por encima de la media",
        exit_rule="Salida: el cierre cruza a la baja su media de {period}, o antes si la subida "
        "muestra {conditions} o más señales de agotamiento (RSI de sobrecompra {rsi_high})",
        params=(
            ParamSpec("period", "Media simple", 50, 5, 400),
            ParamSpec("conditions", "Señales de agotamiento", 3, 1, 6),
            ParamSpec("rsi_high", "RSI de sobrecompra", 70, 55, 95),
        ),
        signals=trend_exhaustion_reentry,
        reference=trend_only,
        reference_name="Misma tendencia sin salida por agotamiento",
    ),
)
STRATEGY_REGISTRY = {s.id: s for s in STRATEGIES}


def validate_strategy_params(spec: StrategySpec, raw: dict[str, Any]) -> dict[str, int | float]:
    params: dict[str, int | float] = {}
    for p in spec.params:
        try:
            value = float(raw.get(p.key, p.default))
        except (TypeError, ValueError):
            raise UserError(
                f"{p.key} not numeric",
                user_message=f"{p.label}: el valor debe ser numérico.",
            ) from None
        if not p.minimum <= value <= p.maximum:
            raise UserError(
                f"{p.key} out of range",
                user_message=f"{p.label}: debe estar entre {p.minimum:g} y {p.maximum:g}.",
            )
        params[p.key] = int(value) if p.kind == "int" else value
    if spec.id == "ema_cross" and params["fast"] >= params["slow"]:
        raise UserError(
            "fast >= slow",
            user_message="La EMA rápida debe tener un periodo menor que la lenta.",
        )
    if spec.id == "rsi_reversion" and params["low"] >= params["high"]:
        raise UserError(
            "low >= high",
            user_message="El nivel de entrada debe ser menor que el de salida.",
        )
    return params
