"""Turns an agent's decision into paper orders, within the profile's hard limits.

The agent proposes; this module disposes. Everything that protects the experiment is
here, not in the prompt:

* only the Alpaca PAPER account (fixed URL, and an account number starting with "PA",
  checked before every order);
* a profile spends only its free virtual cash and sells only what its own book holds
  (capped by what the account really holds);
* stocks only while Alpaca's clock says the exchange is open: nothing is queued blind;
* % per asset, trades per day, minimum order, and a buy must expect to move more than
  its round-trip cost (fees + spread);
* positions past their loss limit are sold by the executor itself; a profile past its
  total loss limit can only sell.

Every call leaves a decision row (even "nothing", "not due" or "market closed").
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from analisis_acciones.broker.alpaca import (
    PAPER_URL,
    AccountInfo,
    BrokerOrder,
    BrokerPosition,
    OrderRequest,
    to_alpaca_symbol,
)
from analisis_acciones.lab import costs
from analisis_acciones.lab.book import DUST, Book, build_book
from analisis_acciones.lab.profiles import MIN_GAP_H, LabProfile
from analisis_acciones.lab.store import OPEN_STATES, Store, now_iso
from analisis_acciones.models.errors import AppError

ET = ZoneInfo("America/New_York")
EXPECTED_PAPER_URL = "https://paper-api.alpaca.markets"
#: A buy must expect at least this multiple of its round-trip cost.
COST_MARGIN = 1.5
#: Alpaca refuses crypto buys below this cost (HTTP 403 "minimal amount of order 10", seen on
#: the paper account on 2026-10-26); sells below it are accepted.
MIN_CRYPTO_BUY_USD = 10.0
_FILLED = {"filled"}
_DEAD = {"canceled", "expired", "rejected", "done_for_day", "replaced", "stopped", "suspended"}
#: Decisions that do not use up a profile's turn.
NOT_A_TURN = ("no_toca", "sin_accion", "error", "simulacro")


class LabAbort(Exception):
    """Stop everything: the account is not the paper one, or the books do not add up."""


class Broker(Protocol):
    def account(self) -> AccountInfo: ...
    def positions(self) -> list[BrokerPosition]: ...
    def place_order(self, order: OrderRequest) -> BrokerOrder: ...
    def get_order(self, order_id: str) -> BrokerOrder: ...
    def order_by_client_id(self, client_order_id: str) -> BrokerOrder | None: ...
    def clock(self) -> dict[str, Any]: ...
    def asset(self, symbol: str) -> dict[str, Any] | None: ...


def ensure_paper(broker: Broker) -> AccountInfo:
    """Raise LabAbort unless this is an active Alpaca paper account."""
    if PAPER_URL != EXPECTED_PAPER_URL:
        raise LabAbort(f"El cliente no apunta a la cuenta paper ({PAPER_URL}).")
    account = broker.account()
    if not account.account_number.upper().startswith("PA"):
        raise LabAbort("La cuenta de Alpaca no es de práctica (paper): no se envía nada.")
    if account.status.upper() != "ACTIVE":
        raise LabAbort(f"La cuenta paper no está activa ({account.status}).")
    return account


# -- fills and reconciliation ---------------------------------------------------------------


def fees_for_fill(
    symbol: str, side: str, qty: float, price: float, day: date
) -> tuple[float, float]:
    """(fee in coin, fee in USD) the book charges for a fill."""
    if to_alpaca_symbol(symbol)[1]:
        return costs.crypto_fee(side, qty, price)
    return 0.0, costs.stock_fees(side, qty, price, day)


def _fill_day(filled_at: str) -> date:
    try:
        return datetime.fromisoformat(filled_at.replace("Z", "+00:00")).date()
    except ValueError:
        return datetime.now(UTC).date()


def record_broker_order(store: Store, client_order_id: str, symbol: str, side: str,
                        order: BrokerOrder) -> str:  # fmt: skip
    """Copy Alpaca's view of an order into the store; returns the stored status."""
    status = order.status.lower()
    if status in _FILLED:
        stored = "filled"
    elif status in _DEAD:
        stored = "dead"
    elif status == "partially_filled":
        stored = "partial"
    else:
        stored = "open"
    fields: dict[str, Any] = {"status": stored, "alpaca_id": order.id}
    if order.filled_qty > DUST and order.filled_avg_price:
        fee_coin, fee_usd = fees_for_fill(symbol, side, order.filled_qty, order.filled_avg_price,
                                          _fill_day(order.filled_at))  # fmt: skip
        fields |= {"filled_qty": order.filled_qty, "filled_price": order.filled_avg_price,
                   "filled_at": order.filled_at or now_iso(), "fee_coin": fee_coin,
                   "fee_usd": fee_usd}  # fmt: skip
    store.update_order(client_order_id, **fields)
    return stored


def reconcile(broker: Broker, store: Store, now: datetime | None = None) -> list[str]:
    """Bring every unfinished order up to date with Alpaca. Run before any decision.

    An order left as "sending" (the run died between saving it and hearing back) is looked
    up by its client_order_id: found, it is followed like any other; not found two minutes
    later, it never reached Alpaca.
    """
    now = now or datetime.now(UTC)
    notes = []
    for row in store.orders(states=OPEN_STATES):
        cid, symbol, side = str(row["client_order_id"]), str(row["symbol"]), str(row["side"])
        try:
            order = (broker.get_order(row["alpaca_id"]) if row["alpaca_id"]
                     else broker.order_by_client_id(cid))  # fmt: skip
        except AppError as exc:
            notes.append(f"{cid}: no se pudo consultar ({exc.user_message})")
            continue
        if order is None:
            created = datetime.fromisoformat(str(row["created_at"]))
            if now - created > timedelta(minutes=2):
                store.update_order(cid, status="not_sent")
                notes.append(f"{cid}: nunca llegó a Alpaca; se libera lo reservado.")
            continue
        before = str(row["status"])
        after = record_broker_order(store, cid, symbol, side, order)
        if after != before:
            notes.append(f"{cid}: {before} → {after} ({order.filled_qty:.9g} a "
                         f"{order.filled_avg_price or 0:,.6g}).")  # fmt: skip
    for note in notes:
        store.add_note("reconcile", note)
    return notes


def account_quantities(positions: list[BrokerPosition], known: set[str]) -> dict[str, float]:
    """App symbol -> quantity the account holds. Alpaca names crypto positions BTCUSD."""
    by_compact = {s.replace("-", ""): s for s in known}
    out = {}
    for p in positions:
        compact = p.symbol.upper().replace("/", "")
        out[by_compact.get(compact, compact)] = p.qty
    return out


def invariant_issues(books: Mapping[str, Book], account_qty: Mapping[str, float]) -> list[str]:
    """Symbols whose books add up to more than the account holds (they must never)."""
    totals: dict[str, float] = {}
    for book in books.values():
        for sym, pos in book.positions.items():
            totals[sym] = totals.get(sym, 0.0) + pos.qty
    issues = []
    for sym, total in sorted(totals.items()):
        held = account_qty.get(sym, 0.0)
        if total > held * (1 + 1e-6) + 1e-8:
            issues.append(f"{sym}: los libros suman {total:.9g} y la cuenta tiene {held:.9g}.")
    return issues


# -- when a profile decides ------------------------------------------------------------------


def _counted(store: Store, profile_id: str) -> list[datetime]:
    return [datetime.fromisoformat(str(r["at"])) for r in store.decisions(profile_id, limit=50)
            if r["kind"] not in NOT_A_TURN]  # fmt: skip


def is_due(profile: LabProfile, store: Store, now: datetime) -> tuple[bool, str]:
    """Whether the profile's turn has come (its frequency since its last real decision)."""
    past = _counted(store, profile.id)
    if not past:
        return True, "primera decisión"
    last = max(past)
    if profile.frecuencia in MIN_GAP_H:
        gap = (now - last).total_seconds() / 3600
        ok = gap >= MIN_GAP_H[profile.frecuencia]
        return ok, f"última decisión hace {gap:.1f} h"
    a, b = last.astimezone(ET), now.astimezone(ET)
    if profile.frecuencia == "diaria":
        same = a.date() == b.date()
    elif profile.frecuencia == "semanal":
        same = a.isocalendar()[:2] == b.isocalendar()[:2]
    else:
        same = (a.year, a.month) == (b.year, b.month)
    return not same, f"última decisión {a:%Y-%m-%d %H:%M} ET"


# -- validation ------------------------------------------------------------------------------


@dataclass(frozen=True)
class Planned:
    symbol: str
    side: str
    notional: float | None
    qty: float | None
    reason: str
    forced: bool = False
    expected_pct: float | None = None
    cost_pct: float | None = None


@dataclass
class Plan:
    orders: list[Planned] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Market:
    """What the executor knows about the market right now."""

    stock_open: bool
    prices: Mapping[str, float]
    quotes: Mapping[str, tuple[float | None, float | None]]
    assets: Mapping[str, Mapping[str, Any] | None]
    account_qty: Mapping[str, float]
    day: date


def _floor(value: float, decimals: int) -> float:
    factor: float = 10.0**decimals
    return float(math.floor(value * factor + 1e-9)) / factor


def _tradable(symbol: str, market: Market) -> str | None:
    asset = market.assets.get(symbol)
    crypto = to_alpaca_symbol(symbol)[1]
    if not asset or asset.get("status") != "active" or asset.get("tradable") is not True:
        return "Alpaca no lo lista como activo y operable"
    if not crypto and asset.get("fractionable") is not True:
        return "Alpaca no permite fracciones de esta acción"
    if not crypto and not market.stock_open:
        return "mercado de acciones cerrado: no se encolan órdenes"
    if symbol not in market.prices:
        return "sin precio actual"
    return None


def forced_stops(profile: LabProfile, book: Book, market: Market) -> Plan:
    plan = Plan()
    for sym, pos in sorted(book.positions.items()):
        price = market.prices.get(sym)
        if not price or pos.free_qty <= DUST or pos.cost <= 0:
            continue
        loss = (pos.qty * price / pos.cost - 1) * 100
        if loss > -profile.limites.stop_posicion_pct:
            continue
        why = _tradable(sym, market)
        if why:
            plan.notes.append(f"{sym}: alcanzó el límite de pérdida ({loss:.1f} %) pero no se "
                              f"puede vender ahora ({why}).")  # fmt: skip
            continue
        qty = _floor(min(pos.free_qty, market.account_qty.get(sym, 0.0)), 9)
        if qty > DUST:
            limit = profile.limites.stop_posicion_pct
            why_sold = f"venta forzada: pérdida de {loss:.1f} % ≥ límite de {limit:g} %"
            plan.orders.append(Planned(sym, "sell", None, qty, why_sold, forced=True))
    return plan


def validate(profile: LabProfile, book: Book, decision: Mapping[str, Any], market: Market,
             trades_today: int,
             skip_symbols: set[str] | frozenset[str] = frozenset()) -> Plan:  # fmt: skip
    """The orders of ``decision`` that respect every hard limit; the rest, with the reason."""
    plan = Plan()
    lim = profile.limites
    equity = book.value(market.prices)
    lost = (1 - equity / book.capital) * 100 if book.capital else 0.0
    blocked_buys = None
    if profile.estado != "activo":
        blocked_buys = f"perfil {profile.estado}: solo puede vender"
    elif lost >= lim.stop_perfil_pct:
        blocked_buys = (
            f"el perfil perdió {lost:.1f} % (límite {lim.stop_perfil_pct:g} %): solo vende"
        )
    cash_left = book.free_cash
    seen: set[str] = set()
    count = trades_today
    raw_orders = decision.get("ordenes") or []
    if not isinstance(raw_orders, list):
        plan.refused.append("'ordenes' debe ser una lista")
        return plan
    for raw in raw_orders:
        if not isinstance(raw, dict):
            plan.refused.append("orden con formato no válido")
            continue
        sym = str(raw.get("simbolo", "")).strip().upper()
        side = {"comprar": "buy", "vender": "sell", "buy": "buy", "sell": "sell"}.get(
            str(raw.get("lado", "")).lower()
        )
        why = str(raw.get("motivo", "")).strip()[:300]
        label = f"{side or '?'} {sym or '?'}"
        if side is None or sym not in profile.universo:
            plan.refused.append(f"{label}: fuera del universo del perfil o lado no válido")
            continue
        if sym in seen or sym in skip_symbols:
            plan.refused.append(f"{label}: ya hay otra orden para este activo en esta ejecución")
            continue
        if count >= lim.max_operaciones_dia:
            plan.refused.append(f"{label}: límite de {lim.max_operaciones_dia} operaciones por día")
            continue
        reason = _tradable(sym, market)
        if reason:
            plan.refused.append(f"{label}: {reason}")
            continue
        price = market.prices[sym]
        bid, ask = market.quotes.get(sym, (None, None))
        crypto = to_alpaca_symbol(sym)[1]
        pos = book.positions.get(sym)
        if side == "buy":
            if blocked_buys:
                plan.refused.append(f"{label}: {blocked_buys}")
                continue
            try:
                usd = _floor(float(raw.get("usd", 0)), 2)
                expected = float(raw.get("objetivo_pct", 0))
            except (TypeError, ValueError):
                plan.refused.append(f"{label}: 'usd' y 'objetivo_pct' deben ser números")
                continue
            min_size = float((market.assets.get(sym) or {}).get("min_order_size") or 0)
            minimum = max(lim.min_orden_usd, min_size * price * 1.05,
                          MIN_CRYPTO_BUY_USD if crypto else 0.0)  # fmt: skip
            held_value = pos.qty * price if pos else 0.0
            cap = lim.max_pct_activo / 100 * equity - held_value
            spread, _measured = costs.effective_spread(crypto, bid, ask)
            cost = costs.round_trip_cost_pct(crypto, price, spread, market.day)
            if usd < minimum:
                plan.refused.append(
                    f"{label}: {usd:.2f} USD es menos que el mínimo ({minimum:.2f})"
                )
            elif usd > cash_left + 1e-9:
                plan.refused.append(f"{label}: {usd:.2f} USD supera el efectivo libre "
                                    f"({cash_left:.2f})")  # fmt: skip
            elif usd > cap + 0.01:
                plan.refused.append(f"{label}: superaría el {lim.max_pct_activo:g} % del perfil en "
                                    f"un activo (cabe {max(cap, 0):.2f} USD)")  # fmt: skip
            elif expected < COST_MARGIN * cost:
                plan.refused.append(
                    f"{label}: objetivo {expected:.2f} % no compensa el coste "
                    f"de ida y vuelta ({cost:.2f} % × {COST_MARGIN:g})"
                )
            else:
                plan.orders.append(Planned(sym, "buy", usd, None, why, expected_pct=expected,
                                           cost_pct=round(cost, 3)))  # fmt: skip
                cash_left -= usd
                count += 1
                seen.add(sym)
            continue
        free = pos.free_qty if pos else 0.0
        if free <= DUST:
            plan.refused.append(f"{label}: el perfil no tiene este activo (solo vende lo propio)")
            continue
        try:
            if "cantidad" in raw:
                qty = min(float(raw["cantidad"]), free)
            else:
                qty = free * min(max(float(raw.get("fraccion", 1.0)), 0.0), 1.0)
        except (TypeError, ValueError):
            plan.refused.append(f"{label}: 'cantidad' o 'fraccion' no válidas")
            continue
        if qty >= free * 0.999:
            qty = free  # all of it: no dust left behind
        account = market.account_qty.get(sym, 0.0)
        if qty > account:
            plan.notes.append(f"{sym}: la cuenta tiene {account:.9g}, menos que el libro; se "
                              "vende lo que hay.")  # fmt: skip
        qty = _floor(min(qty, account), 9)
        if qty <= DUST or qty * price < 1.0:
            plan.refused.append(f"{label}: cantidad demasiado pequeña ({qty:.9g})")
            continue
        plan.orders.append(Planned(sym, "sell", None, qty, why))
        count += 1
        seen.add(sym)
    return plan


# -- sending ---------------------------------------------------------------------------------


def client_order_id(profile_id: str, now: datetime, symbol: str, side: str, n: int) -> str:
    sym = to_alpaca_symbol(symbol)[0].replace("/", "")
    return f"{profile_id}-{now:%y%m%d%H%M}-{sym}-{side[0].upper()}{n}"


def send_orders(broker: Broker, store: Store, profile: LabProfile, orders: list[Planned],
                market: Market, now: datetime, decision_id: int,
                wait: Callable[[float], None] = time.sleep) -> list[dict[str, Any]]:  # fmt: skip
    """Send ``orders``; each one is saved before it leaves and followed until it settles."""
    results: list[dict[str, Any]] = []
    for n, p in enumerate(orders, start=1):
        cid = client_order_id(profile.id, now, p.symbol, p.side, n)
        bid, ask = market.quotes.get(p.symbol, (None, None))
        try:
            ensure_paper(broker)  # before every order, not once per run
        except LabAbort as exc:
            results.append({"orden": cid, "estado": "abortada", "detalle": str(exc)})
            break
        store.add_order(client_order_id=cid, profile=profile.id, symbol=p.symbol, side=p.side,
                        notional=p.notional, qty=p.qty, bid=bid, ask=ask, forced=p.forced,
                        reason=p.reason, decision_id=decision_id)  # fmt: skip
        request = OrderRequest(p.symbol, p.side, p.qty or 0.0, notional=p.notional,
                               client_order_id=cid)  # fmt: skip
        try:
            placed = broker.place_order(request)
        except AppError as exc:
            # The request may or may not have reached Alpaca: the next reconcile looks it up.
            results.append({"orden": cid, "estado": "desconocido", "detalle": exc.user_message})
            continue
        status = record_broker_order(store, cid, p.symbol, p.side, placed)
        for delay in (0.5, 1.0, 2.0, 3.0):
            if status not in OPEN_STATES:
                break
            wait(delay)
            try:
                status = record_broker_order(store, cid, p.symbol, p.side,
                                             broker.get_order(placed.id))  # fmt: skip
            except AppError:
                break
        row = next(r for r in store.orders(profile.id) if r["client_order_id"] == cid)
        results.append(
            {
                "orden": cid,
                "simbolo": p.symbol,
                "lado": p.side,
                "estado": status,
                "usd_pedidos": p.notional,
                "cantidad_pedida": p.qty,
                "cantidad_ejecutada": row["filled_qty"],
                "precio_ejecucion": row["filled_price"],
                "comision_moneda": row["fee_coin"],
                "comision_usd": row["fee_usd"],
                "bid": bid,
                "ask": ask,
                "forzada": p.forced,
                "motivo": p.reason,
            }
        )
    return results


def trades_today(store: Store, profile_id: str, now: datetime) -> int:
    start = datetime(now.year, now.month, now.day, tzinfo=UTC).isoformat(timespec="seconds")
    return sum(1 for r in store.orders(profile_id, since=start)
               if not r["forced"] and r["status"] not in ("not_sent",))  # fmt: skip


def books_for(store: Store, profiles: Mapping[str, LabProfile]) -> dict[str, Book]:
    orders = store.orders()
    out = {}
    for pid, profile in profiles.items():
        start = store.profile_start(pid)
        capital = start[1] if start else profile.capital
        out[pid] = build_book(pid, capital, orders)
    return out
