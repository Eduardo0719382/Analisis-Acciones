"""Parse a broker's CSV export of trades (purchases and sales).

The file is external data: nothing in it is executed or interpreted beyond the
columns listed here. Rows that cannot be read are reported with their line
number and skipped; nothing is guessed.

Columns (header names are case- and accent-insensitive, Spanish or English):

    fecha / date                         required: AAAA-MM-DD or DD/MM/AAAA (optional time)
    ticker / símbolo / symbol            required
    operación / tipo / side / action     compra|venta|buy|sell (optional: the sign of the
                                         quantity then decides, negative = sale)
    cantidad / acciones / quantity       required
    precio / price                       required, in the asset's currency
    comisión / comisiones / fee          optional (0 if missing)
    divisa / moneda / currency           optional (otherwise the asset's trading currency)
    nota / motivo / comentario / note    optional

US-style MM/DD/YYYY dates are rejected rather than guessed (day/month confusion
would silently corrupt the history).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from analisis_acciones.models.errors import UserError

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 20_000
MAX_NOTE = 500

_ALIASES = {
    "fecha": "date", "date": "date", "trade date": "date", "fecha operacion": "date",
    "fecha de operacion": "date", "fecha ejecucion": "date", "datetime": "date", "time": "date",
    "ticker": "symbol", "simbolo": "symbol", "symbol": "symbol", "valor": "symbol",
    "activo": "symbol", "instrumento": "symbol",
    "operacion": "side", "tipo": "side", "side": "side", "action": "side", "accion": "side",
    "type": "side", "compra/venta": "side", "buy/sell": "side",
    "cantidad": "quantity", "acciones": "quantity", "titulos": "quantity",
    "quantity": "quantity", "shares": "quantity", "qty": "quantity", "numero": "quantity",
    "precio": "price", "price": "price", "precio unitario": "price", "cotizacion": "price",
    "comision": "commission", "comisiones": "commission", "commission": "commission",
    "fee": "commission", "fees": "commission", "gastos": "commission",
    "divisa": "currency", "moneda": "currency", "currency": "currency",
    "nota": "note", "notas": "note", "note": "note", "notes": "note", "motivo": "note",
    "comentario": "note",
    "importe": "amount", "amount": "amount", "total": "amount", "neto": "amount",
    "importe neto": "amount", "net amount": "amount", "importe total": "amount",
}  # fmt: skip
# Cash rows (``operación`` column), mapped to the portfolio's cash movement kinds.
_CASH_WORDS = {
    "cash_dividend": {"dividendo", "dividendos", "dividend", "dividends"},
    "interest": {"interes", "intereses", "interest"},
    "fee": {"comision", "comisiones", "fee", "fees", "gasto", "gastos", "custodia"},
    "deposit": {"deposito", "ingreso", "aportacion", "deposit"},
    "withdrawal": {"retirada", "retiro", "reintegro", "withdrawal"},
}
_BUY = {"compra", "c", "buy", "b", "bought", "purchase", "comprar"}
_SELL = {"venta", "v", "sell", "s", "sold", "sale", "vender"}
_REQUIRED = ("date",)
_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?$")
_DMY = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?: \d{1,2}:\d{2}(?::\d{2})?)?$")
_SYMBOL = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=]{0,14}$")
_CURRENCY = re.compile(r"^[A-Za-z]{3}$")


@dataclass(frozen=True)
class ImportedTrade:
    line: int
    day: date
    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    price: float
    commission: float
    currency: str | None
    note: str


@dataclass(frozen=True)
class ImportedCash:
    line: int
    day: date
    kind: str  # deposit, withdrawal, cash_dividend, interest or fee
    amount: float  # positive
    symbol: str  # the asset of a dividend, "" otherwise
    currency: str | None
    note: str


@dataclass(frozen=True)
class TradesFile:
    trades: list[ImportedTrade] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)  # "Línea N: motivo"
    missing_commission: bool = False
    cash: list[ImportedCash] = field(default_factory=list)


def _canonical(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return _ALIASES.get(" ".join(text.strip().strip('"').lower().split()), "")


def read_trades_csv(path: Path) -> TradesFile:
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise UserError("trades csv too large", user_message="El archivo supera 5 MB.")
        data = path.read_bytes()
    except OSError as exc:
        raise UserError(str(exc), user_message="No se pudo leer el archivo.") from exc
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return parse_trades_text(text)


def _parse_date(text: str) -> date | None:
    text = text.strip()
    try:
        if m := _ISO.match(text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := _DMY.match(text):
            return date(int(m[3]), int(m[2]), int(m[1]))
    except ValueError:
        return None
    return None


def _number(text: str, decimal_comma: bool) -> float | None:
    clean = text.strip().replace("\u00a0", "").replace(" ", "")
    clean = clean.replace("$", "").replace("€", "").replace("£", "")
    if not clean:
        return None
    # Decided per file, not per cell, so "123.45" is never read as 12345.
    clean = clean.replace(".", "").replace(",", ".") if decimal_comma else clean.replace(",", "")
    try:
        value = float(clean)
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def parse_trades_text(text: str) -> TradesFile:
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise UserError("empty trades csv", user_message="El archivo está vacío.")
    header_line = lines[0]
    delimiter = ";" if header_line.count(";") > header_line.count(",") else ","
    if header_line.count("\t") > max(header_line.count(";"), header_line.count(",")):
        delimiter = "\t"
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = next(reader)
    columns = [_canonical(h) for h in header]
    missing = [c for c in _REQUIRED if c not in columns]
    if not missing and not ({"symbol", "quantity", "price"} <= set(columns) or "side" in columns):
        missing = ["symbol/quantity/price"]
    if missing:
        raise UserError(
            f"missing columns {missing}",
            user_message=(
                "Faltan columnas obligatorias: fecha, ticker, cantidad y precio (y, si no se "
                "deduce del signo de la cantidad, la operación compra/venta)."
            ),
        )
    position = {c: columns.index(c) for c in set(columns) if c}
    rows = list(reader)
    if len(rows) > MAX_ROWS:
        raise UserError("too many rows", user_message=f"El archivo tiene más de {MAX_ROWS} filas.")
    numeric_cols = [
        position[c] for c in ("quantity", "price", "commission", "amount") if c in position
    ]
    decimal_comma = delimiter == ";" and any(
        "," in row[i] for row in rows for i in numeric_cols if i < len(row)
    )

    trades: list[ImportedTrade] = []
    cash: list[ImportedCash] = []
    errors: list[str] = []
    for offset, row in enumerate(rows):
        line = offset + 2
        if not any(cell.strip() for cell in row):
            continue

        def cell(name: str, row: list[str] = row) -> str:
            i = position.get(name)
            return row[i].strip() if i is not None and i < len(row) else ""

        day = _parse_date(cell("date"))
        if day is None:
            errors.append(f"Línea {line}: fecha «{cell('date')[:20]}» no válida.")
            continue
        side_text = cell("side").lower()
        words = set(re.split(r"[^a-z]+", unicodedata.normalize("NFKD", side_text)
                             .encode("ascii", "ignore").decode()))  # fmt: skip
        cash_kind = next((k for k, names in _CASH_WORDS.items() if words & names), None)
        if cash_kind is not None and not words & (_BUY | _SELL):
            entry = _cash_row(line, day, cash_kind, cell, decimal_comma)
            if isinstance(entry, str):
                errors.append(entry)
            else:
                cash.append(entry)
            continue
        symbol = cell("symbol").upper()
        if not _SYMBOL.match(symbol):
            errors.append(f"Línea {line}: ticker «{symbol[:20]}» no válido.")
            continue
        quantity = _number(cell("quantity"), decimal_comma)
        price = _number(cell("price"), decimal_comma)
        if quantity is None or quantity == 0:
            errors.append(f"Línea {line}: cantidad no válida.")
            continue
        if price is None or price <= 0:
            errors.append(f"Línea {line}: precio no válido.")
            continue
        if side_text:
            if words & _BUY and not words & _SELL:
                side = "buy"
            elif words & _SELL and not words & _BUY:
                side = "sell"
            else:
                errors.append(f"Línea {line}: operación «{side_text[:20]}» no reconocida.")
                continue
        elif "side" in position:
            errors.append(f"Línea {line}: falta la operación (compra o venta).")
            continue
        else:
            side = "sell" if quantity < 0 else "buy"
        commission = 0.0
        if cell("commission"):
            fee = _number(cell("commission"), decimal_comma)
            if fee is None:
                errors.append(f"Línea {line}: comisión no válida.")
                continue
            commission = abs(fee)
        currency = cell("currency") or None
        if currency is not None:
            if not _CURRENCY.match(currency) and currency not in ("GBp", "GBX", "ZAc", "ILA"):
                errors.append(f"Línea {line}: divisa «{currency[:10]}» no válida.")
                continue
            currency = currency if currency in ("GBp", "ZAc") else currency.upper()
        note = " ".join(cell("note").split())[:MAX_NOTE]
        trades.append(ImportedTrade(line, day, symbol, side, abs(quantity), price,
                                    commission, currency, note))  # fmt: skip
    return TradesFile(trades, errors, "commission" not in position, cash)


def _currency(text: str) -> str | bool | None:
    """Normalised currency, None when empty, False when invalid."""
    if not text:
        return None
    if text in ("GBp", "ZAc"):
        return text
    if text in ("GBX", "ILA") or _CURRENCY.match(text):
        return text.upper()
    return False


def _cash_row(line: int, day: date, kind: str, cell: Callable[[str], str],
              decimal_comma: bool) -> ImportedCash | str:  # fmt: skip
    """A cash row (dividend, interest, fee, deposit, withdrawal) or the reason it is invalid."""
    amount = _number(cell("amount"), decimal_comma) if cell("amount") else None
    if amount is None:
        quantity = _number(cell("quantity"), decimal_comma)
        price = _number(cell("price"), decimal_comma)
        if quantity is not None and price is not None:
            amount = quantity * price
    if amount is None or amount == 0:
        return f"Línea {line}: falta el importe del movimiento."
    symbol = cell("symbol").upper()
    if kind == "cash_dividend" and not _SYMBOL.match(symbol):
        return f"Línea {line}: el dividendo no tiene un ticker válido."
    currency = _currency(cell("currency"))
    if currency is False:
        return f"Línea {line}: divisa «{cell('currency')[:10]}» no válida."
    note = " ".join(cell("note").split())[:MAX_NOTE]
    return ImportedCash(line, day, kind, abs(amount),
                        symbol if kind == "cash_dividend" else "",
                        currency if isinstance(currency, str) else None, note)  # fmt: skip


def summary_dates(trades: list[ImportedTrade]) -> tuple[date, date] | None:
    if not trades:
        return None
    days = [t.day for t in trades]
    return min(days), max(days)
