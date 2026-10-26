"""A profile's virtual book, rebuilt from its filled orders (never from expected prices).

* Cash moves in whole cents, rounded the way the paper account does it (seen 2026-10-26):
  a buy debits the amount rounded up, a sell credits it rounded down.
* Buy: the cash pays ``filled_qty × filled_price`` plus the dollar fees; the position gets
  ``filled_qty`` minus the coin fee (crypto). The cost basis includes every fee.
* Sell: the cash receives ``filled_qty × filled_price`` minus the dollar fees; the realized
  result is that minus the average cost of the quantity sold.
* Orders still open reserve their dollars (buys) or quantity (sells), so a profile can
  never spend or sell the same thing twice.
"""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from analisis_acciones.lab.store import OPEN_STATES

DUST = 1e-9
#: After a sell, a remainder below this share of the position is rounding dust: Alpaca rounds
#: the coin fee of each partial fill, so the book can hold a few 1e-9 more than the account.
RESIDUE = 1e-4


@dataclass
class Position:
    symbol: str
    qty: float = 0.0
    cost: float = 0.0  # dollars paid for ``qty``, fees included
    reserved_qty: float = 0.0  # quantity an open sell order is already selling

    @property
    def avg_cost(self) -> float:
        return self.cost / self.qty if self.qty > DUST else 0.0

    @property
    def free_qty(self) -> float:
        return max(0.0, self.qty - self.reserved_qty)


@dataclass
class Book:
    profile: str
    capital: float
    cash: float
    reserved_cash: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    realized: float = 0.0
    fees: float = 0.0  # dollars (coin fees valued at their fill price)
    trades: int = 0  # filled orders
    closed_sells: int = 0
    winning_sells: int = 0

    @property
    def free_cash(self) -> float:
        return max(0.0, self.cash - self.reserved_cash)

    def value(self, prices: Mapping[str, float]) -> float:
        """Cash plus positions at ``prices``; a position without a price counts at cost."""
        held = sum(p.qty * prices[s] if s in prices else p.cost for s, p in self.positions.items())
        return self.cash + held

    def unrealized(self, prices: Mapping[str, float]) -> float:
        return sum(p.qty * prices[s] - p.cost for s, p in self.positions.items() if s in prices)


def _cents_up(value: float) -> float:
    return math.ceil(round(value * 100, 6)) / 100


def _cents_down(value: float) -> float:
    return math.floor(round(value * 100, 6)) / 100


def build_book(profile: str, capital: float, orders: Iterable[sqlite3.Row]) -> Book:
    book = Book(profile, capital, cash=capital)
    for o in orders:
        if o["profile"] != profile:
            continue
        symbol, side = str(o["symbol"]), str(o["side"])
        if o["status"] in OPEN_STATES and float(o["filled_qty"] or 0) <= DUST:
            if side == "buy":
                book.reserved_cash += float(o["notional"] or 0)
            else:
                pos = book.positions.setdefault(symbol, Position(symbol))
                pos.reserved_qty += float(o["qty_requested"] or 0)
            continue
        qty, price = float(o["filled_qty"] or 0), float(o["filled_price"] or 0)
        if qty <= DUST or price <= 0:
            continue  # dead or never sent: nothing happened
        fee_coin, fee_usd = float(o["fee_coin"] or 0), float(o["fee_usd"] or 0)
        book.trades += 1
        book.fees += fee_usd + fee_coin * price
        pos = book.positions.setdefault(symbol, Position(symbol))
        if side == "buy":
            paid = _cents_up(qty * price) + fee_usd
            book.cash -= paid
            pos.qty += qty - fee_coin
            pos.cost += paid
        else:
            sold = min(qty, pos.qty)
            avg = pos.avg_cost
            proceeds = _cents_down(qty * price) - fee_usd
            book.cash += proceeds
            result = proceeds - avg * sold
            book.realized += result
            book.closed_sells += 1
            book.winning_sells += result > 0
            before = pos.qty
            pos.cost -= avg * sold
            pos.qty -= sold
            if pos.qty < before * RESIDUE:  # what fee rounding leaves after selling it all
                book.realized -= pos.cost
                pos.qty = pos.cost = 0.0
        if pos.qty <= DUST:
            pos.qty = pos.cost = 0.0
    book.positions = {s: p for s, p in book.positions.items() if p.qty > DUST or p.reserved_qty}
    return book


def max_drawdown(values: Iterable[float]) -> float:
    """Largest fall from a peak, in % (0 when it never fell)."""
    peak, worst = 0.0, 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            worst = min(worst, (v / peak - 1) * 100)
    return -worst
