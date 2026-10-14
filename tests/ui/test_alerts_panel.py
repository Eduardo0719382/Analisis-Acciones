from __future__ import annotations

from collections.abc import Iterator

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.alerts.rules import AlertKind
from analisis_acciones.alerts.service import AlertService
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui import strings
from analisis_acciones.ui.alerts_panel import AlertsPanel, NewAlertDialog
from analisis_acciones.ui.main_window import MainWindow
from tests.alerts.test_service import Clock
from tests.analysis.test_rules import make_bars
from tests.synthetic import FakeYahooClient


@pytest.fixture
def services() -> Iterator[tuple[MarketDataService, AlertService]]:
    client = FakeYahooClient(make_bars(np.linspace(100, 110, 55)))
    clock = Clock()
    market = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"), clock)
    alerts = AlertService(open_database(":memory:"), market, clock)
    yield market, alerts
    alerts.close()
    market.close()


def test_new_alert_dialog_validates_and_creates(
    qtbot: QtBot, services: tuple[MarketDataService, AlertService]
) -> None:
    _, alerts = services
    dialog = NewAlertDialog(alerts, "test")
    qtbot.addWidget(dialog)
    dialog.kind.setCurrentIndex(dialog.kind.findData(AlertKind.EMA_CROSS_UP.value))
    assert set(dialog.editors) == {"fast", "slow"}
    dialog.editors["fast"].setValue(60)
    assert "rápida" in dialog.preview.text()
    dialog.accept()
    assert "rápida" in dialog.error.text() and alerts.alerts() == []
    dialog.editors["fast"].setValue(10)
    dialog.accept()
    assert [a.description for a in alerts.alerts()] == ["TEST: EMA 10 cruza por encima de EMA 50"]


def test_panel_check_toggle_delete(
    qtbot: QtBot, services: tuple[MarketDataService, AlertService]
) -> None:
    _, alerts = services
    alerts.create("TEST", AlertKind.PRICE_ABOVE, {"value": 105})
    panel = AlertsPanel(alerts)
    qtbot.addWidget(panel)
    assert panel.table.rowCount() == 1
    with qtbot.waitSignal(panel.alerts_triggered, timeout=10000) as blocker:
        panel.check_now()
    assert len(blocker.args[0]) == 1
    assert "Cierre > 105.00" in panel.history.item(0).text()
    assert panel.table.item(0, 2).text() != "—"  # type: ignore[union-attr]

    panel.table.selectRow(0)
    panel.toggle_selected()
    assert panel.table.item(0, 1).text() == strings.ALERT_PAUSED  # type: ignore[union-attr]
    panel.table.selectRow(0)
    panel.delete_selected()
    assert panel.table.rowCount() == 0


def test_main_window_notifies(
    qtbot: QtBot, settings: SettingsService, services: tuple[MarketDataService, AlertService]
) -> None:
    market, alerts = services
    alerts.create("TEST", AlertKind.PRICE_ABOVE, {"value": 105})
    window = MainWindow(settings, market_service=market, alert_service=alerts)
    qtbot.addWidget(window)
    assert window.alerts_panel is not None
    assert window.right_tabs.tabText(window.right_tabs.indexOf(window.alerts_panel)) == (
        strings.TAB_ALERTS
    )
    with qtbot.waitSignal(window.alerts_panel.alerts_triggered, timeout=10000):
        window.alerts_panel.check_now()
    assert "Cierre > 105.00" in window.statusBar().currentMessage()


def test_dialog_interval_and_fast_schedule(
    qtbot: QtBot, services: tuple[MarketDataService, AlertService]
) -> None:
    from analisis_acciones.ui.alerts_panel import (
        CHECK_INTERVAL_MS,
        INTRADAY_CHECK_INTERVAL_MS,
        AlertsPanel,
        NewAlertDialog,
    )

    _market, alerts = services
    panel = AlertsPanel(alerts)
    qtbot.addWidget(panel)
    assert panel.timer.interval() == CHECK_INTERVAL_MS
    dialog = NewAlertDialog(alerts, "TEST")
    qtbot.addWidget(dialog)
    dialog.interval.setCurrentIndex(dialog.interval.findData("15m"))
    dialog.kind.setCurrentIndex(dialog.kind.findData("price_below"))
    dialog.accept()
    assert dialog.created.interval == "15m"
    panel.reload()
    assert panel.timer.interval() == INTRADAY_CHECK_INTERVAL_MS
    assert "(15 min)" in panel.table.item(0, 0).text()
