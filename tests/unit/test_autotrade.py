"""Automatic paper orders: ledger-driven, idempotent, long-only, dry run by default."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from analisis_acciones.broker.alpaca import (
    AccountInfo,
    BrokerOrder,
    BrokerPosition,
    OrderRequest,
    validate_order,
)
from analisis_acciones.models.errors import UserError
from analisis_acciones.services import autotrade
from analisis_acciones.services.autotrade import (
    Slot,
    load_ledger,
    plan,
    run,
    save_ledger,
    slot_key,
    wants_position,
)
from analisis_acciones.services.forward_test import (
    SLEEVES,
    ProfileResult,
    SleeveResult,
)
from analisis_acciones.strategies.profiles import PROFILES

NOW = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)
P = PROFILES[3]  # days_aggressive
BTC = next(i for i, s in enumerate(SLEEVES) if s.symbol == "BTC-USD")


def sleeve(i: int, pending: str | None = None, held: bool = False) -> SleeveResult:
    return SleeveResult(SLEEVES[i], 50.0, 50.0, 0, "x" if held else None, pending, None,
                        "2026-10-26 00:00")  # fmt: skip


def results(*sleeves: SleeveResult) -> list[ProfileResult]:
    return [ProfileResult(P, tuple(sleeves))]


def test_wants_position() -> None:
    assert wants_position(sleeve(0, "buy"))
    assert not wants_position(sleeve(0, "sell", held=True))
    assert wants_position(sleeve(0, None, held=True))
    assert not wants_position(sleeve(0))


def test_plan_buys_with_the_slot_cash_and_a_unique_id() -> None:
    ledger: dict[str, Slot] = {}
    (a,) = plan(results(sleeve(0, "buy")), ledger, lambda _s: 0.0)
    assert a.order.side == "buy" and a.order.notional == 49.99
    assert a.order.client_order_id and a.order.client_order_id.endswith("-buy")
    validate_order(a.order)
    assert (
        plan(results(sleeve(0, "buy")), ledger, lambda _s: 0.0)[0].order.client_order_id
        == a.order.client_order_id
    )  # same decision, same id


def test_plan_does_nothing_when_already_in_line() -> None:
    key = slot_key(P.id, "QQQ")
    ledger = {key: Slot(cash=0.0, qty=0.1)}
    assert plan(results(sleeve(0, None, held=True)), ledger, lambda _s: 5) == []
    assert plan(results(sleeve(0)), {key: Slot(cash=50)}, lambda _s: 0) == []


def test_plan_sells_only_what_the_slot_holds_and_the_account_has() -> None:
    key = slot_key(P.id, "BTC-USD")
    ledger = {key: Slot(cash=0.0, qty=0.5)}
    (a,) = plan(results(sleeve(BTC, "sell", held=True)), ledger, lambda _s: 0.2)
    assert a.order.side == "sell" and a.order.qty == 0.2
    assert plan(results(sleeve(BTC, "sell", held=True)), ledger, lambda _s: 0.0) == []
    # a slot that holds nothing never sells (no short selling)
    assert plan(results(sleeve(BTC, "sell")), {key: Slot(cash=50)}, lambda _s: 9) == []


def test_slot_with_an_open_order_waits() -> None:
    key = slot_key(P.id, "QQQ")
    ledger = {key: Slot(cash=50, open_order_id="a1b2c3d4-0001", open_side="buy")}
    assert plan(results(sleeve(0, "buy")), ledger, lambda _s: 0) == []


def test_notional_orders_are_buys_at_market_only() -> None:
    for bad in (OrderRequest("QQQ", "sell", 0, notional=10),
                OrderRequest("QQQ", "buy", 0, "limit", 10, notional=10),
                OrderRequest("QQQ", "buy", 0, notional=0.5),
                OrderRequest("QQQ", "buy", 1, client_order_id="bad id!")):  # fmt: skip
        with pytest.raises(UserError):
            validate_order(bad)


class FakeBroker:
    def __init__(self, status: str = "ACTIVE", fill: bool = True) -> None:
        self.status, self.fill = status, fill
        self.open = True
        self.untradable: set[str] = set()
        self.sent: list[OrderRequest] = []
        self.orders: dict[str, BrokerOrder] = {}
        self.held: dict[str, float] = {}

    def account(self) -> AccountInfo:
        return AccountInfo(self.status, 100000, 100000, 100000)

    def positions(self) -> list[BrokerPosition]:
        return [BrokerPosition(s, q, 1, 1, 0) for s, q in self.held.items()]

    def place_order(self, order: OrderRequest) -> BrokerOrder:
        self.sent.append(order)
        price = 100.0
        qty = (order.notional or 0) / price if order.side == "buy" else order.qty
        oid = f"a1b2c3d4-{len(self.sent):04d}"
        placed = BrokerOrder(oid, order.symbol, order.side, "market", qty, None,
                             "filled" if self.fill else "accepted", price if self.fill else None,
                             qty if self.fill else 0.0)  # fmt: skip
        self.orders[oid] = placed
        return placed

    def market_open(self) -> bool:
        return self.open

    def is_tradable(self, symbol: str) -> bool:
        return symbol not in self.untradable

    def get_order(self, order_id: str) -> BrokerOrder:
        o = self.orders[order_id]
        return BrokerOrder(o.id, o.symbol, o.side, o.type, o.qty, None, "filled", 100.0, o.qty)


def patch_results(monkeypatch: pytest.MonkeyPatch, pending: list[str | None]) -> None:
    state = {"i": 0}

    def fake_run_all(*_a: Any, **_k: Any) -> list[ProfileResult]:
        p = pending[min(state["i"], len(pending) - 1)]
        state["i"] += 1
        return results(sleeve(0, p, held=p is None), sleeve(BTC))

    monkeypatch.setattr(autotrade, "run_all", fake_run_all)


def fetch(*_a: Any) -> Any:
    return None


def test_dry_run_sends_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    patch_results(monkeypatch, ["buy"])
    broker = FakeBroker()
    report = run(broker, fetch, NOW, tmp_path / "l.json", send=False, now=NOW)
    assert broker.sent == [] and report.sent == 0
    assert report.lines[0].startswith("[simulacro]")
    assert not (tmp_path / "l.json").exists()


def test_send_buys_once_then_sells_and_never_repeats(monkeypatch: pytest.MonkeyPatch,
                                                     tmp_path: Path) -> None:  # fmt: skip
    path = tmp_path / "l.json"
    broker = FakeBroker()
    patch_results(monkeypatch, ["buy", None, None, "sell", "sell"])
    assert run(broker, fetch, NOW, path, send=True, now=NOW).sent == 1  # buys 50 of QQQ
    ledger = load_ledger(path)
    slot = ledger[slot_key(P.id, "QQQ")]
    assert slot.qty == pytest.approx(0.4999) and slot.cash < 0.02 and slot.open_order_id is None
    assert run(broker, fetch, NOW, path, send=True, now=NOW).sent == 0  # still in line
    assert run(broker, fetch, NOW, path, send=True, now=NOW).sent == 0
    broker.held = {"QQQ": 0.4999}
    assert run(broker, fetch, NOW, path, send=True, now=NOW).sent == 1  # strategy says sell
    slot = load_ledger(path)[slot_key(P.id, "QQQ")]
    assert slot.qty == 0 and slot.cash == pytest.approx(49.99, abs=0.02)
    assert run(broker, fetch, NOW, path, send=True, now=NOW).sent == 0
    assert [o.side for o in broker.sent] == ["buy", "sell"]


def test_order_not_yet_filled_is_followed_up(monkeypatch: pytest.MonkeyPatch,
                                             tmp_path: Path) -> None:  # fmt: skip
    path = tmp_path / "l.json"
    broker = FakeBroker(fill=False)
    patch_results(monkeypatch, ["buy"])
    assert run(broker, fetch, NOW, path, send=True, now=NOW).sent == 1
    assert load_ledger(path)[slot_key(P.id, "QQQ")].open_order_id
    report = run(broker, fetch, NOW, path, send=True, now=NOW)  # the order is filled by now
    assert report.sent == 0 and "ejecutada" in report.lines[0]
    assert load_ledger(path)[slot_key(P.id, "QQQ")].qty > 0


def test_inactive_account_blocks_everything(monkeypatch: pytest.MonkeyPatch,
                                            tmp_path: Path) -> None:  # fmt: skip
    patch_results(monkeypatch, ["buy"])
    broker = FakeBroker(status="ACCOUNT_UPDATED")
    report = run(broker, fetch, NOW, tmp_path / "l.json", send=True, now=NOW)
    assert broker.sent == [] and "no está activa" in report.lines[0]


def test_ledger_roundtrip_and_corrupt_file(tmp_path: Path) -> None:
    path = tmp_path / "x" / "l.json"
    save_ledger(path, {"a|QQQ": Slot(cash=1.5, qty=2.0)})
    assert load_ledger(path)["a|QQQ"].qty == 2.0
    path.write_text("{not json", encoding="utf-8")
    assert load_ledger(path) == {}


def test_stocks_wait_for_the_exchange_but_crypto_does_not(monkeypatch: pytest.MonkeyPatch,
                                                         tmp_path: Path) -> None:  # fmt: skip
    def fake_run_all(*_a: Any, **_k: Any) -> list[ProfileResult]:
        return results(sleeve(0, "buy"), sleeve(BTC, "buy"))

    monkeypatch.setattr(autotrade, "run_all", fake_run_all)
    broker = FakeBroker()
    broker.open = False
    report = run(broker, fetch, NOW, tmp_path / "l.json", send=True, now=NOW)
    assert [o.symbol for o in broker.sent] == ["BTC-USD"] and report.sent == 1
    assert any("[en espera]" in line and "QQQ" in line and "bolsa cerrada" in line
               for line in report.lines)  # fmt: skip
    broker.open = True  # next run: the stock order goes out, the crypto one is not repeated
    report = run(broker, fetch, NOW, tmp_path / "l.json", send=True, now=NOW)
    assert [o.symbol for o in broker.sent] == ["BTC-USD", "QQQ"]


def test_untradable_asset_is_skipped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    both = results(sleeve(0, "buy"), sleeve(BTC, "buy"))
    monkeypatch.setattr(autotrade, "run_all", lambda *_a, **_k: both)
    broker = FakeBroker()
    broker.untradable = {"BTC-USD"}
    report = run(broker, fetch, NOW, tmp_path / "l.json", send=True, now=NOW)
    assert [o.symbol for o in broker.sent] == ["QQQ"]
    assert any("no permite operar" in line for line in report.lines)


def test_universe_has_stocks_and_crypto() -> None:
    symbols = {s.symbol for s in SLEEVES}
    assert {"GOOGL", "META", "MSFT", "AMZN", "ETH-USD", "SOL-USD", "BTC-USD"} <= symbols
    assert all(s.is_crypto == s.symbol.endswith("-USD") for s in SLEEVES)
