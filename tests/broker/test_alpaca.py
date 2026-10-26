"""Alpaca paper client with SIMULATED responses; credentials never leak."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest

from analisis_acciones.broker.alpaca import (
    PAPER_URL,
    AlpacaPaperClient,
    OrderRequest,
    to_alpaca_symbol,
    validate_order,
)
from analisis_acciones.models.errors import NetworkError, ProviderError, UserError

KEY, SECRET = "PKTESTKEY123456", "SECRETTESTVALUE1234567890"


class FakeTransport:
    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status, self.body = status, body
        self.calls: list[tuple[str, str, Mapping[str, str], dict[str, Any] | None]] = []

    def __call__(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> tuple[int, bytes]:
        self.calls.append((method, url, headers, json.loads(body) if body else None))
        return self.status, json.dumps(self.body).encode() if self.body is not None else b""


def client(transport: FakeTransport, key: str | None = KEY, secret: str | None = SECRET):
    return AlpacaPaperClient(lambda: key, lambda: secret, transport)


def test_symbols() -> None:
    assert to_alpaca_symbol("aapl") == ("AAPL", False)
    assert to_alpaca_symbol("BTC-USD") == ("BTC/USD", True)
    for bad in ("", "AAPL.MX", "BTC-EUR", "A B", "../x"):
        with pytest.raises(UserError):
            to_alpaca_symbol(bad)


def test_validation() -> None:
    validate_order(OrderRequest("AAPL", "buy", 1.5))
    for order in (
        OrderRequest("AAPL", "short", 1),
        OrderRequest("AAPL", "buy", 0),
        OrderRequest("AAPL", "buy", float("nan")),
        OrderRequest("AAPL", "buy", 1, "limit"),
        OrderRequest("AAPL", "buy", 1, "stop"),
    ):
        with pytest.raises(UserError):
            validate_order(order)


def test_account_positions_orders_use_paper_url_and_headers() -> None:
    t = FakeTransport(body={"status": "ACTIVE", "equity": "100000", "cash": "5e4",
                            "buying_power": "200000"})  # fmt: skip
    account = client(t).account()
    assert (account.equity, account.cash, account.buying_power) == (100000, 50000, 200000)
    method, url, headers, _ = t.calls[0]
    assert (method, url) == ("GET", PAPER_URL + "/v2/account")
    assert headers["APCA-API-KEY-ID"] == KEY and headers["APCA-API-SECRET-KEY"] == SECRET

    t.body = [{"symbol": "AAPL", "qty": "2", "avg_entry_price": "190.5",
               "market_value": "385", "unrealized_pl": "4"}, "junk"]  # fmt: skip
    (pos,) = client(t).positions()
    assert (pos.symbol, pos.qty, pos.unrealized_pl) == ("AAPL", 2, 4)

    t.body = [{"id": "a1b2c3d4-0000", "symbol": "AAPL", "side": "buy", "type": "limit",
               "qty": "1", "limit_price": "150", "status": "new",
               "filled_avg_price": None}]  # fmt: skip
    (order,) = client(t).orders()
    assert order.limit_price == 150 and order.filled_avg_price is None


def test_place_order_payloads() -> None:
    t = FakeTransport(body={"id": "a1b2c3d4-0000", "symbol": "AAPL", "side": "buy",
                            "type": "market", "qty": "3", "status": "accepted"})  # fmt: skip
    placed = client(t).place_order(OrderRequest("AAPL", "buy", 3))
    method, url, _, payload = t.calls[0]
    assert (method, url) == ("POST", PAPER_URL + "/v2/orders")
    assert payload == {"symbol": "AAPL", "side": "buy", "type": "market", "qty": "3",
                       "time_in_force": "day"}  # fmt: skip
    assert placed.status == "accepted"

    client(t).place_order(OrderRequest("BTC-USD", "sell", 0.25, "limit", 60000))
    payload = t.calls[1][3]
    assert payload is not None
    assert payload["symbol"] == "BTC/USD" and payload["time_in_force"] == "gtc"
    assert payload["qty"] == "0.25" and payload["limit_price"] == "60000.0"


def test_invalid_order_never_reaches_the_network() -> None:
    t = FakeTransport(body={})
    with pytest.raises(UserError):
        client(t).place_order(OrderRequest("AAPL", "buy", -1))
    assert t.calls == []


def test_cancel_checks_the_id() -> None:
    t = FakeTransport(status=204)
    client(t).cancel_order("a1b2c3d4-0000")
    assert t.calls[0][:2] == ("DELETE", PAPER_URL + "/v2/orders/a1b2c3d4-0000")
    with pytest.raises(UserError):
        client(t).cancel_order("../account")


def test_missing_keys_and_rejections() -> None:
    t = FakeTransport(body={})
    with pytest.raises(UserError, match="no credentials"):
        client(t, key=None).account()
    assert t.calls == []
    for status in (401, 403):
        with pytest.raises(UserError) as info:
            client(FakeTransport(status=status, body={})).account()
        assert KEY not in str(info.value) and SECRET not in info.value.user_message


def test_provider_errors_carry_alpaca_message() -> None:
    t = FakeTransport(status=422, body={"message": "insufficient buying power"})
    with pytest.raises(ProviderError) as info:
        client(t).place_order(OrderRequest("AAPL", "buy", 1))
    assert "insufficient buying power" in info.value.user_message
    with pytest.raises(ProviderError):
        client(FakeTransport(status=429, body={})).account()


def test_connection_failure_is_a_network_error() -> None:
    def broken(*_args: Any) -> tuple[int, bytes]:
        raise ConnectionError("down")

    with pytest.raises(NetworkError) as info:
        AlpacaPaperClient(lambda: KEY, lambda: SECRET, broken).account()
    assert KEY not in str(info.value)
