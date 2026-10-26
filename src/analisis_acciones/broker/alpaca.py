"""Alpaca *paper trading* client (simulated money), standard library only.

The base URL is fixed to Alpaca's paper environment: there is deliberately no setting
that points this client at a real-money account. Credentials are read at every request
from the callables given (the OS credential store) and never appear in errors or logs.
Responses are external data: only the fields named here are read.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from analisis_acciones.models.errors import NetworkError, ProviderError, UserError
from analisis_acciones.providers.keyed import number
from analisis_acciones.providers.yahoo_http import _ssl_context

PAPER_URL = "https://paper-api.alpaca.markets"
SIGNUP_URL = "https://app.alpaca.markets/signup"
TIMEOUT_S = 20
MAX_BYTES = 5 * 1024 * 1024

#: (method, url, headers, body) -> (status, body). Injected so tests never use the network.
Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, bytes]]

_STOCK = re.compile(r"^[A-Z]{1,5}$")
_CRYPTO = re.compile(r"^([A-Z]{2,6})-USD$")
_ORDER_ID = re.compile(r"^[0-9a-fA-F-]{8,64}$")
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
SIDES = ("buy", "sell")
ORDER_TYPES = ("market", "limit")


def urllib_transport(
    method: str, url: str, headers: Mapping[str, str], body: bytes | None
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S, context=_ssl_context()) as resp:
            return int(resp.status), bytes(resp.read(MAX_BYTES))
    except urllib.error.HTTPError as exc:
        return exc.code, bytes(exc.read(MAX_BYTES))
    except (urllib.error.URLError, OSError) as exc:
        raise ConnectionError(type(exc).__name__) from None


@dataclass(frozen=True)
class AccountInfo:
    status: str
    equity: float
    cash: float
    buying_power: float


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    qty: float
    avg_price: float
    market_value: float
    unrealized_pl: float


@dataclass(frozen=True)
class BrokerOrder:
    id: str
    symbol: str
    side: str
    type: str
    qty: float
    limit_price: float | None
    status: str
    filled_avg_price: float | None
    filled_qty: float = 0.0


@dataclass(frozen=True)
class OrderRequest:
    symbol: str  # as the app writes it: AAPL or BTC-USD
    side: str
    qty: float  # ignored (may be 0) when ``notional`` is given
    type: str = "market"
    limit_price: float | None = None
    #: Dollars to buy instead of a quantity (market buys only; Alpaca fills the fraction).
    notional: float | None = None
    #: Unique id chosen by the caller: Alpaca rejects a second order with the same one.
    client_order_id: str | None = None


def to_alpaca_symbol(symbol: str) -> tuple[str, bool]:
    """(symbol in Alpaca's notation, is_crypto). Raises UserError for anything else."""
    s = symbol.strip().upper()
    crypto = _CRYPTO.match(s)
    if crypto:
        return f"{crypto.group(1)}/USD", True
    if _STOCK.match(s):
        return s, False
    raise UserError(
        f"unsupported symbol {symbol!r}",
        user_message="Símbolo no válido: use una acción de EE. UU. (AAPL) o una cripto contra "
        "dólar (BTC-USD).",
    )


def validate_order(order: OrderRequest) -> None:
    to_alpaca_symbol(order.symbol)
    if order.side not in SIDES or order.type not in ORDER_TYPES:
        raise UserError("bad side/type", user_message="Lado o tipo de orden no válido.")
    if order.notional is not None:
        if order.side != "buy" or order.type != "market" or not 1 <= order.notional <= 1_000_000:
            raise UserError(
                "bad notional",
                user_message="Una orden por monto solo puede ser una compra a mercado de "
                "1 dólar o más.",
            )
    elif not 0 < order.qty <= 1_000_000:
        raise UserError("bad qty", user_message="La cantidad debe ser mayor que cero.")
    if order.client_order_id is not None and not _CLIENT_ID.match(order.client_order_id):
        raise UserError("bad client id", user_message="Identificador de orden no válido.")
    if order.type == "limit" and not (order.limit_price and order.limit_price > 0):
        raise UserError("bad limit", user_message="Indique un precio límite mayor que cero.")


def _qty(qty: float) -> str:
    return str(int(qty)) if float(qty).is_integer() else repr(float(qty))


def _order(d: Mapping[str, Any]) -> BrokerOrder:
    return BrokerOrder(
        id=str(d.get("id", "")),
        symbol=str(d.get("symbol", "")),
        side=str(d.get("side", "")),
        type=str(d.get("type", d.get("order_type", ""))),
        qty=number(d.get("qty")) or 0.0,
        limit_price=number(d.get("limit_price")),
        status=str(d.get("status", "")),
        filled_avg_price=number(d.get("filled_avg_price")),
        filled_qty=number(d.get("filled_qty")) or 0.0,
    )


class AlpacaPaperClient:
    def __init__(
        self,
        key_id: Callable[[], str | None],
        secret: Callable[[], str | None],
        transport: Transport = urllib_transport,
    ) -> None:
        self._key_id = key_id
        self._secret = secret
        self._transport = transport

    # -- plumbing -------------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        key, secret = self._key_id(), self._secret()
        if not key or not secret:
            raise UserError(
                "alpaca: no credentials",
                user_message="Faltan las claves de Alpaca. Guárdelas en la ventana de Alpaca "
                "(cuenta de práctica / paper).",
            )
        return {
            "APCA-API-KEY-ID": key,
            "APCA-API-SECRET-KEY": secret,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None) -> Any:
        headers = self._headers()
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        try:
            status, raw = self._transport(method, PAPER_URL + path, headers, body)
        except ConnectionError:
            raise NetworkError("alpaca: connection failed") from None
        if status in (401, 403):
            raise UserError(
                f"alpaca HTTP {status}",
                user_message="Alpaca rechazó las claves. Compruebe que son las de la cuenta "
                "paper (práctica) y que están bien copiadas.",
            )
        if status == 429:
            raise ProviderError(
                "alpaca HTTP 429", user_message="Alpaca limitó las consultas; espere un minuto."
            )
        data: Any = None
        if raw:
            try:
                data = json.loads(raw.decode("utf-8"))
            except ValueError:
                data = None
        if status >= 400:
            detail = data.get("message") if isinstance(data, dict) else None
            text = detail[:200] if isinstance(detail, str) else ""
            raise ProviderError(
                f"alpaca HTTP {status}",
                user_message=f"Alpaca no aceptó la petición: {text}" if text
                else f"Alpaca devolvió un error (HTTP {status}).",
            )  # fmt: skip
        return data

    # -- reads ----------------------------------------------------------------------------

    def account(self) -> AccountInfo:
        d = self._request("GET", "/v2/account")
        if not isinstance(d, dict):
            raise ProviderError("alpaca: bad account response")
        return AccountInfo(
            status=str(d.get("status", "")),
            equity=number(d.get("equity")) or 0.0,
            cash=number(d.get("cash")) or 0.0,
            buying_power=number(d.get("buying_power")) or 0.0,
        )

    def positions(self) -> list[BrokerPosition]:
        d = self._request("GET", "/v2/positions")
        return [
            BrokerPosition(
                symbol=str(p.get("symbol", "")),
                qty=number(p.get("qty")) or 0.0,
                avg_price=number(p.get("avg_entry_price")) or 0.0,
                market_value=number(p.get("market_value")) or 0.0,
                unrealized_pl=number(p.get("unrealized_pl")) or 0.0,
            )
            for p in (d if isinstance(d, list) else [])
            if isinstance(p, dict)
        ]

    def orders(self, status: str = "all", limit: int = 50) -> list[BrokerOrder]:
        if status not in ("open", "closed", "all"):
            raise UserError("bad status")
        d = self._request("GET", f"/v2/orders?status={status}&limit={int(limit)}&direction=desc")
        return [_order(o) for o in (d if isinstance(d, list) else []) if isinstance(o, dict)]

    # -- writes (simulated money) ---------------------------------------------------------

    def place_order(self, order: OrderRequest) -> BrokerOrder:
        validate_order(order)
        symbol, crypto = to_alpaca_symbol(order.symbol)
        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": order.side,
            "type": order.type,
            "time_in_force": "gtc" if crypto else "day",
        }
        if order.notional is not None:
            payload["notional"] = f"{order.notional:.2f}"
        else:
            payload["qty"] = _qty(order.qty)
        if order.client_order_id:
            payload["client_order_id"] = order.client_order_id
        if order.type == "limit":
            payload["limit_price"] = repr(float(order.limit_price or 0))
        d = self._request("POST", "/v2/orders", payload)
        if not isinstance(d, dict):
            raise ProviderError("alpaca: bad order response")
        return _order(d)

    def market_open(self) -> bool:
        """Whether the US stock exchange is open right now (Alpaca's clock)."""
        d = self._request("GET", "/v2/clock")
        return bool(d.get("is_open")) if isinstance(d, dict) else False

    def is_tradable(self, symbol: str) -> bool:
        """Whether Alpaca lists ``symbol`` (AAPL, BTC-USD) as active and tradable."""
        alpaca_symbol, _crypto = to_alpaca_symbol(symbol)
        try:
            d = self._request("GET", "/v2/assets/" + urllib.parse.quote(alpaca_symbol, safe=""))
        except ProviderError:  # 404: unknown symbol
            return False
        return isinstance(d, dict) and d.get("status") == "active" and d.get("tradable") is True

    def get_order(self, order_id: str) -> BrokerOrder:
        if not _ORDER_ID.match(order_id):
            raise UserError("bad order id", user_message="Identificador de orden no válido.")
        d = self._request("GET", f"/v2/orders/{order_id}")
        if not isinstance(d, dict):
            raise ProviderError("alpaca: bad order response")
        return _order(d)

    def cancel_order(self, order_id: str) -> None:
        if not _ORDER_ID.match(order_id):
            raise UserError("bad order id", user_message="Identificador de orden no válido.")
        self._request("DELETE", f"/v2/orders/{order_id}")
