"""Projection tab: worker run -> text with calibration -> overlay on the chart."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    fixed = datetime(2025, 3, 3, 23, 0, tzinfo=UTC)
    client = FakeYahooClient()
    client.known = {"TEST", "OTHER"}
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                                clock=lambda: fixed)  # fmt: skip
    yield service
    service.close()


@pytest.fixture
def window(qtbot: QtBot, settings: SettingsService, market: MarketDataService) -> MainWindow:
    win = MainWindow(settings, market_service=market)
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


def test_projection_drawn_and_cleared(qtbot: QtBot, window: MainWindow) -> None:
    panel = window.projection_panel
    panel.horizon.setValue(10)
    panel.lookback.setValue(60)
    with qtbot.waitSignal(panel.projection_ready, timeout=20000):
        panel.run()
    assert panel.outcome is not None
    assert panel.outcome.projection.horizon == 10
    assert panel.outcome.calibration is not None
    assert "P95" in panel.result.text()
    qtbot.waitUntil(lambda: state(qtbot, window)["overlayGroups"].get("projection") == 5,
                    timeout=10000)  # fmt: skip

    panel.show_on_chart.setChecked(False)
    qtbot.waitUntil(lambda: not state(qtbot, window)["overlayGroups"].get("projection"),
                    timeout=10000)  # fmt: skip
    panel.show_on_chart.setChecked(True)
    qtbot.waitUntil(lambda: state(qtbot, window)["overlayGroups"].get("projection") == 5,
                    timeout=10000)  # fmt: skip

    # New data invalidates the result and removes the fan.
    assert window.market is not None
    with qtbot.waitSignal(window.market.load_finished, timeout=5000):
        window.open_symbol("OTHER")
    qtbot.waitUntil(lambda: panel.outcome is None, timeout=5000)
    qtbot.waitUntil(lambda: not state(qtbot, window)["overlayGroups"].get("projection"),
                    timeout=10000)  # fmt: skip


def test_regression_method_changes_lookback(qtbot: QtBot, window: MainWindow) -> None:
    panel = window.projection_panel
    panel.method.setCurrentIndex(panel.method.findData("regression"))
    assert panel.lookback.value() == 120
    with qtbot.waitSignal(panel.projection_ready, timeout=20000):
        panel.run()
    assert panel.outcome is not None and panel.outcome.projection.method == "regression"
