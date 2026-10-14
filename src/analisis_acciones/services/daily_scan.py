"""Daily automatic scan: what is new since the previous session's scan.

The scan is "due" once per completed US session: when the last session close
(see ``data.freshness``) is newer than the session of the stored snapshot.
Each scan stores, per symbol, the notable items found (signals and chart
patterns). The next scan reports items that were not there before.

A symbol seen for the first time only sets a baseline: reporting every
existing signal as "new" would flood the user on the first run or after
adding symbols to the watchlist.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from analisis_acciones.data.freshness import last_session_close
from analisis_acciones.services.scanner import BREAKOUT_NOTE, ScanResult, ScanRow


@dataclass(frozen=True)
class Novelty:
    symbol: str
    text: str
    bias: int  # +1 bullish, -1 bearish, 0 neutral/undecided
    bar_date: date | None


def session_of(now: datetime) -> date:
    """New York date of the latest completed session at ``now``."""
    return last_session_close(now).date()


def is_due(now: datetime, snapshot: dict[str, Any] | None) -> bool:
    if not snapshot or not isinstance(snapshot.get("session"), str):
        return True
    return str(snapshot["session"]) < session_of(now).isoformat()


def notable_items(row: ScanRow) -> dict[str, int]:
    """Item text -> bias. Patterns keep their state so a breakout is new after 'forming'."""
    items = {f"Señal alcista: {t}": 1 for t in row.bullish}
    items.update({f"Señal bajista: {t}": -1 for t in row.bearish})
    for note in row.pattern_notes:
        state = "ruptura" if note.state == BREAKOUT_NOTE else "en formación"
        items[f"Patrón {note.name} ({state})"] = note.bias
    return items


def find_novelties(previous: dict[str, list[str]], result: ScanResult) -> list[Novelty]:
    novelties = []
    for row in result.rows:
        if row.symbol not in previous:
            continue  # first time: baseline only
        known = set(previous[row.symbol])
        for text, bias in notable_items(row).items():
            if text not in known:
                novelties.append(Novelty(row.symbol, text, bias, row.as_of))
    return novelties


def make_snapshot(result: ScanResult, session: date,
                  previous: dict[str, list[str]] | None = None) -> dict[str, Any]:  # fmt: skip
    """Snapshot for the next comparison. Symbols that failed this time keep their old items."""
    items = dict(previous or {})
    for row in result.rows:
        items[row.symbol] = sorted(notable_items(row))
    return {"session": session.isoformat(), "items": items}


def previous_items(snapshot: dict[str, Any] | None) -> dict[str, list[str]]:
    """Stored items, ignoring anything malformed (settings are local data, still validated)."""
    raw = snapshot.get("items") if isinstance(snapshot, dict) else None
    if not isinstance(raw, dict):
        return {}
    return {
        str(symbol): [str(i) for i in values]
        for symbol, values in raw.items()
        if isinstance(values, list)
    }
