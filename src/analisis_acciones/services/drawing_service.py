"""Chart drawings (horizontal lines, trend lines, Fibonacci retracements, notes).

Coordinates arriving from the chart page are untrusted: they are validated
here (kind, number of points, dates, finite positive prices, text length)
before anything is stored.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from analisis_acciones.models.errors import UserError

logger = logging.getLogger(__name__)

#: Standard retracement ratios (0 % = second point, 100 % = first point).
FIB_RATIOS = (0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0)
MAX_TEXT = 200
MAX_PER_SYMBOL = 200


class DrawingKind(StrEnum):
    HLINE = "hline"
    TREND = "trend"
    FIB = "fib"
    NOTE = "note"


POINTS_REQUIRED = {
    DrawingKind.HLINE: 1,
    DrawingKind.TREND: 2,
    DrawingKind.FIB: 2,
    DrawingKind.NOTE: 1,
}


@dataclass(frozen=True)
class Point:
    time: date
    price: float


@dataclass(frozen=True)
class Drawing:
    id: int
    symbol: str
    kind: DrawingKind
    points: tuple[Point, ...]
    text: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind.value,
            "points": [{"time": p.time.isoformat(), "price": p.price} for p in self.points],
            "text": self.text,
        }
        if self.kind is DrawingKind.FIB:
            payload["levels"] = [
                {"ratio": r, "price": price} for r, price in fib_levels(*self.points)
            ]
        return payload


def fib_levels(start: Point, end: Point) -> list[tuple[float, float]]:
    """Retracement prices between ``start`` (100 %) and ``end`` (0 %)."""
    span = start.price - end.price
    return [(ratio, end.price + span * ratio) for ratio in FIB_RATIOS]


def _invalid(detail: str) -> UserError:
    return UserError(f"invalid drawing: {detail}", user_message="El dibujo no es válido.")


def parse_points(kind: DrawingKind, raw: Any) -> tuple[Point, ...]:
    if not isinstance(raw, list) or len(raw) != POINTS_REQUIRED[kind]:
        raise _invalid(f"{kind} needs {POINTS_REQUIRED[kind]} point(s)")
    points = []
    for item in raw:
        if not isinstance(item, dict):
            raise _invalid("point is not an object")
        try:
            day = date.fromisoformat(str(item.get("time")))
            price = float(item.get("price"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise _invalid(f"bad point {item!r}") from None
        if not math.isfinite(price) or price <= 0:
            raise _invalid(f"bad price {price}")
        points.append(Point(day, price))
    return tuple(points)


class DrawingService:
    def __init__(
        self, conn: sqlite3.Connection, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._conn = conn
        self._clock = clock

    def drawings(self, symbol: str) -> list[Drawing]:
        rows = self._conn.execute(
            "SELECT id, symbol, kind, data FROM drawings WHERE symbol = ? ORDER BY id", (symbol,)
        ).fetchall()
        result = []
        for row in rows:
            try:
                kind = DrawingKind(row["kind"])
                data = json.loads(row["data"])
                points = parse_points(kind, data.get("points"))
                text = str(data.get("text") or "")[:MAX_TEXT]
            except (ValueError, UserError, AttributeError, json.JSONDecodeError):
                logger.warning("Skipping invalid stored drawing %s", row["id"])
                continue
            result.append(Drawing(row["id"], row["symbol"], kind, points, text))
        return result

    def add(self, symbol: str, kind: str, raw_points: Any, text: str = "") -> Drawing:
        try:
            drawing_kind = DrawingKind(kind)
        except ValueError:
            raise _invalid(f"unknown kind {kind!r}") from None
        points = parse_points(drawing_kind, raw_points)
        clean_text = " ".join(str(text).split())[:MAX_TEXT]
        if drawing_kind is DrawingKind.NOTE and not clean_text:
            raise UserError("empty note", user_message="La nota no puede estar vacía.")
        if len(self.drawings(symbol)) >= MAX_PER_SYMBOL:
            raise UserError(
                "too many drawings",
                user_message=f"Máximo {MAX_PER_SYMBOL} dibujos por activo.",
            )
        data = {"points": [{"time": p.time.isoformat(), "price": p.price} for p in points],
                "text": clean_text}  # fmt: skip
        cursor = self._conn.execute(
            "INSERT INTO drawings (symbol, kind, data, created_at) VALUES (?, ?, ?, ?)",
            (symbol, drawing_kind.value, json.dumps(data), self._clock().isoformat()),
        )
        return Drawing(int(cursor.lastrowid or 0), symbol, drawing_kind, points, clean_text)

    def delete_last(self, symbol: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM drawings WHERE id = (SELECT MAX(id) FROM drawings WHERE symbol = ?)",
            (symbol,),
        )
        return cursor.rowcount > 0

    def clear(self, symbol: str) -> int:
        cursor = self._conn.execute("DELETE FROM drawings WHERE symbol = ?", (symbol,))
        return cursor.rowcount
