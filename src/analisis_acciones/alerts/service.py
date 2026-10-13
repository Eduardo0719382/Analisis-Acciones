"""Alert persistence and checking (independent of the UI)."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from analisis_acciones.alerts.rules import (
    ALERT_SPECS,
    AlertKind,
    AlertRule,
    evaluate,
    validate_alert_params,
)
from analisis_acciones.models.errors import AppError, InternalError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.providers.base import normalize_symbol
from analisis_acciones.services.market_data_service import (
    CSV_PREFIX,
    MarketDataService,
    is_csv_symbol,
)
from analisis_acciones.storage.database import transaction

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AlertEvent:
    alert_id: int | None
    symbol: str
    description: str
    message: str
    bar_date: date
    triggered_at: datetime


@dataclass(frozen=True)
class CheckSummary:
    events: tuple[AlertEvent, ...]
    checked: int
    #: Per-symbol or per-alert problems (no data, no connection, ...).
    problems: tuple[str, ...]


class AlertService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        market: MarketDataService,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._conn = conn
        self._market = market
        self._clock = clock
        self._lock = threading.RLock()
        self._closed = False

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self._closed:
                raise InternalError(
                    "alert service closed", user_message="La aplicación se está cerrando."
                )
            yield self._conn

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._conn.close()

    # CRUD --------------------------------------------------------------------
    def create(self, symbol: str, kind: AlertKind | str, params: dict[str, Any]) -> AlertRule:
        kind = AlertKind(kind)
        if is_csv_symbol(symbol):
            clean = CSV_PREFIX + symbol.strip()[len(CSV_PREFIX) :].upper()
        else:
            clean = normalize_symbol(symbol)
        created = self._clock()
        rule = AlertRule(clean, kind, validate_alert_params(kind, params), created_at=created)
        with self._db() as db:
            cursor = db.execute(
                "INSERT INTO alerts (symbol, kind, params, enabled, armed, created_at) "
                "VALUES (?, ?, ?, 1, 1, ?)",
                (
                    rule.symbol,
                    rule.kind.value,
                    json.dumps(rule.params),
                    created.isoformat(),
                ),
            )
        rule.id = int(cursor.lastrowid or 0)
        return rule

    def alerts(self) -> list[AlertRule]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM alerts ORDER BY symbol, id").fetchall()
        rules = []
        for row in rows:
            try:
                kind = AlertKind(row["kind"])
                params = validate_alert_params(kind, json.loads(row["params"]))
            except (ValueError, AppError, json.JSONDecodeError):
                logger.warning("Skipping invalid stored alert %s", row["id"])
                continue
            rules.append(AlertRule(
                symbol=row["symbol"], kind=kind, params=params, enabled=bool(row["enabled"]),
                armed=bool(row["armed"]),
                last_bar=date.fromisoformat(row["last_bar"]) if row["last_bar"] else None,
                last_triggered_at=datetime.fromisoformat(row["last_triggered_at"])
                if row["last_triggered_at"] else None,
                created_at=datetime.fromisoformat(row["created_at"]), id=row["id"],
            ))  # fmt: skip
        return rules

    def delete(self, alert_id: int) -> None:
        with self._db() as db:
            db.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))

    def set_enabled(self, alert_id: int, enabled: bool) -> None:
        with self._db() as db:
            # Re-enabling re-arms level alerts so a still-true condition is reported again.
            db.execute(
                "UPDATE alerts SET enabled = ?, armed = CASE WHEN ? THEN 1 ELSE armed END "
                "WHERE id = ?",
                (int(enabled), int(enabled), alert_id),
            )

    def events(self, limit: int = 100) -> list[AlertEvent]:
        with self._db() as db:
            rows = db.execute(
                "SELECT * FROM alert_events ORDER BY triggered_at DESC, id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            AlertEvent(r["alert_id"], r["symbol"], r["description"], r["message"],
                       date.fromisoformat(r["bar_date"]),
                       datetime.fromisoformat(r["triggered_at"]))
            for r in rows
        ]  # fmt: skip

    def clear_events(self) -> None:
        with self._db() as db:
            db.execute("DELETE FROM alert_events")

    # Checking ----------------------------------------------------------------
    def check_all(self) -> CheckSummary:
        """Evaluate every enabled alert on completed daily bars. Never raises for data issues."""
        rules = [r for r in self.alerts() if r.enabled]
        by_symbol: dict[str, list[AlertRule]] = {}
        for rule in rules:
            by_symbol.setdefault(rule.symbol, []).append(rule)

        events: list[AlertEvent] = []
        problems: list[str] = []
        now = self._clock()
        for symbol, symbol_rules in by_symbol.items():
            try:
                result = self._market.load(symbol, Interval.D1)
            except AppError as exc:
                problems.append(f"{symbol}: {exc.user_message}")
                continue
            bars = result.series.bars
            if result.session_in_progress:
                bars = bars.iloc[:-1]  # only completed sessions can trigger alerts
            if result.stale:
                problems.append(f"{symbol}: datos guardados sin actualizar (sin conexión)")
            for rule in symbol_rules:
                try:
                    outcome = evaluate(rule, bars)
                except (ValueError, ArithmeticError, KeyError) as exc:
                    logger.exception("Alert %s failed", rule.id)
                    problems.append(f"{rule.description}: no se pudo evaluar ({exc})")
                    continue
                if outcome.skipped:
                    problems.append(f"{rule.description}: {outcome.skipped}")
                event = None
                if outcome.fired and outcome.check is not None:
                    check = outcome.check
                    event = AlertEvent(
                        rule.id, rule.symbol, rule.description, check.message, check.bar_date, now
                    )
                    events.append(event)
                self._save_state(rule, event)
        return CheckSummary(tuple(events), len(rules), tuple(problems))

    def _save_state(self, rule: AlertRule, event: AlertEvent | None) -> None:
        with self._db() as db, transaction(db):
            db.execute(
                "UPDATE alerts SET armed = ?, last_bar = ?, "
                "last_triggered_at = COALESCE(?, last_triggered_at) WHERE id = ?",
                (int(rule.armed), rule.last_bar.isoformat() if rule.last_bar else None,
                 event.triggered_at.isoformat() if event else None, rule.id),
            )  # fmt: skip
            if event is not None:
                db.execute(
                    "INSERT INTO alert_events (alert_id, symbol, description, message, bar_date, "
                    "triggered_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (event.alert_id, event.symbol, event.description, event.message,
                     event.bar_date.isoformat(), event.triggered_at.isoformat()),
                )  # fmt: skip


def kind_choices() -> list[tuple[str, str]]:
    """(kind value, generic label) for the UI."""
    labels = {
        AlertKind.PRICE_ABOVE: "Precio por encima de…",
        AlertKind.PRICE_BELOW: "Precio por debajo de…",
        AlertKind.CHANGE_ABOVE: "Cambio diario mayor que… %",
        AlertKind.CHANGE_BELOW: "Cambio diario menor que… %",
        AlertKind.RSI_ABOVE: "RSI por encima de…",
        AlertKind.RSI_BELOW: "RSI por debajo de…",
        AlertKind.EMA_CROSS_UP: "Cruce alcista de EMAs",
        AlertKind.EMA_CROSS_DOWN: "Cruce bajista de EMAs",
        AlertKind.MACD_CROSS_UP: "Cruce alcista MACD/señal",
        AlertKind.MACD_CROSS_DOWN: "Cruce bajista MACD/señal",
        AlertKind.BREAKOUT_HIGH: "Ruptura de máximo de N barras",
        AlertKind.BREAKDOWN_LOW: "Ruptura de mínimo de N barras",
    }
    return [(k.value, labels[k]) for k in ALERT_SPECS]


__all__ = ["AlertEvent", "AlertService", "CheckSummary", "UserError", "kind_choices"]
