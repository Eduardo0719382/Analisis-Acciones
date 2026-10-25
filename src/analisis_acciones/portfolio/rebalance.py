"""Rebalancing plan: trades that bring a paper portfolio to target weights.

Rules (deterministic, explained to the user):

* Targets are percentages of the total value; whatever is not assigned stays in
  cash. A held symbol without a target has a target of 0 % (it is sold).
* Prices are the valuation prices (last close); quantities may be fractional.
* Differences smaller than ``tolerance_pct`` points of weight, or than
  ``min_trade`` dollars, are ignored to avoid tiny trades.
* Sales are done first; purchases are scaled down together if their cost plus
  commissions does not fit in the cash available after the sales.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from analisis_acciones.portfolio.engine import BUY, SELL, Valuation

QUANTITY_DECIMALS = 6
CASH_MARGIN = 0.01  # dollars kept aside for rounding


@dataclass(frozen=True)
class RebalanceOrder:
    symbol: str
    side: str
    quantity: float
    price: float
    current_pct: float
    target_pct: float

    @property
    def value(self) -> float:
        return self.quantity * self.price


@dataclass(frozen=True)
class RebalancePlan:
    orders: list[RebalanceOrder] = field(default_factory=list)
    cash_target_pct: float = 0.0
    cash_after: float = 0.0
    commissions: float = 0.0
    scaled: bool = False  # purchases reduced to fit the cash
    problems: list[str] = field(default_factory=list)
    # symbol -> (current %, target %) for every symbol considered
    weights: dict[str, tuple[float, float]] = field(default_factory=dict)


def plan_rebalance(
    valuation: Valuation,
    targets: Mapping[str, float],
    commission_for: Callable[[float], float],
    prices: Mapping[str, float | None] | None = None,
    tolerance_pct: float = 0.5,
    min_trade: float = 1.0,
) -> RebalancePlan:
    total = valuation.total_value
    if total is None or total <= 0:
        return RebalancePlan(problems=["Falta el precio de algún activo: no se puede calcular."])
    if sum(targets.values()) > 100 + 1e-9:
        return RebalancePlan(problems=["Los pesos objetivo suman más del 100 %."])
    held = {h.symbol: h for h in valuation.holdings}
    known: dict[str, float | None] = dict(prices or {})
    known.update({s: h.price for s, h in held.items()})
    missing = sorted(s for s in set(targets) | set(held) if not (known.get(s) or 0) > 0)
    if missing:
        return RebalancePlan(problems=["Sin cotización para " + ", ".join(missing) + "."])
    weights: dict[str, tuple[float, float]] = {}
    sells: list[RebalanceOrder] = []
    wanted_buys: list[tuple[str, float, float, float, float]] = []
    for symbol in sorted(set(held) | set(targets)):
        h = held.get(symbol)
        price = float(known[symbol] or 0.0)
        current_value = (h.market_value or 0.0) if h is not None else 0.0
        held_quantity = h.quantity if h is not None else 0.0
        current_pct = current_value / total * 100
        target_pct = float(targets.get(symbol, 0.0))
        weights[symbol] = (current_pct, target_pct)
        diff = total * target_pct / 100 - current_value
        if abs(current_pct - target_pct) < tolerance_pct and target_pct > 0:
            continue
        if abs(diff) < min_trade:
            continue
        if diff < 0:
            quantity = min(round(-diff / price, QUANTITY_DECIMALS), held_quantity)
            if target_pct == 0:
                quantity = held_quantity  # sell everything, no fraction left behind
            sells.append(RebalanceOrder(symbol, SELL, quantity, price, current_pct, target_pct))
        else:
            wanted_buys.append((symbol, diff, price, current_pct, target_pct))

    cash = valuation.cash
    commissions = 0.0
    for order in sells:
        fee = commission_for(order.value)
        commissions += fee
        cash += order.value - fee

    scale = 1.0
    buys: list[RebalanceOrder] = []
    for _ in range(20):
        buys = [
            RebalanceOrder(s, BUY, round(d * scale / p, QUANTITY_DECIMALS), p, cur, tgt)
            for s, d, p, cur, tgt in wanted_buys
        ]
        buys = [b for b in buys if b.value >= min_trade]
        cost = sum(b.value + commission_for(b.value) for b in buys)
        if cost <= cash - CASH_MARGIN or not buys:
            break
        scale *= max((cash - CASH_MARGIN) / cost, 0.0) * 0.999
    buy_fees = sum(commission_for(b.value) for b in buys)
    cash_after = cash - sum(b.value for b in buys) - buy_fees
    return RebalancePlan(
        orders=sells + buys,
        cash_target_pct=100 - sum(targets.values()),
        cash_after=cash_after,
        commissions=commissions + buy_fees,
        scaled=scale < 1.0,
        weights=weights,
    )
