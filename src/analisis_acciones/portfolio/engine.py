"""Replay of paper trades: cash, positions (average cost) and profit and loss.

Rules: long positions only (a sale can not exceed the shares held) and no
borrowing (a purchase can not cost more than the cash available). Commissions
are paid in cash; for a purchase they add to the cost basis, for a sale they
reduce the realised result. Trades are applied in date order, ties by entry
order.

Corporate events
----------------
Prices from the data source are split-adjusted for the whole history. Trades
keep the real price and quantity the user entered; ``adjust_for_splits``
converts them into today's share units (quantity × later splits, price ÷ later
splits) so they match the price history. Dividends (per current share) are
paid in cash on their ex-date to the shares held before that day.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date

import numpy as np
import pandas as pd

from analisis_acciones.models.errors import UserError

BUY, SELL = "buy", "sell"
DIVIDEND, SPLIT = "dividend", "split"
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
    review: str = ""
    split_factor: float = 1.0  # set by adjust_for_splits; messages show the original units
    currency: str = "USD"  # currency of ``price``; the replay works in dollars
    fx_rate: float = 1.0  # dollars per unit of ``currency`` on the trade date

    @property
    def value(self) -> float:
        return self.quantity * self.price


@dataclass(frozen=True)
class CorporateEvent:
    symbol: str
    day: date  # ex-date
    kind: str  # DIVIDEND (amount per share) or SPLIT (new shares per old share)
    value: float


@dataclass(frozen=True)
class AppliedEvent:
    """A corporate event that affected the portfolio, with its effect."""

    event: CorporateEvent
    shares: float  # shares held (today's units) on the event
    cash: float  # cash credited (dividends, after withholding), 0 for splits
    withheld: float = 0.0  # tax withheld from the dividend


@dataclass(frozen=True)
class ClosedTrade:
    """Result of one sale against the average cost of the shares sold."""

    trade: PaperTrade  # in the units used by the replay
    cost: float  # average cost of the shares sold, purchase commissions included
    proceeds: float  # sale value minus its commission
    opened_on: date | None = None  # when the position was opened (from zero shares)

    @property
    def result(self) -> float:
        return self.proceeds - self.cost

    @property
    def result_pct(self) -> float | None:
        return self.result / self.cost * 100 if self.cost > EPSILON else None


def split_factor_after(splits: pd.Series, day: date) -> float:
    """Product of split ratios with an ex-date after ``day`` (1.0 when none)."""
    later = splits[(splits.index > pd.Timestamp(day)) & (splits > 0)]
    factor = 1.0
    for ratio in later:
        factor *= float(ratio)
    return factor


def adjust_for_splits(
    trades: list[PaperTrade], splits: Mapping[str, pd.Series]
) -> list[PaperTrade]:
    """Trades expressed in today's share units (see module docstring)."""
    out = []
    for t in trades:
        series = splits.get(t.symbol)
        factor = split_factor_after(series, t.trade_date) if series is not None else 1.0
        if factor == 1.0:
            out.append(t)
        else:
            out.append(
                replace(
                    t, quantity=t.quantity * factor, price=t.price / factor, split_factor=factor
                )
            )
    return out


def in_dollars(trades: list[PaperTrade]) -> list[PaperTrade]:
    """Trades with the price converted at their recorded exchange rate."""
    return [
        t
        if t.currency == "USD" and t.fx_rate == 1.0
        else replace(t, price=t.price * t.fx_rate, currency="USD", fx_rate=1.0)
        for t in trades
    ]


@dataclass
class Position:
    symbol: str
    quantity: float = 0.0
    cost_basis: float = 0.0  # total cost of the shares held, commissions included
    realized: float = 0.0
    dividends: float = 0.0
    opened_on: date | None = None  # first purchase since the position was last empty

    @property
    def average_cost(self) -> float:
        return self.cost_basis / self.quantity if self.quantity > EPSILON else 0.0


@dataclass
class PortfolioState:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    commissions: float = 0.0
    applied: list[AppliedEvent] = field(default_factory=list)
    closed: list[ClosedTrade] = field(default_factory=list)
    withheld: float = 0.0  # dividend tax withheld

    @property
    def dividends(self) -> float:
        return sum(p.dividends for p in self.positions.values())

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
    trades: list[PaperTrade],
    initial_cash: float,
    until: date | None = None,
    events: list[CorporateEvent] | tuple[CorporateEvent, ...] = (),
    withholding_pct: float = 0.0,
) -> PortfolioState:
    """State after applying ``trades`` and ``events`` (up to ``until``, inclusive).

    ``withholding_pct`` of each dividend is withheld as tax (only the rest is credited).

    Trades must already be in today's share units (``adjust_for_splits``). On a
    given day, events are applied before trades: a dividend goes to the shares
    held before its ex-date. Raises UserError when a trade is impossible
    (selling shares not held, spending cash not available).
    """
    state = PortfolioState(cash=initial_cash)
    for day, item in _timeline(trades, events):
        if until is not None and day > until:
            break
        _apply(state, item, withholding_pct)
    return state


def _timeline(
    trades: list[PaperTrade], events: list[CorporateEvent] | tuple[CorporateEvent, ...]
) -> list[tuple[date, PaperTrade | CorporateEvent]]:
    """Events and trades in application order: by day, events before trades, then entry order."""
    items: list[tuple[date, int, int, PaperTrade | CorporateEvent]] = [
        (e.day, 0, i, e) for i, e in enumerate(events)
    ]
    items += [(t.trade_date, 1, t.id or 0, t) for t in trades]
    items.sort(key=lambda item: (item[0], item[1], item[2]))
    return [(day, item) for day, _order, _key, item in items]


def _apply(state: PortfolioState, item: PaperTrade | CorporateEvent, withholding: float) -> None:
    if isinstance(item, CorporateEvent):
        _apply_event(state, item, withholding)
    else:
        _apply_trade(state, item)


def _apply_event(state: PortfolioState, event: CorporateEvent, withholding_pct: float) -> None:
    position = state.positions.get(event.symbol)
    if position is None or position.quantity <= EPSILON:
        return
    cash = withheld = 0.0
    if event.kind == DIVIDEND:
        gross = position.quantity * event.value
        withheld = gross * withholding_pct / 100
        cash = gross - withheld
        position.dividends += cash
        state.cash += cash
        state.withheld += withheld
    state.applied.append(AppliedEvent(event, position.quantity, cash, withheld))


def _apply_trade(state: PortfolioState, trade: PaperTrade) -> None:
    position = state.positions.setdefault(trade.symbol, Position(trade.symbol))
    state.commissions += trade.commission
    if trade.side == BUY:
        cost = trade.value + trade.commission
        if cost > state.cash + 1e-6:
            raise UserError(
                f"not enough cash for {trade}",
                user_message=(
                    f"Efectivo insuficiente el {trade.trade_date:%d/%m/%Y} para comprar "
                    f"{trade.quantity / trade.split_factor:g} {trade.symbol} ({cost:,.2f} $; "
                    f"disponible {state.cash:,.2f} $)."
                ),
            )
        state.cash -= cost
        if position.quantity <= EPSILON:
            position.opened_on = trade.trade_date
        position.quantity += trade.quantity
        position.cost_basis += cost
        return
    if trade.quantity > position.quantity + 1e-6:
        raise UserError(
            f"selling more than held: {trade}",
            user_message=(
                f"El {trade.trade_date:%d/%m/%Y} solo había "
                f"{position.quantity / trade.split_factor:g} {trade.symbol}: no se pueden vender "
                f"{trade.quantity / trade.split_factor:g} (la cartera "
                "simulada no permite ventas en corto)."
            ),
        )
    quantity = min(trade.quantity, position.quantity)  # absorb rounding of fractions
    cost_out = position.average_cost * quantity
    proceeds = trade.value - trade.commission
    position.realized += proceeds - cost_out
    state.closed.append(ClosedTrade(trade, cost_out, proceeds, position.opened_on))
    position.quantity -= quantity
    position.cost_basis -= cost_out
    if position.quantity <= 1e-6:
        position.quantity, position.cost_basis = 0.0, 0.0
    state.cash += proceeds


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
    dividends: float = 0.0
    withheld: float = 0.0  # dividend tax withheld

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
    return Valuation(
        initial_cash,
        state.cash,
        rows,
        state.realized,
        state.commissions,
        total,
        state.dividends,
        state.withheld,
    )


def equity_curve(
    trades: list[PaperTrade],
    initial_cash: float,
    closes: Mapping[str, pd.Series],
    end: date,
    events: list[CorporateEvent] | tuple[CorporateEvent, ...] = (),
    withholding_pct: float = 0.0,
) -> pd.Series:
    """Daily total value from the first trade date to ``end`` (see ``daily_values``)."""
    return daily_values(trades, initial_cash, closes, end, events, withholding_pct)[0]


def daily_values(
    trades: list[PaperTrade],
    initial_cash: float,
    closes: Mapping[str, pd.Series],
    end: date,
    events: list[CorporateEvent] | tuple[CorporateEvent, ...] = (),
    withholding_pct: float = 0.0,
) -> tuple[pd.Series, pd.DataFrame]:
    """Daily total value and market value per symbol (business days, first trade to ``end``).

    Each holding is valued at its last close on or before each day; a day where a
    held symbol has no close yet is left out rather than guessed. A symbol not held
    on a day is worth 0 that day. The history is replayed once, day by day (same
    result as ``replay(..., until=day)`` for every day).
    """
    if not trades:
        return pd.Series(dtype=float), pd.DataFrame(dtype=float)
    days = pd.bdate_range(ordered(trades)[0].trade_date, end)
    symbols = sorted({t.symbol for t in trades})
    column = {s: i for i, s in enumerate(symbols)}
    prices = np.full((len(days), len(symbols)), np.nan)
    for s, c in closes.items():
        if s in column:
            prices[:, column[s]] = c.sort_index().reindex(days, method="ffill").to_numpy(float)
    timeline = _timeline(trades, events)
    state = PortfolioState(cash=initial_cash)
    nxt = 0
    keep: list[int] = []
    totals: list[float] = []
    rows: list[np.ndarray] = []
    for i, day in enumerate(days):
        today = day.date()
        while nxt < len(timeline) and timeline[nxt][0] <= today:
            _apply(state, timeline[nxt][1], withholding_pct)
            nxt += 1
        row = np.zeros(len(symbols))
        complete = True
        for pos in state.open_positions():
            price = prices[i, column[pos.symbol]] if pos.symbol in column else np.nan
            if np.isnan(price):  # no close known yet
                complete = False
                break
            row[column[pos.symbol]] = pos.quantity * price
        if complete:
            keep.append(i)
            totals.append(state.cash + float(row.sum()))
            rows.append(row)
    index = days[keep]
    frame = pd.DataFrame(np.array(rows).reshape(len(rows), len(symbols)), index=index,
                         columns=symbols, dtype=float)  # fmt: skip
    return pd.Series(totals, index=index, dtype=float), frame
