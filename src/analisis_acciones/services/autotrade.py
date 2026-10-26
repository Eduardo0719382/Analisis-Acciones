"""Sends the orders of the 12 strategy profiles to Alpaca's PAPER account (simulated money).

It is the forward test (``forward_test``) with a broker behind it: every profile owns two
slots (a stock ETF and a cryptocurrency) with a share of its budget, and a small local
ledger remembers what each slot holds, because Alpaca only knows the account's total per
symbol. Each run reconciles the ledger with what the profile's strategy wants *now*:

* wants a position and holds none  -> market buy of the slot's cash (by dollar amount);
* wants none and holds a position  -> market sell of the quantity the slot holds;
* anything else                    -> nothing.

So a run that is missed or repeated never duplicates an order, and the order ids are
deterministic (profile, symbol, side, bar) so Alpaca itself rejects a second copy. Long
only: it never sells what the slot does not hold. ``send=False`` (the default) only shows
what it would do. The client is the paper one: there is no way to point it at real money.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

import pandas as pd

from analisis_acciones.broker.alpaca import (
    AccountInfo,
    BrokerOrder,
    BrokerPosition,
    OrderRequest,
    to_alpaca_symbol,
)
from analisis_acciones.models.errors import AppError
from analisis_acciones.models.market import Interval
from analisis_acciones.services.forward_test import (
    BUDGET,
    ProfileResult,
    SleeveResult,
    run_all,
)

MIN_ORDER_USD = 1.0
_DONE = {"filled"}
_DEAD = {"canceled", "expired", "rejected", "done_for_day", "replaced", "stopped"}


class Broker(Protocol):
    def account(self) -> AccountInfo: ...
    def positions(self) -> list[BrokerPosition]: ...
    def place_order(self, order: OrderRequest) -> BrokerOrder: ...
    def get_order(self, order_id: str) -> BrokerOrder: ...
    def market_open(self) -> bool: ...
    def is_tradable(self, symbol: str) -> bool: ...


@dataclass
class Slot:
    cash: float
    qty: float = 0.0
    open_order_id: str | None = None  # an order sent and not yet seen as filled
    open_side: str | None = None


@dataclass(frozen=True)
class Action:
    key: str  # "<profile id>|<symbol>"
    order: OrderRequest
    reason: str


def slot_key(profile_id: str, symbol: str) -> str:
    return f"{profile_id}|{symbol}"


def wants_position(result: SleeveResult) -> bool:
    """What the strategy asks for after its last completed bar."""
    if result.pending == "buy":
        return True
    if result.pending == "sell":
        return False
    return result.open_position is not None


def bar_tag(last_bar: str) -> str:
    return re.sub(r"[^0-9A-Za-z]", "", last_bar)


def plan(results: list[ProfileResult], ledger: dict[str, Slot],
         account_qty: Callable[[str], float],
         blocked: Callable[[str], str | None] = lambda _s: None,
         deferred: list[str] | None = None) -> list[Action]:  # fmt: skip
    """Orders that bring every slot to what its profile wants. Pure: nothing is sent.

    ``blocked(symbol)`` gives the reason an order for that symbol cannot be sent now (stock
    exchange closed, asset not tradable); those orders are left out and, with ``deferred``,
    their slots are listed as "<slot>: <reason>".
    """
    actions: list[Action] = []
    for result in results:
        for sleeve in result.sleeves:
            symbol = sleeve.sleeve.symbol
            key = slot_key(result.profile.id, symbol)
            slot = ledger.setdefault(key, Slot(cash=sleeve.start_value))
            if slot.open_order_id:
                continue  # wait for the previous order to finish
            held = slot.qty > 0
            want = wants_position(sleeve)
            tag = f"aa-{result.profile.id}-{bar_tag(sleeve.last_bar)}-{bar_tag(symbol)}"
            would_act = (want and not held and slot.cash >= MIN_ORDER_USD) or (held and not want)
            reason = blocked(symbol) if would_act else None
            if reason:
                if deferred is not None:
                    deferred.append(f"{key}: {reason}")
                continue
            if want and not held and slot.cash >= MIN_ORDER_USD:
                order = OrderRequest(symbol, "buy", 0, notional=round(slot.cash - 0.005, 2),
                                     client_order_id=f"{tag}-buy")  # fmt: skip
                actions.append(Action(key, order, "la estrategia pide estar comprado"))
            elif held and not want:
                qty = min(slot.qty, account_qty(symbol))
                if qty > 0:
                    order = OrderRequest(symbol, "sell", qty, client_order_id=f"{tag}-sell")
                    actions.append(Action(key, order, "la estrategia pide salir"))
    return actions


# -- ledger ---------------------------------------------------------------------------------


def load_ledger(path: Path) -> dict[str, Slot]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {k: Slot(**v) for k, v in raw["slots"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def save_ledger(path: Path, ledger: dict[str, Slot]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"budget": BUDGET, "slots": {k: asdict(v) for k, v in ledger.items()}}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
    tmp.replace(path)


def apply_fill(slot: Slot, order: BrokerOrder) -> None:
    price = order.filled_avg_price or 0.0
    if order.side == "buy":
        slot.qty += order.filled_qty
        slot.cash = max(0.0, slot.cash - order.filled_qty * price)
    else:
        slot.qty = max(0.0, slot.qty - order.filled_qty)
        slot.cash += order.filled_qty * price
    if slot.qty < 1e-9:
        slot.qty = 0.0
    slot.open_order_id = slot.open_side = None


def reconcile_open_orders(broker: Broker, ledger: dict[str, Slot]) -> list[str]:
    """Close the slots whose last order has finished; returns lines to show."""
    notes = []
    for key, slot in ledger.items():
        if not slot.open_order_id:
            continue
        order = broker.get_order(slot.open_order_id)
        if order.status in _DONE:
            apply_fill(slot, order)
            notes.append(f"{key}: orden {order.side} ejecutada ({order.filled_qty:.6g} a "
                         f"{order.filled_avg_price or 0:,.2f}).")  # fmt: skip
        elif order.status in _DEAD:
            slot.open_order_id = slot.open_side = None
            notes.append(f"{key}: la orden terminó sin ejecutarse ({order.status}).")
    return notes


# -- one run --------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunReport:
    lines: list[str]
    sent: int


def run(broker: Broker, fetch: Callable[[str, Interval], pd.DataFrame], start: datetime,
        ledger_path: Path, send: bool, now: datetime | None = None) -> RunReport:  # fmt: skip
    lines: list[str] = []
    account = broker.account()
    if account.status.upper() != "ACTIVE":
        return RunReport([f"La cuenta de Alpaca no está activa ({account.status})."], 0)
    ledger = load_ledger(ledger_path)
    lines += reconcile_open_orders(broker, ledger)

    held = {p.symbol.replace("/", "").upper(): p.qty for p in broker.positions()}

    def account_qty(symbol: str) -> float:
        return held.get(to_alpaca_symbol(symbol)[0].replace("/", ""), 0.0)

    market_open = broker.market_open()
    tradable: dict[str, bool] = {}

    def blocked(symbol: str) -> str | None:
        if symbol not in tradable:
            tradable[symbol] = broker.is_tradable(symbol)
        if not tradable[symbol]:
            return "Alpaca no permite operar este activo en la cuenta paper"
        if not to_alpaca_symbol(symbol)[1] and not market_open:
            return "bolsa cerrada: la orden espera a la próxima apertura"
        return None

    results = run_all(fetch, start, now)
    deferred: list[str] = []
    actions = plan(results, ledger, account_qty, blocked, deferred)
    lines += [f"[en espera] {d}" for d in deferred]
    sent = 0
    for action in actions:
        o = action.order
        what = (f"{o.side} {o.symbol} por {o.notional:,.2f} USD" if o.notional is not None
                else f"{o.side} {o.symbol} x {o.qty:.6g}")  # fmt: skip
        if not send:
            lines.append(f"[simulacro] {action.key}: {what} — {action.reason}")
            continue
        try:
            placed = broker.place_order(o)
        except AppError as exc:
            lines.append(f"{action.key}: NO enviada ({exc.user_message})")
            continue
        slot = ledger[action.key]
        slot.open_order_id, slot.open_side = placed.id, o.side
        if placed.status in _DONE:
            apply_fill(slot, placed)
        save_ledger(ledger_path, ledger)  # right away: never lose track of a sent order
        sent += 1
        lines.append(f"{action.key}: enviada {what} ({placed.status}) — {action.reason}")
    if not actions and not deferred:
        lines.append("Sin órdenes nuevas: cada perfil ya tiene lo que su estrategia pide.")
    if send:
        save_ledger(ledger_path, ledger)
    return RunReport(lines, sent)


def holdings_report(ledger: dict[str, Slot]) -> list[str]:
    rows = [f"- {k}: {s.qty:.6g} en cartera, {s.cash:,.2f} USD en efectivo"
            + (f", orden pendiente ({s.open_side})" if s.open_order_id else "")
            for k, s in sorted(ledger.items())]  # fmt: skip
    return rows or ["(todavía no se ha enviado ninguna orden)"]
