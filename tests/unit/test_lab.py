"""Experiment lab: books from fills, costs, hard limits, paper-only, reconciliation.

Synthetic data only (no network): a fake broker stands in for Alpaca.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from analisis_acciones.broker.alpaca import (
    DATA_URL,
    AccountInfo,
    AlpacaPaperClient,
    BrokerOrder,
    BrokerPosition,
    OrderRequest,
)
from analisis_acciones.lab import costs
from analisis_acciones.lab import executor as ex
from analisis_acciones.lab.book import build_book, max_drawdown
from analisis_acciones.lab.profiles import DEFAULT_CONFIG, LabProfile, Limits, load_profiles
from analisis_acciones.lab.report import benchmark_return
from analisis_acciones.lab.store import Store
from analisis_acciones.models.errors import InternalError, UserError

NOW = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)  # Tuesday 11:00 ET
DAY = NOW.date()


def profile(**changes: Any) -> LabProfile:
    base = LabProfile(
        id="P99", nombre="Prueba", hipotesis="", frecuencia="4h", estilo="", fallo="",
        universo=("BTC-USD", "ETH-USD", "AAPL"), herramientas=("reglas",), instrucciones="",
        limites=Limits(max_pct_activo=40, stop_posicion_pct=10, stop_perfil_pct=20,
                       max_operaciones_dia=3),
    )  # fmt: skip
    return replace(base, **changes)


def asset(fractionable: bool = True, min_size: str | None = "0.0001") -> dict[str, Any]:
    return {"status": "active", "tradable": True, "fractionable": fractionable,
            "min_order_size": min_size}  # fmt: skip


def market(stock_open: bool = True, **prices: float) -> ex.Market:
    p = {"BTC-USD": 80_000.0, "ETH-USD": 4_000.0, "AAPL": 300.0} | {
        k.replace("_", "-"): v for k, v in prices.items()
    }
    return ex.Market(
        stock_open=stock_open, prices=p,
        quotes={"BTC-USD": (79_990.0, 80_010.0), "ETH-USD": (3_999.0, 4_001.0),
                "AAPL": (299.95, 300.05)},
        assets={s: asset() for s in p}, account_qty={"BTC-USD": 1.0, "ETH-USD": 1.0, "AAPL": 1.0},
        day=DAY,
    )  # fmt: skip


class FakeBroker:
    def __init__(self, account_number: str = "PA123", fill: bool = True) -> None:
        self.account_number = account_number
        self.fill = fill
        self.sent: list[OrderRequest] = []
        self.orders: dict[str, BrokerOrder] = {}
        self.held: dict[str, float] = {}
        self.prices = {"BTC-USD": 80_000.0, "ETH-USD": 4_000.0, "AAPL": 300.0}

    def account(self) -> AccountInfo:
        return AccountInfo("ACTIVE", 1e5, 1e5, 4e5, self.account_number)

    def positions(self) -> list[BrokerPosition]:
        return [BrokerPosition(s.replace("-", ""), q, 0, 0, 0) for s, q in self.held.items()]

    def place_order(self, order: OrderRequest) -> BrokerOrder:
        self.sent.append(order)
        price = self.prices[order.symbol]
        qty = order.qty or round((order.notional or 0) / price, 9)
        o = BrokerOrder(
            id=f"0000000{len(self.sent)}-aaaa", symbol=order.symbol, side=order.side,
            type="market", qty=qty, limit_price=None,
            status="filled" if self.fill else "accepted",
            filled_avg_price=price if self.fill else None, filled_qty=qty if self.fill else 0,
            client_order_id=order.client_order_id or "", filled_at=NOW.isoformat(),
        )  # fmt: skip
        self.orders[o.id] = o
        if self.fill:
            sign = 1 if order.side == "buy" else -1
            self.held[order.symbol] = self.held.get(order.symbol, 0) + sign * qty
        return o

    def get_order(self, order_id: str) -> BrokerOrder:
        return self.orders[order_id]

    def order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        return next((o for o in self.orders.values() if o.client_order_id == client_order_id),
                    None)  # fmt: skip

    def clock(self) -> dict[str, Any]:
        return {"is_open": True}

    def asset(self, symbol: str) -> dict[str, Any] | None:
        return asset()


@pytest.fixture
def store() -> Store:
    return Store.open(":memory:")


def filled(store: Store, cid: str, symbol: str, side: str, qty: float, price: float,
           at: str = "2026-10-27T15:00:00+00:00", profile_id: str = "P99") -> None:  # fmt: skip
    store.add_order(client_order_id=cid, profile=profile_id, symbol=symbol, side=side,
                    notional=qty * price if side == "buy" else None,
                    qty=qty if side == "sell" else None, bid=None, ask=None, forced=False,
                    reason="", decision_id=None)  # fmt: skip
    fee_coin, fee_usd = ex.fees_for_fill(symbol, side, qty, price, DAY)
    store.update_order(cid, status="filled", filled_qty=qty, filled_price=price, filled_at=at,
                       fee_coin=fee_coin, fee_usd=fee_usd)  # fmt: skip


# -- costs ----------------------------------------------------------------------------------


def test_crypto_fees_match_what_alpaca_charged_this_account() -> None:
    # Seen on the paper account: LINK buy of 0.721 -> 0.0018025 LINK; SOL sell of 9.78 USD -> 0.03
    assert costs.crypto_fee("buy", 0.721, 14.1636) == (pytest.approx(0.0018025), 0.0)
    assert costs.crypto_fee("sell", 0.0827925, 118.1) == (0.0, 0.03)
    # a BTC buy of 0.000117 kept 0.000000293 (rounded up to 9 decimals). Alpaca rounds each
    # partial fill, so an order filled in two parts may keep 1e-9 more than this estimate.
    assert costs.crypto_fee("buy", 0.000117, 85_000)[0] == pytest.approx(2.93e-7, abs=1e-15)


def test_stock_fees_by_date() -> None:
    # Q4 2026: TAF paused, SEC 20.60 per million, CAT on both sides
    sell = costs.stock_fees("sell", 1.0, 1_000.0, date(2026, 11, 2))
    assert sell == pytest.approx(1_000 * 20.60 / 1e6 + costs.CAT_PER_SHARE)
    assert costs.stock_fees("buy", 2.0, 1_000.0, date(2026, 11, 2)) == pytest.approx(
        2 * costs.CAT_PER_SHARE
    )
    # 2027: TAF back, capped per trade
    big = costs.stock_fees("sell", 100_000, 1.0, date(2027, 1, 4))
    assert big == pytest.approx(100_000 * 20.60 / 1e6 + 9.79 + 100_000 * costs.CAT_PER_SHARE)


def test_round_trip_cost_includes_spread() -> None:
    assert costs.round_trip_cost_pct(True, 100, 0.1, DAY) == pytest.approx(0.6)
    assert costs.spread_pct(99.0, 101.0) == pytest.approx(2.0)
    assert costs.spread_pct(None, 101.0) is None
    assert costs.effective_spread(False, 332.0, 367.0) == (costs.STOCK_SPREAD_FALLBACK, False)
    assert costs.effective_spread(False, 299.95, 300.05)[1]
    assert costs.effective_spread(True, 4.42e-6, 4.44e-6)[0] == pytest.approx(0.4515, abs=1e-3)


# -- books ----------------------------------------------------------------------------------


def test_book_from_fills_with_fees_and_realized_result(store: Store) -> None:
    filled(store, "a", "BTC-USD", "buy", 0.0005, 80_000)  # 40 USD, keeps 0.25 % of the coin
    filled(store, "b", "BTC-USD", "sell", 0.0004, 90_000, at="2026-10-28T15:00:00+00:00")
    book = build_book("P99", 100.0, store.orders())
    pos = book.positions["BTC-USD"]
    assert pos.qty == pytest.approx(0.0005 * 0.9975 - 0.0004)
    sell_fee = costs.ceil_cent(0.0004 * 90_000 * 0.0025)
    assert book.cash == pytest.approx(100 - 40 + 36 - sell_fee)
    avg = 40 / (0.0005 * 0.9975)
    assert book.realized == pytest.approx(36 - sell_fee - avg * 0.0004)
    assert book.fees == pytest.approx(0.0005 * 0.0025 * 80_000 + sell_fee)
    assert book.closed_sells == book.winning_sells == 1


def test_selling_it_all_leaves_no_dust(store: Store) -> None:
    filled(store, "a", "BTC-USD", "buy", 0.000134714, 80_000)
    filled(store, "b", "BTC-USD", "sell", 0.000134376, 80_000, at="2026-10-28T15:00:00+00:00")
    assert build_book("P99", 100.0, store.orders()).positions == {}


def test_open_orders_reserve_cash_and_quantity(store: Store) -> None:
    filled(store, "a", "ETH-USD", "buy", 0.005, 4_000)
    store.add_order(client_order_id="b", profile="P99", symbol="BTC-USD", side="buy",
                    notional=30.0, qty=None, bid=None, ask=None, forced=False, reason="",
                    decision_id=None)  # fmt: skip
    store.add_order(client_order_id="c", profile="P99", symbol="ETH-USD", side="sell",
                    notional=None, qty=0.002, bid=None, ask=None, forced=False, reason="",
                    decision_id=None)  # fmt: skip
    book = build_book("P99", 100.0, store.orders())
    assert book.reserved_cash == 30 and book.free_cash == pytest.approx(80 - 30)
    assert book.positions["ETH-USD"].free_qty == pytest.approx(0.005 * 0.9975 - 0.002)


def test_books_are_separate_per_profile(store: Store) -> None:
    filled(store, "a", "BTC-USD", "buy", 0.0005, 80_000, profile_id="P01")
    assert build_book("P02", 100.0, store.orders()).positions == {}


def test_max_drawdown() -> None:
    assert max_drawdown([100, 110, 99, 120, 108]) == pytest.approx(10.0)
    assert max_drawdown([100, 101, 102]) == 0.0


# -- hard limits ----------------------------------------------------------------------------


def buy(sym: str, usd: float, target: float = 5.0) -> dict[str, Any]:
    return {"simbolo": sym, "lado": "comprar", "usd": usd, "objetivo_pct": target}


def test_validate_accepts_a_buy_within_limits(store: Store) -> None:
    plan = ex.validate(profile(), build_book("P99", 100, []), {"ordenes": [buy("BTC-USD", 30)]},
                       market(), 0)  # fmt: skip
    assert [(o.symbol, o.notional) for o in plan.orders] == [("BTC-USD", 30.0)] and not plan.refused


@pytest.mark.parametrize(
    ("order", "why"),
    [
        (buy("BTC-USD", 120), "efectivo libre"),
        (buy("BTC-USD", 45), "40 %"),
        (buy("BTC-USD", 1.0), "mínimo"),
        (buy("BTC-USD", 8.0), "mínimo"),  # Alpaca: crypto buys from 10 USD
        (buy("BTC-USD", 20, target=0.5), "no compensa"),
        (buy("DOGE-USD", 10), "fuera del universo"),
        ({"simbolo": "ETH-USD", "lado": "vender", "fraccion": 1}, "no tiene este activo"),
    ],
)
def test_validate_refuses_what_breaks_a_limit(order: dict[str, Any], why: str) -> None:
    plan = ex.validate(profile(), build_book("P99", 100, []), {"ordenes": [order]}, market(), 0)
    assert plan.orders == [] and why in plan.refused[0]


def test_stocks_are_not_queued_while_the_market_is_closed() -> None:
    plan = ex.validate(profile(), build_book("P99", 100, []), {"ordenes": [buy("AAPL", 20)]},
                       market(stock_open=False), 0)  # fmt: skip
    assert plan.orders == [] and "cerrado" in plan.refused[0]
    crypto = ex.validate(profile(), build_book("P99", 100, []), {"ordenes": [buy("ETH-USD", 20)]},
                         market(stock_open=False), 0)  # fmt: skip
    assert len(crypto.orders) == 1  # crypto trades around the clock


def test_trades_per_day_and_one_order_per_asset() -> None:
    orders = [buy("BTC-USD", 20), buy("BTC-USD", 10), buy("ETH-USD", 20)]
    plan = ex.validate(profile(), build_book("P99", 100, []), {"ordenes": orders}, market(), 2)
    assert [o.symbol for o in plan.orders] == ["BTC-USD"]
    assert any("otra orden" in r for r in plan.refused)
    assert any("operaciones por día" in r for r in plan.refused)


def test_sells_only_own_quantity_capped_by_the_account(store: Store) -> None:
    filled(store, "a", "ETH-USD", "buy", 0.01, 4_000)
    book = build_book("P99", 100, store.orders())
    m = replace(market(), account_qty={"ETH-USD": 0.006})
    plan = ex.validate(profile(), book, {"ordenes": [
        {"simbolo": "ETH-USD", "lado": "vender", "fraccion": 1}]}, m, 0)  # fmt: skip
    assert plan.orders[0].qty == pytest.approx(0.006) and plan.notes


def test_profile_past_its_loss_limit_can_only_sell(store: Store) -> None:
    filled(store, "a", "ETH-USD", "buy", 0.01, 4_000)
    book = build_book("P99", 100, store.orders())
    m = market(ETH_USD=1_000.0)  # the 40 USD position is now worth ~10: -30 % for the profile
    plan = ex.validate(profile(limites=Limits(40, 90, 20, 3)), book, {"ordenes": [
        buy("BTC-USD", 10), {"simbolo": "ETH-USD", "lado": "vender"}]}, m, 0)  # fmt: skip
    assert [o.side for o in plan.orders] == ["sell"] and "solo vende" in plan.refused[0]


def test_forced_stop_sells_a_position_past_its_limit(store: Store) -> None:
    filled(store, "a", "ETH-USD", "buy", 0.01, 4_000)
    book = build_book("P99", 100, store.orders())
    assert ex.forced_stops(profile(), book, market(ETH_USD=3_700.0)).orders == []  # -7.7 %
    (stop,) = ex.forced_stops(profile(), book, market(ETH_USD=3_500.0)).orders  # -12.7 %
    assert stop.forced and stop.side == "sell" and stop.qty == pytest.approx(0.01 * 0.9975)


# -- turns ----------------------------------------------------------------------------------


def test_turns_by_frequency(store: Store) -> None:
    p4 = profile()
    assert ex.is_due(p4, store, NOW)[0]
    store.add_decision("P99", "nada", "", {}, at=(NOW - timedelta(hours=2)).isoformat())
    assert not ex.is_due(p4, store, NOW)[0]
    assert ex.is_due(p4, store, NOW + timedelta(hours=2))[0]
    daily = profile(id="P98", frecuencia="diaria")
    store.add_decision("P98", "comprar", "", {}, at=(NOW - timedelta(hours=3)).isoformat())
    assert not ex.is_due(daily, store, NOW)[0]
    assert ex.is_due(daily, store, NOW + timedelta(days=1))[0]
    # a run that could not act (market closed, dry run) does not use up the turn
    weekly = profile(id="P97", frecuencia="semanal")
    store.add_decision("P97", "sin_accion", "", {}, at=NOW.isoformat())
    store.add_decision("P97", "simulacro", "", {}, at=NOW.isoformat())
    assert ex.is_due(weekly, store, NOW)[0]


# -- sending and reconciliation -------------------------------------------------------------


def planned(sym: str = "BTC-USD", usd: float = 30.0) -> list[ex.Planned]:
    return [ex.Planned(sym, "buy", usd, None, "prueba")]


def test_orders_go_only_to_a_paper_account(store: Store) -> None:
    broker = FakeBroker(account_number="1234567")  # a live account number
    with pytest.raises(ex.LabAbort):
        ex.ensure_paper(broker)
    results = ex.send_orders(broker, store, profile(), planned(), market(), NOW, 1,
                             wait=lambda _s: None)  # fmt: skip
    assert broker.sent == [] and results[0]["estado"] == "abortada"


def test_client_rejects_writes_outside_the_paper_url() -> None:
    client = AlpacaPaperClient(lambda: "k", lambda: "s",
                               transport=lambda *_a: (200, b"{}"))  # fmt: skip
    with pytest.raises(InternalError):
        client._request("POST", "/v2/orders", {}, base=DATA_URL)
    with pytest.raises(InternalError):
        client._request("GET", "/v2/account", base="https://api.alpaca.markets")


def test_send_records_the_real_fill_with_a_prefixed_id(store: Store) -> None:
    broker = FakeBroker()
    broker.prices["BTC-USD"] = 81_000.0  # fills worse than the 80,000 the agent saw
    (r,) = ex.send_orders(broker, store, profile(), planned(), market(), NOW, 1,
                          wait=lambda _s: None)  # fmt: skip
    assert r["orden"].startswith("P99-") and r["estado"] == "filled"
    book = build_book("P99", 100, store.orders())
    qty = round(30 / 81_000, 9)
    assert book.positions["BTC-USD"].qty == pytest.approx(qty * 0.9975)
    assert book.cash == pytest.approx(100 - qty * 81_000)


def test_a_run_that_died_mid_order_is_reconciled_first(store: Store) -> None:
    broker = FakeBroker()
    store.add_order(client_order_id="P99-x-BTCUSD-B1", profile="P99", symbol="BTC-USD",
                    side="buy", notional=30, qty=None, bid=None, ask=None, forced=False,
                    reason="", decision_id=None)  # fmt: skip
    broker.place_order(OrderRequest("BTC-USD", "buy", 0, notional=30,
                                    client_order_id="P99-x-BTCUSD-B1"))  # fmt: skip
    store.add_order(client_order_id="P99-y-ETHUSD-B1", profile="P99", symbol="ETH-USD",
                    side="buy", notional=20, qty=None, bid=None, ask=None, forced=False,
                    reason="", decision_id=None)  # fmt: skip
    notes = ex.reconcile(broker, store, now=datetime.now(UTC) + timedelta(minutes=5))
    states = {r["client_order_id"]: r["status"] for r in store.orders()}
    assert states == {"P99-x-BTCUSD-B1": "filled", "P99-y-ETHUSD-B1": "not_sent"}
    assert len(notes) == 2
    book = build_book("P99", 100, store.orders())
    assert book.reserved_cash == 0 and "BTC-USD" in book.positions


def test_open_order_is_followed_until_filled(store: Store) -> None:
    broker = FakeBroker(fill=False)
    ex.send_orders(broker, store, profile(), planned(), market(), NOW, 1, wait=lambda _s: None)
    assert build_book("P99", 100, store.orders()).reserved_cash == 30
    (o,) = broker.orders.values()
    broker.orders[o.id] = replace(o, status="filled", filled_qty=o.qty, filled_avg_price=80_000.0)
    ex.reconcile(broker, store)
    book = build_book("P99", 100, store.orders())
    assert book.reserved_cash == 0 and book.positions["BTC-USD"].qty > 0


def test_invariant_flags_books_above_the_account(store: Store) -> None:
    filled(store, "a", "BTC-USD", "buy", 0.001, 80_000, profile_id="P01")
    filled(store, "b", "BTC-USD", "buy", 0.001, 80_000, profile_id="P02")
    books = {p: build_book(p, 100, store.orders()) for p in ("P01", "P02")}
    qty = ex.account_quantities([BrokerPosition("BTCUSD", 0.001995, 0, 0, 0)], {"BTC-USD"})
    assert ex.invariant_issues(books, qty) == []
    assert ex.invariant_issues(books, {"BTC-USD": 0.0015})


# -- benchmarks and config ------------------------------------------------------------------


def test_benchmark_from_the_profile_start(store: Store) -> None:
    store.add_prices({"BTC-USD": 80_000.0}, at="2026-10-27T15:00:00+00:00")
    assert benchmark_return(store, "BTC-USD", "2026-10-27T14:00:00+00:00", 88_000.0) == (
        pytest.approx((0.9975 * 1.1 - 1) * 100)
    )
    assert benchmark_return(store, "SPY", "2026-10-27T14:00:00+00:00", 500.0) is None


def test_repository_profiles_are_valid_and_distinct() -> None:
    profiles = load_profiles(DEFAULT_CONFIG)
    assert 8 <= len(profiles) <= 12
    assert len({(p.frecuencia, p.universo) for p in profiles.values()}) == len(profiles)


def test_bad_config_is_refused(tmp_path: Path) -> None:
    bad = {"perfiles": [{"id": "P01", "frecuencia": "30m", "universo": ["BTC-USD"]}]}
    path = tmp_path / "p.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(UserError):
        load_profiles(path)
