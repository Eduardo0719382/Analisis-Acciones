"""Conditions of a paper portfolio worth a notice (pure; the service remembers what was said).

* loss: a holding is down ``loss_pct`` % or more from its average cost;
* drift: a symbol's weight is ``drift_pts`` points or more away from its target;
* drawdown: the portfolio value is ``drawdown_pct`` % or more below its highest value.

A threshold of 0 switches that rule off. Each condition has a stable key so a
notice is given once while the condition lasts.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd

from analisis_acciones.portfolio.engine import Valuation


@dataclass(frozen=True)
class AlertThresholds:
    loss_pct: float = 0.0
    drift_pts: float = 0.0
    drawdown_pct: float = 0.0

    @property
    def active(self) -> bool:
        return self.loss_pct > 0 or self.drift_pts > 0 or self.drawdown_pct > 0


def _pct(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def conditions(valuation: Valuation, equity: pd.Series, targets: Mapping[str, float],
               limits: AlertThresholds) -> dict[str, tuple[str, str]]:  # fmt: skip
    """Key -> (symbol or "", message) for every condition true now."""
    found: dict[str, tuple[str, str]] = {}
    if limits.loss_pct > 0:
        for h in valuation.holdings:
            if h.unrealized_pct is not None and h.unrealized_pct <= -limits.loss_pct:
                found[f"loss:{h.symbol}"] = (
                    h.symbol,
                    f"{h.symbol} pierde {_pct(-h.unrealized_pct)} % desde su coste medio "
                    f"(aviso a partir de {_pct(limits.loss_pct)} %).",
                )
    if limits.drift_pts > 0 and targets and valuation.total_value:
        weights = {h.symbol: h.weight_pct or 0.0 for h in valuation.holdings}
        for symbol in sorted(set(targets) | set(weights)):
            current, target = weights.get(symbol, 0.0), targets.get(symbol, 0.0)
            if abs(current - target) >= limits.drift_pts:
                found[f"drift:{symbol}"] = (
                    symbol,
                    f"{symbol} pesa {_pct(current)} % y su objetivo es {_pct(target)} % "
                    f"(desvío de {_pct(abs(current - target))} puntos).",
                )
    if limits.drawdown_pct > 0 and len(equity) >= 2:
        peak = float(equity.max())
        last = float(equity.iloc[-1])
        drop = (1 - last / peak) * 100 if peak > 0 else 0.0
        if drop >= limits.drawdown_pct:
            found["drawdown"] = (
                "",
                f"La cartera está un {_pct(drop)} % por debajo de su máximo "
                f"(aviso a partir de {_pct(limits.drawdown_pct)} %).",
            )
    return found
