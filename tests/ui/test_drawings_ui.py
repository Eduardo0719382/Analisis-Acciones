"""Drawing tools end to end: page click (simulated) -> bridge -> validation -> DB -> page."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.drawing_service import DrawingService
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui import strings
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    fixed = datetime(2025, 3, 3, 23, 0, tzinfo=UTC)
    service = MarketDataService(YahooFinanceProvider(FakeYahooClient()), open_database(":memory:"),
                                clock=lambda: fixed)  # fmt: skip
    yield service
    service.close()


@pytest.fixture
def drawings(conn: sqlite3.Connection) -> DrawingService:
    return DrawingService(conn)


@pytest.fixture
def window(qtbot: QtBot, settings: SettingsService, market: MarketDataService,
           drawings: DrawingService) -> MainWindow:  # fmt: skip
    win = MainWindow(settings, market_service=market, drawing_service=drawings)
    qtbot.addWidget(win)
    win.show()
    assert win.market is not None
    with qtbot.waitSignal(win.market.load_finished, timeout=5000):
        win.open_symbol("TEST")
    qtbot.waitUntil(lambda: win.chart.is_loaded, timeout=20000)
    return win


def state(qtbot: QtBot, win: MainWindow) -> dict[str, Any]:
    out: list[str] = []
    win.chart.evaluate("JSON.stringify(window.chartApp.state())", out.append)
    qtbot.waitUntil(lambda: bool(out), timeout=10000)
    return json.loads(out[0])  # type: ignore[no-any-return]


def click(win: MainWindow, day: str, price: float) -> None:
    win.chart.evaluate(f"window.chartApp.simulateDrawClick({json.dumps(day)}, {price})",
                       lambda _r: None)  # fmt: skip


def test_bridge_connected(qtbot: QtBot, window: MainWindow) -> None:
    qtbot.waitUntil(lambda: state(qtbot, window)["bridge"], timeout=10000)


def test_hline_trend_fib_created_and_persisted(
    qtbot: QtBot, window: MainWindow, drawings: DrawingService
) -> None:
    qtbot.waitUntil(lambda: state(qtbot, window)["bridge"], timeout=10000)
    window.draw_actions["hline"].trigger()
    assert state(qtbot, window)["drawMode"] == "hline"
    with qtbot.waitSignal(window.chart.bridge.drawing_created, timeout=10000):
        click(window, "2024-05-01", 95.5)
    window.start_drawing("trend")
    click(window, "2024-03-01", 90.0)
    with qtbot.waitSignal(window.chart.bridge.drawing_created, timeout=10000):
        click(window, "2024-06-03", 110.0)
    window.start_drawing("fib")
    click(window, "2024-02-01", 120.0)
    with qtbot.waitSignal(window.chart.bridge.drawing_created, timeout=10000):
        click(window, "2024-04-01", 80.0)

    stored = drawings.drawings("TEST")
    assert [d.kind.value for d in stored] == ["hline", "trend", "fib"]
    assert stored[0].points[0].price == 95.5
    # 1 horizontal line + 7 Fibonacci levels as price lines; the trend line is a series.
    qtbot.waitUntil(lambda: state(qtbot, window)["drawingLines"] == 8, timeout=10000)
    assert state(qtbot, window)["drawingSeries"] == 1

    window.undo_drawing()
    qtbot.waitUntil(lambda: state(qtbot, window)["drawingLines"] == 1, timeout=10000)
    window.clear_drawings()
    qtbot.waitUntil(lambda: state(qtbot, window)["drawings"] == 0, timeout=10000)
    assert drawings.drawings("TEST") == []


def test_note_uses_text_and_invalid_points_rejected(
    qtbot: QtBot, window: MainWindow, drawings: DrawingService
) -> None:
    window._on_drawing_created("note", [{"time": "2024-05-01", "price": 95.0}], "Ex-dividendo")
    assert drawings.drawings("TEST")[0].text == "Ex-dividendo"
    # Malformed data coming from the page is rejected with a message, never stored.
    window._on_drawing_created("trend", [{"time": "2024-05-01", "price": -1}], None)
    assert len(drawings.drawings("TEST")) == 1
    assert window.statusBar().currentMessage() == "El dibujo no es válido."


def test_drawing_needs_open_symbol(qtbot: QtBot, settings: SettingsService,
                                   drawings: DrawingService) -> None:  # fmt: skip
    win = MainWindow(settings, drawing_service=drawings)
    qtbot.addWidget(win)
    win.start_drawing("hline")
    assert win.statusBar().currentMessage() == strings.DRAW_NEED_SYMBOL
