"""Projection methods.

Volatility cone
    Assumes log-returns are independent with the historical mean (optional) and
    standard deviation σ of the last ``lookback`` bars. After h bars the price
    quantile q is P₀·exp(μ·h + z_q·σ·√h). Real returns have fat tails and
    changing volatility, so extreme moves are more frequent than the cone says.

Regression channel
    Ordinary least squares of ln(close) on time over the last ``lookback``
    bars, extrapolated h bars ahead, ± 1 and 2 standard deviations of the
    residuals. It only extends the recent trend; it does not model reversals.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from analisis_acciones.models.errors import UserError

#: Standard normal quantiles for the bands shown.
QUANTILES: dict[str, float] = {
    "p05": -1.6448536269514722,
    "p25": -0.6744897501960817,
    "p50": 0.0,
    "p75": 0.6744897501960817,
    "p95": 1.6448536269514722,
}
METHODS = ("cone", "regression")


@dataclass(frozen=True)
class Projection:
    method: str
    base_price: float
    horizon: int
    #: Band name -> projected price for steps 1..horizon.
    bands: dict[str, list[float]]
    explanation: tuple[str, ...]
    stats: dict[str, float] = field(default_factory=dict)
    #: Band name -> fitted values over the last ``len(values)`` bars (regression only).
    fitted: dict[str, list[float]] = field(default_factory=dict)

    def at_horizon(self) -> dict[str, float]:
        return {name: float(values[-1]) for name, values in self.bands.items()}


def _validate(closes: np.ndarray, horizon: int, lookback: int) -> None:
    if not 1 <= horizon <= 500:
        raise UserError("bad horizon", user_message="El horizonte debe estar entre 1 y 500 barras.")
    if lookback < 20:
        raise UserError("bad lookback", user_message="La ventana debe tener al menos 20 barras.")
    if len(closes) < lookback + 1:
        raise UserError(
            "not enough history",
            user_message=f"Se necesitan al menos {lookback + 1} barras (hay {len(closes)}).",
        )
    if (closes <= 0).any() or not np.isfinite(closes).all():
        raise UserError("bad prices", user_message="Hay precios no válidos en la ventana.")


def volatility_cone(closes: np.ndarray, horizon: int, lookback: int = 252,
                    use_drift: bool = False) -> Projection:  # fmt: skip
    closes = np.asarray(closes, dtype=float)
    _validate(closes, horizon, lookback)
    window = closes[-(lookback + 1) :]
    returns = np.diff(np.log(window))
    sigma = float(returns.std(ddof=1))
    mu = float(returns.mean()) if use_drift else 0.0
    base = float(closes[-1])
    steps = np.arange(1, horizon + 1)
    bands = {
        name: (base * np.exp(mu * steps + z * sigma * np.sqrt(steps))).tolist()
        for name, z in QUANTILES.items()
    }
    explanation = (
        f"Volatilidad por barra (σ de los rendimientos logarítmicos de {lookback} barras): "
        f"{sigma * 100:.2f} %",
        "Deriva: "
        + (f"media histórica {mu * 100:.3f} % por barra" if use_drift
           else "cero (sin tendencia supuesta)"),
        "Rango 5–95 %: donde estaría el precio 9 de cada 10 veces si los rendimientos fueran "
        "normales e independientes. En la práctica los movimientos extremos son más frecuentes.",
    )  # fmt: skip
    return Projection("cone", base, horizon, bands, explanation,
                      {"sigma": sigma, "mu": mu})  # fmt: skip


def regression_channel(closes: np.ndarray, horizon: int, lookback: int = 120) -> Projection:
    closes = np.asarray(closes, dtype=float)
    _validate(closes, horizon, lookback)
    y = np.log(closes[-lookback:])
    x = np.arange(lookback, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    fitted = intercept + slope * x
    residuals = y - fitted
    s = float(residuals.std(ddof=2))
    ss_res = float((residuals**2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    future_x = np.arange(lookback, lookback + horizon, dtype=float)
    center = intercept + slope * future_x
    offsets = {"p05": -2 * s, "p25": -s, "p50": 0.0, "p75": s, "p95": 2 * s}
    bands = {name: np.exp(center + k).tolist() for name, k in offsets.items()}
    past = {name: np.exp(fitted + k).tolist() for name, k in offsets.items()}
    explanation = (
        f"Pendiente del canal: {(math.exp(slope) - 1) * 100:+.3f} % por barra "
        f"(ajuste de {lookback} barras, R² = {r2:.2f})",
        f"Desviación de los residuos: {s * 100:.2f} % (bandas a ±1 y ±2 desviaciones)",
        "Solo prolonga la tendencia reciente: no anticipa cambios de tendencia. Un R² bajo "
        "indica que la tendencia explica poco del movimiento.",
    )
    return Projection("regression", float(closes[-1]), horizon, bands, explanation,
                      {"slope": float(slope), "r2": r2, "resid_sd": s}, past)  # fmt: skip


def project(method: str, closes: np.ndarray, horizon: int, lookback: int) -> Projection:
    if method == "cone":
        return volatility_cone(closes, horizon, lookback)
    if method == "regression":
        return regression_channel(closes, horizon, lookback)
    raise UserError(f"unknown method {method}", user_message="Método de proyección desconocido.")


@dataclass(frozen=True)
class Calibration:
    samples: int
    inside_90: float  # share of outcomes inside p05..p95 (expected ~0.90 for the cone)
    inside_50: float  # share inside p25..p75 (expected ~0.50)
    median_abs_error_pct: float  # |actual − p50| / actual, median over samples
    step: int


def calibrate(closes: np.ndarray, method: str, horizon: int, lookback: int,
              step: int = 5, max_samples: int = 400) -> Calibration | None:  # fmt: skip
    """Walk-forward test: at each origin t, project with data up to t only, compare at t+h."""
    closes = np.asarray(closes, dtype=float)
    first = lookback + 1
    last = len(closes) - 1 - horizon
    if last < first:
        return None
    origins = list(range(first, last + 1, step))[-max_samples:]
    inside_90 = inside_50 = 0
    errors = []
    for t in origins:
        projection = project(method, closes[: t + 1], horizon, lookback)
        ends = projection.at_horizon()
        actual = closes[t + horizon]
        inside_90 += ends["p05"] <= actual <= ends["p95"]
        inside_50 += ends["p25"] <= actual <= ends["p75"]
        errors.append(abs(actual - ends["p50"]) / actual)
    n = len(origins)
    return Calibration(n, float(inside_90 / n), float(inside_50 / n),
                       float(np.median(errors) * 100), step)  # fmt: skip


def future_frame(bars: pd.DataFrame, projection: Projection, dates: list[str]) -> pd.DataFrame:
    """Projection bands indexed by future dates (for export or display)."""
    return pd.DataFrame(projection.bands, index=pd.Index(dates[: projection.horizon], name="date"))
