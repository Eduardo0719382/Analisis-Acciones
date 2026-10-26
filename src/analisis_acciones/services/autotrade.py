"""Sends the orders of the 12 strategy profiles to Alpaca's PAPER account (simulated money).

Every profile starts with ``BUDGET`` dollars in its own cash pool and decides, from the
signals of its strategy on each asset, where to put it. A small local ledger remembers
what each profile holds, because Alpaca only knows the account's total per symbol. Each
run reconciles the ledger with what the profile's strategy wants *now*:

* assets the strategy wants and the profile does not hold -> market buys by dollar amount,
  sharing the pool among them, with a cap per asset that depends on the style (aggressive
  50 % of the budget, balanced 34 %, conservative 25 %), so a profile concentrates more or
  less in the assets that are signalling and keeps the rest in cash;
* assets the profile holds and the strategy no longer wants -> market sell of the quantity
  the profile holds (the proceeds go back to its pool);
* anything else -> nothing.

So a run that is missed or repeated never duplicates an order, and the order ids are
deterministic (profile, symbol, side, bar) so Alpaca itself rejects a second copy. Long
only: it never sells what the profile does not hold. ``send=False`` (the default) only shows
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
from analisis_acciones.strategies.profiles import PROFILE_BY_ID

MIN_ORDER_USD = 1.0
#: Largest part of the budget a profile puts in one asset, by style.
MAX_WEIGHT = {"aggressive": 0.5, "balanced": 0.34, "conservative": 0.25}
CASH = "CASH"
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
    """A profile's cash pool (key ``<profile>|CASH``) or its holding of one asset."""

    cash: float = 0.0  # pool only
    qty: float = 0.0
    open_order_id: str | None = None  # an order sent and not yet seen as filled
    open_side: str | None = None
    reserved: float = 0.0  # dollars taken from the pool by a buy that is still open
    cost: float = 0.0  # dollars paid for ``qty``


@dataclass(frozen=True)
class Action:
    key: str  # "<profile id>|<symbol>"
    order: OrderRequest
    reason: str


def slot_key(profile_id: str, symbol: str) -> str:
    return f"{profile_id}|{symbol}"


def cash_key(profile_id: str) -> str:
    return slot_key(profile_id, CASH)


def pool_of(ledger: dict[str, Slot], key: str) -> Slot:
    return ledger.setdefault(cash_key(key.split("|")[0]), Slot(cash=BUDGET))


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
    """Orders that bring every profile to what its strategy wants. Pure: nothing is sent.

    ``blocked(symbol)`` gives the reason an order for that symbol cannot be sent now (stock
    exchange closed, asset not tradable); those orders are left out and, with ``deferred``,
    listed as "<slot>: <reason>".
    """
    actions: list[Action] = []
    for result in results:
        profile = result.profile
        pool = ledger.setdefault(cash_key(profile.id), Slot(cash=BUDGET))
        entries: list[tuple[str, str, str]] = []  # (key, symbol, order id prefix)
        for sleeve in result.sleeves:
            symbol = sleeve.sleeve.symbol
            key = slot_key(profile.id, symbol)
            slot = ledger.setdefault(key, Slot())
            if slot.open_order_id:
                continue  # wait for the previous order to finish
            held, want = slot.qty > 0, wants_position(sleeve)
            if held == want:
                continue
            reason = blocked(symbol)
            if reason:
                if deferred is not None:
                    deferred.append(f"{key}: {reason}")
                continue
            tag = f"aa-{profile.id}-{bar_tag(sleeve.last_bar)}-{bar_tag(symbol)}"
            if want:
                entries.append((key, symbol, tag))
            else:
                qty = min(slot.qty, account_qty(symbol))
                if qty > 0:
                    order = OrderRequest(symbol, "sell", qty, client_order_id=f"{tag}-sell")
                    actions.append(Action(key, order, "la estrategia pide salir"))
        if entries and pool.cash >= MIN_ORDER_USD:
            each = min(pool.cash / len(entries), MAX_WEIGHT[profile.style] * BUDGET)
            if each >= MIN_ORDER_USD:
                for key, symbol, tag in entries:
                    order = OrderRequest(symbol, "buy", 0, notional=round(each - 0.005, 2),
                                         client_order_id=f"{tag}-buy")  # fmt: skip
                    actions.append(Action(key, order, "la estrategia pide estar comprado"))
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


def apply_fill(slot: Slot, pool: Slot, order: BrokerOrder) -> None:
    price = order.filled_avg_price or 0.0
    value = order.filled_qty * price
    if order.side == "buy":
        slot.qty += order.filled_qty
        slot.cost += value
        pool.cash += slot.reserved - value  # the reservation becomes the real cost
        slot.reserved = 0.0
    else:
        before = slot.qty
        slot.qty = max(0.0, slot.qty - order.filled_qty)
        slot.cost = slot.cost * slot.qty / before if before > 0 else 0.0
        pool.cash += value
    if slot.qty < 1e-9:
        slot.qty = slot.cost = 0.0
    slot.open_order_id = slot.open_side = None


def reconcile_open_orders(broker: Broker, ledger: dict[str, Slot]) -> list[str]:
    """Close the slots whose last order has finished; returns lines to show."""
    notes = []
    for key, slot in list(ledger.items()):
        if not slot.open_order_id:
            continue
        order = broker.get_order(slot.open_order_id)
        if order.status in _DONE:
            apply_fill(slot, pool_of(ledger, key), order)
            notes.append(f"{key}: orden {order.side} ejecutada ({order.filled_qty:.6g} a "
                         f"{order.filled_avg_price or 0:,.2f}).")  # fmt: skip
        elif order.status in _DEAD:
            pool_of(ledger, key).cash += slot.reserved
            slot.reserved = 0.0
            slot.open_order_id = slot.open_side = None
            notes.append(f"{key}: la orden terminó sin ejecutarse ({order.status}).")
    return notes


# -- one run --------------------------------------------------------------------------------


@dataclass(frozen=True)
class RunReport:
    lines: list[str]
    sent: int
    positions: list[BrokerPosition]


def run(broker: Broker, fetch: Callable[[str, Interval], pd.DataFrame], start: datetime,
        ledger_path: Path, send: bool, now: datetime | None = None) -> RunReport:  # fmt: skip
    lines: list[str] = []
    account = broker.account()
    if account.status.upper() != "ACTIVE":
        return RunReport([f"La cuenta de Alpaca no está activa ({account.status})."], 0, [])
    ledger = load_ledger(ledger_path)
    lines += reconcile_open_orders(broker, ledger)

    positions = broker.positions()
    held = {p.symbol.replace("/", "").upper(): p.qty for p in positions}

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
        slot, pool = ledger[action.key], pool_of(ledger, action.key)
        slot.open_order_id, slot.open_side = placed.id, o.side
        if o.notional is not None:
            slot.reserved = o.notional
            pool.cash -= o.notional
        if placed.status in _DONE:
            apply_fill(slot, pool, placed)
        save_ledger(ledger_path, ledger)  # right away: never lose track of a sent order
        sent += 1
        lines.append(f"{action.key}: enviada {what} ({placed.status}) — {action.reason}")
    if not actions and not deferred:
        lines.append("Sin órdenes nuevas: cada perfil ya tiene lo que su estrategia pide.")
    if send:
        save_ledger(ledger_path, ledger)
        positions = broker.positions()
    return RunReport(lines, sent, positions)


# -- valuation and Markdown -----------------------------------------------------------------


@dataclass(frozen=True)
class ProfileValue:
    name: str
    cash: float
    holdings: tuple[tuple[str, float, float], ...]  # (symbol, qty, value in USD)

    @property
    def value(self) -> float:
        return self.cash + sum(v for _s, _q, v in self.holdings)

    @property
    def return_pct(self) -> float:
        return (self.value / BUDGET - 1) * 100


def valuation(ledger: dict[str, Slot], positions: list[BrokerPosition]) -> list[ProfileValue]:
    """Value of every profile: its cash plus each holding at the account's market price.

    The price comes from the account's position in that symbol; with none (not yet filled or
    not reported) the holding is valued at what it cost.
    """
    prices = {p.symbol.replace("/", "").upper(): p.market_value / p.qty
              for p in positions if p.qty > 0}  # fmt: skip
    out = []
    for profile_id, profile in PROFILE_BY_ID.items():
        pool = ledger.get(cash_key(profile_id), Slot(cash=BUDGET))
        reserved = sum(s.reserved for k, s in ledger.items() if k.startswith(profile_id + "|"))
        holdings = []
        for key, slot in sorted(ledger.items()):
            profile_part, _sep, symbol = key.partition("|")
            if profile_part != profile_id or symbol == CASH or slot.qty <= 0:
                continue
            price = prices.get(to_alpaca_symbol(symbol)[0].replace("/", ""))
            holdings.append((symbol, slot.qty, slot.qty * price if price else slot.cost))
        out.append(ProfileValue(profile.name, pool.cash + reserved, tuple(holdings)))
    return out


def render_state_md(values: list[ProfileValue], now: datetime) -> str:
    lines = [
        f"# Perfiles en Alpaca paper — estado a {now:%Y-%m-%d %H:%M} UTC",
        f"Cada perfil empezó con {BUDGET:,.0f} USD ficticios y reparte su dinero según las "
        "señales de su estrategia (límite por activo según el estilo). Solo compras y "
        "ventas de lo comprado.",
        "",
        "| Perfil | Efectivo | Posiciones (valor en USD) | Valor total | Resultado |",
        "|---|---:|---|---:|---:|",
    ]
    for v in values:
        held = ", ".join(f"{s} {val:,.2f}" for s, _q, val in v.holdings) or "—"
        lines.append(f"| {v.name} | {v.cash:,.2f} | {held} | {v.value:,.2f} | "
                     f"{v.return_pct:+.1f} % |")  # fmt: skip
    total = sum(v.value for v in values)
    lines += [
        "",
        f"Conjunto: {total:,.2f} de {BUDGET * len(values):,.0f} USD "
        f"({(total / (BUDGET * len(values)) - 1) * 100:+.1f} %).",
        "Simulación con dinero ficticio: no garantiza resultados reales ni es asesoramiento "
        "financiero.",
    ]
    return "\n".join(lines)


def holdings_report(ledger: dict[str, Slot]) -> list[str]:
    rows = [
        f"- {k}: {s.qty:.6g} en cartera"
        + (f", orden pendiente ({s.open_side})" if s.open_order_id else "")
        for k, s in sorted(ledger.items())
        if not k.endswith("|" + CASH) and (s.qty > 0 or s.open_order_id)
    ]
    return rows or ["(todavía no hay posiciones)"]
