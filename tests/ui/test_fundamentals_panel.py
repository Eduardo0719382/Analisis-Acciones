from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient
from tests.unit.test_fundamentals import INFO, statement


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    client = FakeYahooClient()
    client.info_payload = dict(INFO)
    client.statement = statement()
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                                clock=lambda: datetime(2025, 3, 7, 22, tzinfo=UTC))  # fmt: skip
    yield service
    service.close()


def test_fundamentals_tab_loads_only_when_shown(qtbot: QtBot, settings: SettingsService,
                                                market: MarketDataService) -> None:  # fmt: skip
    win = MainWindow(settings, market_service=market)
    qtbot.addWidget(win)
    assert win.market is not None
    with qtbot.waitSignal(win.market.load_finished, timeout=5000):
        win.open_symbol("TEST")
    panel = win.fundamentals_panel
    assert panel.result is None  # not fetched while another tab is shown
    win.right_tabs.setCurrentWidget(panel)
    qtbot.waitUntil(lambda: panel.result is not None, timeout=10000)
    assert "PER (últimos 12 meses)" in panel.html and "Beneficio neto por año" in panel.html
    panel.set_symbol("CSV:MINE")
    assert "CSV" in panel.message.text()
