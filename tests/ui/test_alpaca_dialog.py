"""Alpaca dialog: keys in the credential store, account view and confirmed orders."""

from __future__ import annotations

import json
from typing import Any

from pytestqt.qtbot import QtBot

from analisis_acciones.broker.alpaca import AlpacaPaperClient
from analisis_acciones.services.api_keys import MemoryKeyStore
from analisis_acciones.ui.alpaca_dialog import AlpacaDialog


class Transport:
    def __init__(self) -> None:
        self.posted: list[dict[str, Any]] = []

    def __call__(self, method: str, url: str, headers: Any, body: bytes | None):
        path = url.split(".markets", 1)[1]
        if method == "POST":
            self.posted.append(json.loads(body or b"{}"))
            data: Any = {"id": "a1b2c3d4-0000", "symbol": "AAPL", "side": "buy",
                         "type": "market", "qty": "1", "status": "accepted"}  # fmt: skip
        elif path == "/v2/account":
            data = {"status": "ACTIVE", "equity": "1000", "cash": "500", "buying_power": "900"}
        elif path == "/v2/positions":
            data = [{"symbol": "MSFT", "qty": "2", "avg_entry_price": "300",
                     "market_value": "620", "unrealized_pl": "20"}]  # fmt: skip
        else:
            data = []
        return 200, json.dumps(data).encode()


def make(qtbot: QtBot, with_keys: bool = True) -> tuple[AlpacaDialog, Transport, MemoryKeyStore]:
    keys = MemoryKeyStore()
    if with_keys:
        keys.set("alpaca_id", "PKTESTKEY123456")
        keys.set("alpaca_secret", "SECRETTESTVALUE1234567890")
    transport = Transport()
    client = AlpacaPaperClient(
        lambda: keys.get("alpaca_id"), lambda: keys.get("alpaca_secret"), transport
    )
    dialog = AlpacaDialog(keys, client)
    qtbot.addWidget(dialog)
    return dialog, transport, keys


def test_loads_account_and_positions(qtbot: QtBot) -> None:
    dialog, _, _ = make(qtbot)
    qtbot.waitUntil(lambda: "ACTIVE" in dialog.account_label.text())
    assert dialog.positions_table.item(0, 0).text() == "MSFT"
    assert "1,000.00" in dialog.account_label.text()


def test_save_keys_masked_and_validated(qtbot: QtBot) -> None:
    dialog, _, keys = make(qtbot, with_keys=False)
    assert "Guarde" in dialog.account_label.text()
    dialog.key_fields["alpaca_id"].setText("bad key!")
    dialog.save_key("alpaca_id")
    assert "formato" in dialog.message.text() and keys.get("alpaca_id") is None
    dialog.key_fields["alpaca_id"].setText("PKTESTKEY123456")
    dialog.save_key("alpaca_id")
    assert dialog.key_status["alpaca_id"].text() == "Clave guardada (PKT…456)."
    assert dialog.key_fields["alpaca_id"].text() == ""


def test_order_needs_confirmation(qtbot: QtBot) -> None:
    dialog, transport, _ = make(qtbot)
    qtbot.waitUntil(lambda: "ACTIVE" in dialog.account_label.text())
    dialog.symbol.setText("aapl")
    dialog.qty.setValue(1)
    dialog.confirm = lambda _text: False
    dialog.send_order()
    assert transport.posted == []
    seen: list[str] = []
    dialog.confirm = lambda text: seen.append(text) or True
    dialog.send_order()
    qtbot.waitUntil(lambda: len(transport.posted) == 1)
    assert transport.posted[0]["symbol"] == "AAPL" and "AAPL" in seen[0]
    qtbot.waitUntil(lambda: "accepted" in dialog.message.text())


def test_invalid_order_is_not_sent(qtbot: QtBot) -> None:
    dialog, transport, _ = make(qtbot)
    dialog.confirm = lambda _text: True
    dialog.symbol.setText("NOT A SYMBOL")
    dialog.send_order()
    assert "Símbolo" in dialog.message.text() and transport.posted == []
