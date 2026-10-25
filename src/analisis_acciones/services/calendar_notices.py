"""Notices a few days before the earnings and ex-dividend dates of watched symbols.

Each date is announced once: the key ``SYMBOL|kind|date`` is remembered, so a
moved date is announced again (it is new information) and an unchanged one is
not repeated. Keys of past dates are dropped so the stored list stays small.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from analisis_acciones.models.market import Fundamentals
from analisis_acciones.services import company_calendar
from analisis_acciones.services.company_calendar import EARNINGS, EX_DIVIDEND, CalendarEntry
from analisis_acciones.services.daily_scan import Novelty

NOTICE_KINDS = (EARNINGS, EX_DIVIDEND)


def key_of(entry: CalendarEntry) -> str:
    return f"{entry.symbol}|{entry.kind}|{entry.day.isoformat()}"


def notice_text(entry: CalendarEntry, today: date) -> str:
    estimated = " (fecha estimada)" if entry.estimated else ""
    return (
        f"{entry.label}{estimated}: {company_calendar.date_text(entry)} · "
        f"{company_calendar.when(entry, today)}"
    )


def due_notices(data: Mapping[str, Fundamentals], today: date, days: int,
                notified: list[str]) -> tuple[list[Novelty], list[str]]:  # fmt: skip
    """New notices and the updated list of announced keys."""
    if days <= 0:
        return [], notified
    entries = [e for e in company_calendar.upcoming(data, today, days) if e.kind in NOTICE_KINDS]
    known = set(notified)
    notices = [
        Novelty(e.symbol, notice_text(e, today), 0, today, "calendar")
        for e in entries
        if key_of(e) not in known
    ]
    keep = [k for k in notified if _still_relevant(k, today)]
    keep += [key_of(e) for e in entries if key_of(e) not in known]
    return notices, keep


def _still_relevant(key: str, today: date) -> bool:
    try:
        return date.fromisoformat(key.rsplit("|", 1)[1]) >= today
    except (IndexError, ValueError):
        return False
