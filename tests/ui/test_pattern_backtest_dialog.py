from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.main_window import MainWindow
from analisis_acciones.ui.pattern_backtest_dialog import PatternBacktestDialog
from tests.synthetic import FakeYahooClient, synthetic_daily


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    client = FakeYahooClient(synthetic_daily(sessions=900, seed=3))
    client.known = {"AAA"}
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                                clock=lambda: datetime(2027, 6, 1, tzinfo=UTC))  # fmt: skip
    yield service
    service.close()


def test_run_show_and_export(qtbot: QtBot, market: MarketDataService, tmp_path: Path) -> None:
    dialog = PatternBacktestDialog(market, ["AAA", "ZZZ"])
    qtbot.addWidget(dialog)
    dialog.open_after_export = False
    dialog.max_bars.setValue(30)
    dialog.pattern_boxes["Bandera alcista"].setChecked(False)
    config = dialog.config()
    assert config.max_bars == 30 and "Bandera alcista" not in config.patterns
    dialog.run()
    qtbot.waitUntil(lambda: dialog.outcome is not None, timeout=60000)
    assert dialog.outcome is not None
    assert dialog.trades.rowCount() == len(dialog.outcome.trades)
    assert "ZZZ" in dialog.status.text()
    assert all(t.pattern != "Bandera alcista" for t in dialog.outcome.trades)

    dialog.export("html", tmp_path / "r.html")
    assert "Backtesting de patrones chartistas" in (tmp_path / "r.html").read_text("utf-8")
    dialog.export("csv", tmp_path / "r")
    assert (tmp_path / "r.csv").read_bytes().startswith(b"\xef\xbb\xbfticker,patron")
    dialog.export("pdf", tmp_path / "r.pdf")
    qtbot.waitUntil(lambda: dialog.last_export == tmp_path / "r.pdf", timeout=30000)
    assert (tmp_path / "r.pdf").read_bytes().startswith(b"%PDF")


def test_menu_opens_dialog(qtbot: QtBot, settings: SettingsService,
                           market: MarketDataService) -> None:  # fmt: skip
    win = MainWindow(settings, market_service=market)
    qtbot.addWidget(win)
    win.pattern_backtest_action.trigger()
    assert isinstance(win._pattern_backtest_dialog, PatternBacktestDialog)
