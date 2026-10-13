from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.comparison_dialog import ComparisonDialog
from analisis_acciones.ui.theme import DARK
from tests.synthetic import FakeYahooClient


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    client = FakeYahooClient()
    client.known = {"AAA", "BBB"}
    fixed = datetime(2025, 3, 3, 23, 0, tzinfo=UTC)
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                                clock=lambda: fixed)  # fmt: skip
    yield service
    service.close()


def test_compare_two_assets_and_report_unknown(qtbot: QtBot, market: MarketDataService) -> None:
    dialog = ComparisonDialog(market, DARK, ["AAA", "bbb", "AAA", "ZZZ"])
    qtbot.addWidget(dialog)
    assert dialog.parsed_symbols() == ["AAA", "BBB", "ZZZ"]
    dialog.run()
    qtbot.waitUntil(lambda: dialog.comparison is not None, timeout=10000)
    assert dialog.comparison is not None
    assert list(dialog.comparison.performance.columns) == ["AAA", "BBB"]
    assert dialog.table.rowCount() == 2
    assert "ZZZ" in dialog.status.text()
    assert dialog.comparison.performance.iloc[0].tolist() == [0.0, 0.0]


def test_empty_input(qtbot: QtBot, market: MarketDataService) -> None:
    dialog = ComparisonDialog(market, DARK, [])
    qtbot.addWidget(dialog)
    dialog.run()
    assert "al menos un ticker" in dialog.status.text()
