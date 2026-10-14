"""Earnings and dividend dates published by the data source, in plain words.

The dates are the source's (Yahoo Finance): a company can move them and an
"estimated" earnings date is not confirmed. Nothing is inferred here; only the
dates the source gives are listed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from analisis_acciones.models.market import Fundamentals

EARNINGS, EX_DIVIDEND, DIVIDEND_PAYMENT = "earnings", "ex_dividend", "dividend_payment"
LABELS = {
    EARNINGS: "Presentación de resultados",
    EX_DIVIDEND: "Fecha ex-dividendo",
    DIVIDEND_PAYMENT: "Pago del dividendo",
}
MEANINGS = {
    EARNINGS: "La empresa publica sus cuentas; el precio suele moverse más ese día.",
    EX_DIVIDEND: "Para cobrar el dividendo hay que tener la acción antes de este día.",
    DIVIDEND_PAYMENT: "Día en que se paga el dividendo a quien lo tenía antes de la fecha ex.",
}
UPCOMING_DAYS = 14


@dataclass(frozen=True)
class CalendarEntry:
    symbol: str
    kind: str
    day: date
    day_end: date | None = None  # earnings window end, when the source gives a range
    estimated: bool = False

    @property
    def label(self) -> str:
        return LABELS[self.kind]


def entries(f: Fundamentals) -> list[CalendarEntry]:
    found = []
    if f.earnings_date is not None:
        found.append(CalendarEntry(f.symbol, EARNINGS, f.earnings_date, f.earnings_date_end,
                                   bool(f.earnings_estimated)))  # fmt: skip
    if f.ex_dividend_date is not None:
        found.append(CalendarEntry(f.symbol, EX_DIVIDEND, f.ex_dividend_date))
    if f.dividend_payment_date is not None:
        found.append(CalendarEntry(f.symbol, DIVIDEND_PAYMENT, f.dividend_payment_date))
    return sorted(found, key=lambda e: e.day)


def when(entry: CalendarEntry, today: date) -> str:
    """'hoy', 'mañana', 'dentro de 5 días', 'hace 3 días' (counted to the window start)."""
    days = (entry.day - today).days
    if days == 0:
        return "hoy"
    if days == 1:
        return "mañana"
    if days == -1:
        return "ayer"
    return f"dentro de {days} días" if days > 0 else f"hace {-days} días"


def date_text(entry: CalendarEntry) -> str:
    text = f"{entry.day:%d/%m/%Y}"
    if entry.day_end is not None:
        text += f" – {entry.day_end:%d/%m/%Y}"
    return text


def upcoming(data: Mapping[str, Fundamentals], today: date,
             days: int = UPCOMING_DAYS) -> list[CalendarEntry]:  # fmt: skip
    """Entries from today to ``days`` ahead (a window that already started counts), by date."""
    found = []
    for f in data.values():
        for entry in entries(f):
            last = entry.day_end or entry.day
            if last >= today and (entry.day - today).days <= days:
                found.append(entry)
    return sorted(found, key=lambda e: (e.day, e.symbol, e.kind))
