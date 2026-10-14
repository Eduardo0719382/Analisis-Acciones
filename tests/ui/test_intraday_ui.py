"""Intraday interval end to end: hours on the time axis, tools work, drawings disabled."""

from __future__ import annotations

import json
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
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    service = MarketDataService(YahooFinanceProvider(FakeYahooClient()), open_database(":memory:"),
                                clock=lambda: datetime.now(UTC))  # fmt: skip
    yield service
    service.close()


def state(qtbot: QtBot, win: MainWindow) -> dict[str, Any]:
    out: list[str] = []
    win.chart.evaluate("JSON.stringify(window.chartApp.state())", out.append)
    qtbot.waitUntil(lambda: bool(out), timeout=10000)
    return json.loads(out[0])  # type: ignore[no-any-return]


def test_hourly_chart(qtbot: QtBot, settings: SettingsService, market: MarketDataService,
                      conn: object) -> None:  # fmt: skip
    win = MainWindow(settings, market_service=market,
                     drawing_service=DrawingService(conn))  # type: ignore[arg-type]  # fmt: skip
    qtbot.addWidget(win)
    win.show()
    assert win.market is not None
    with qtbot.waitSignal(win.market.load_finished, timeout=5000):
        win.open_symbol("TEST")
    assert win.draw_button.isEnabled()
    with qtbot.waitSignal(win.market.load_finished, timeout=10000) as blocker:
        win.timeframe_combo.setCurrentIndex(win.timeframe_combo.findData("1h"))
    assert blocker.args[0].series.interval.value == "1h"
    qtbot.waitUntil(lambda: win.chart.is_loaded, timeout=20000)
    qtbot.waitUntil(lambda: state(qtbot, win)["intraday"], timeout=10000)
    assert state(qtbot, win)["timeVisible"] is True
    assert not win.draw_button.isEnabled()

    # Tools run on the hourly bars; dates in the panels include the time.
    panel = win.patterns_panel
    panel.run()
    qtbot.waitUntil(lambda: panel.result is not None, timeout=10000)
    projection = win.projection_panel
    projection.lookback.setValue(60)
    with qtbot.waitSignal(projection.projection_ready, timeout=20000):
        projection.run()
    qtbot.waitUntil(lambda: state(qtbot, win)["overlayGroups"].get("projection") == 5,
                    timeout=10000)  # fmt: skip

    with qtbot.waitSignal(win.market.load_finished, timeout=10000):
        win.timeframe_combo.setCurrentIndex(win.timeframe_combo.findData("1D"))
    qtbot.waitUntil(lambda: not state(qtbot, win)["intraday"], timeout=10000)
    assert win.draw_button.isEnabled()
