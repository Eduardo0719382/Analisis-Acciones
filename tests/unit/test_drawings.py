from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from analisis_acciones.models.errors import UserError
from analisis_acciones.services.drawing_service import (
    DrawingKind,
    DrawingService,
    Point,
    fib_levels,
)


@pytest.fixture
def service(conn: sqlite3.Connection) -> DrawingService:
    return DrawingService(conn)


def pt(day: str, price: float) -> dict[str, object]:
    return {"time": day, "price": price}


def test_fib_levels_by_hand() -> None:
    levels = dict(fib_levels(Point(date(2024, 1, 1), 200.0), Point(date(2024, 2, 1), 100.0)))
    assert levels[0.0] == 100.0 and levels[1.0] == 200.0
    assert levels[0.5] == 150.0
    assert levels[0.618] == pytest.approx(161.8)


def test_add_list_and_payload(service: DrawingService) -> None:
    hline = service.add("AAPL", "hline", [pt("2024-01-02", 150.5)])
    fib = service.add("AAPL", "fib", [pt("2024-01-02", 200), pt("2024-02-01", 100)])
    service.add("MSFT", "note", [pt("2024-01-03", 300)], "  Resultados   trimestrales ")
    drawings = service.drawings("AAPL")
    assert [d.kind for d in drawings] == [DrawingKind.HLINE, DrawingKind.FIB]
    assert hline.points[0].price == 150.5
    payload = fib.to_payload()
    assert len(payload["levels"]) == 7 and payload["points"][1]["time"] == "2024-02-01"
    assert service.drawings("MSFT")[0].text == "Resultados trimestrales"


@pytest.mark.parametrize(
    ("kind", "points"),
    [
        ("hline", []),
        ("trend", [pt("2024-01-02", 1)]),
        ("hline", [pt("2024-13-40", 1)]),
        ("hline", [pt("2024-01-02", -5)]),
        ("hline", [pt("2024-01-02", float("nan"))]),
        ("hline", ["junk"]),
        ("circle", [pt("2024-01-02", 1)]),
    ],
)
def test_untrusted_input_rejected(service: DrawingService, kind: str, points: list) -> None:  # type: ignore[type-arg]
    with pytest.raises(UserError):
        service.add("AAPL", kind, points)


def test_note_requires_text_and_is_truncated(service: DrawingService) -> None:
    with pytest.raises(UserError):
        service.add("AAPL", "note", [pt("2024-01-02", 1)], "   ")
    note = service.add("AAPL", "note", [pt("2024-01-02", 1)], "x" * 500)
    assert len(note.text) == 200


def test_undo_and_clear(service: DrawingService) -> None:
    service.add("AAPL", "hline", [pt("2024-01-02", 1)])
    service.add("AAPL", "hline", [pt("2024-01-02", 2)])
    service.add("MSFT", "hline", [pt("2024-01-02", 3)])
    assert service.delete_last("AAPL")
    assert [d.points[0].price for d in service.drawings("AAPL")] == [1.0]
    assert service.clear("AAPL") == 1
    assert service.drawings("AAPL") == []
    assert len(service.drawings("MSFT")) == 1
    assert not service.delete_last("AAPL")
