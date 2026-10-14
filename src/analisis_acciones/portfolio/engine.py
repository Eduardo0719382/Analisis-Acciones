"""Replay of paper trades: cash, positions (average cost) and profit and loss.

Rules: long positions only (a sale can not exceed the shares held) and no
borrowing (a purchase can not cost more than the cash available). Commissions
are paid in cash; for a purchase they add to the cost basis, for a sale they
reduce the realised result. Trades are applied in date order, ties by entry
order.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from analisis_acciones.models.errors import UserError

BUY, SELL = "buy", "sell"
EPSILON = 1e-9


@dataclass(frozen=True)
class PaperTrade:
    symbol: str
    side: str
    quantity: float
    price: float
    trade_date: date
    commission: float = 0.0
    note: str = ""
    id: int | None = None

    @property
    def value(self) -> float:
        return self.quantity * self.price


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    cost_basis: float = 0.0  # total cost of the shares held, commissions included
    realized: float = 0.0

    @property
    def average_cost(self) -> float:
        return self.cost_basis / self.quantity if self.quantity > EPSILON else 0.0


@dataclass
class PortfolioState:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    commissions: float = 0.0

    @property
    def realized(self) -> float:
        return sum(p.realized for p in self.positions.values())

    def open_positions(self) -> list[Position]:
        return sorted(
            (p for p in self.positions.values() if p.quantity > EPSILON), key=lambda p: p.symbol
        )


def ordered(trades: list[PaperTrade]) -> list[PaperTrade]:
    return sorted(trades, key=lambda t: (t.trade_date, t.id or 0))


def replay(
    trades: list[PaperTrade], initial_cash: float, until: date | None = None
) -> PortfolioState:
    """State after applying ``trades`` (up to ``until``, inclusive). Raises UserError when a
    trade is impossible (selling shares not held, spending cash not available)."""
    state = PortfolioState(cash=initial_cash)
    for trade in ordered(trades):
        if until is not None and trade.trade_date > until:
            break
        position = state.positions.setdefault(trade.symbol, Position(trade.symbol))
        state.commissions += trade.commission
        if trade.side == BUY:
            cost = trade.value + trade.commission
            if cost > state.cash + EPSILON:
                raise UserError(
                    f"not enough cash for {trade}",
                    user_message=(
                        f"Efectivo insuficiente el {trade.trade_date:%d/%m/%Y} para comprar "
                        f"{trade.quantity:g} {trade.symbol} ({cost:,.2f}; disponible "
                        f"{state.cash:,.2f})."
                    ),
                )
            state.cash -= cost
            position.quantity += trade.quantity
            position.cost_basis += cost
        else:
            if trade.quantity > position.quantity + EPSILON:
                raise UserError(
                    f"selling more than held: {trade}",
                    user_message=(
                        f"El {trade.trade_date:%d/%m/%Y} solo había {position.quantity:g} "
                        f"{trade.symbol}: no se pueden vender {trade.quantity:g} (la cartera "
                        "simulada no permite ventas en corto)."
                    ),
                )
            cost_out = position.average_cost * trade.quantity
            proceeds = trade.value - trade.commission
            position.realized += proceeds - cost_out
            position.quantity -= trade.quantity
            position.cost_basis -= cost_out
            if position.quantity <= EPSILON:
                position.quantity, position.cost_basis = 0.0, 0.0
            state.cash += proceeds
    return state


@dataclass(frozen=True)
class Holding:
    symbol: str
    quantity: float
    average_cost: float
    price: float | None  # last close, None when unknown
    market_value: float | None
    unrealized: float | None
    unrealized_pct: float | None
    weight_pct: float | None  # share of total value


@dataclass(frozen=True)
class Valuation:
    initial_cash: float
    cash: float
    holdings: list[Holding]
    realized: float
    commissions: float
    total_value: float | None  # None when a held symbol has no price

    @property
    def total_return_pct(self) -> float | None:
        if self.total_value is None or self.initial_cash <= 0:
            return None
        return (self.total_value / self.initial_cash - 1) * 100

    @property
    def unrealized(self) -> float | None:
        values = [h.unrealized for h in self.holdings]
        return None if any(v is None for v in values) else sum(v for v in values if v is not None)


def value(
    state: PortfolioState, initial_cash: float, prices: Mapping[str, float | None]
) -> Valuation:
    rows = []
    known = True
    invested = 0.0
    for pos in state.open_positions():
        price = prices.get(pos.symbol)
        if price is None:
            known = False
            rows.append(
                Holding(pos.symbol, pos.quantity, pos.average_cost, None, None, None, None, None)
            )
            continue
        market = pos.quantity * price
        invested += market
        unrealized = market - pos.cost_basis
        rows.append(
            Holding(
                pos.symbol,
                pos.quantity,
                pos.average_cost,
                price,
                market,
                unrealized,
                unrealized / pos.cost_basis * 100 if pos.cost_basis else None,
                None,
            )
        )
    total = state.cash + invested if known else None
    if total:
        rows = [
            Holding(
                h.symbol,
                h.quantity,
                h.average_cost,
                h.price,
                h.market_value,
                h.unrealized,
                h.unrealized_pct,
                h.market_value / total * 100 if h.market_value is not None else None,
            )
            for h in rows
        ]
    return Valuation(initial_cash, state.cash, rows, state.realized, state.commissions, total)


def equity_curve(
    trades: list[PaperTrade], initial_cash: float, closes: Mapping[str, pd.Series], end: date
) -> pd.Series:
    """Daily total value from the first trade date to ``end`` (business days).

    Each holding is valued at its last close on or before each day; a day where a
    held symbol has no close yet is left out rather than guessed.
    """
    if not trades:
        return pd.Series(dtype=float)
    days = pd.bdate_range(ordered(trades)[0].trade_date, end)
    aligned = {s: c.sort_index().reindex(days, method="ffill") for s, c in closes.items()}
    values: dict[pd.Timestamp, float] = {}
    for day in days:
        state = replay(trades, initial_cash, until=day.date())
        total = state.cash
        complete = True
        for pos in state.open_positions():
            series = aligned.get(pos.symbol)
            price = series.loc[day] if series is not None else float("nan")
            if price != price:  # NaN: no close known yet
                complete = False
                break
            total += pos.quantity * float(price)
        if complete:
            values[day] = total
    return pd.Series(values, dtype=float)
