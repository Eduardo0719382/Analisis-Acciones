from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PySide6.QtCore import QDate
from pytestqt.qtbot import QtBot

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.paper_portfolio import PaperPortfolioService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.main_window import MainWindow
from analisis_acciones.ui.portfolio_dialog import PortfolioDialog
from tests.synthetic import FakeYahooClient, synthetic_daily

NOW = datetime(2024, 3, 30, 12, tzinfo=UTC)


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    client = FakeYahooClient(synthetic_daily(sessions=60))
    client.known = {"TEST", "SPY"}
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                                clock=lambda: NOW)  # fmt: skip
    yield service
    service.close()


@pytest.fixture
def service(market: MarketDataService) -> PaperPortfolioService:
    return PaperPortfolioService(open_database(":memory:"), market, clock=lambda: NOW)


def test_trade_report_delete_and_export(qtbot: QtBot, service: PaperPortfolioService,
                                        tmp_path: Path) -> None:  # fmt: skip
    dialog = PortfolioDialog(service, lambda: "SPY", "TEST")
    qtbot.addWidget(dialog)
    dialog.open_after_export = False
    qtbot.waitUntil(lambda: dialog.report is not None, timeout=10000)
    dialog.quantity.setValue(5)
    dialog.trade_date.setDate(QDate(2024, 2, 1))
    dialog.note.setText("primera")
    dialog.add_trade()
    qtbot.waitUntil(lambda: dialog.report is not None and len(dialog.report.trades) == 1,
                    timeout=10000)  # fmt: skip
    assert dialog.trades.rowCount() == 1 and dialog.trades.item(0, 7).text() == "primera"
    assert dialog.report.valuation.holdings[0].quantity == 5

    dialog.side.setCurrentIndex(dialog.side.findData("sell"))
    dialog.quantity.setValue(50)  # more than held: refused with a clear message
    dialog.add_trade()
    qtbot.waitUntil(lambda: "no se pueden vender" in dialog.status.text(), timeout=10000)

    dialog.export("html", tmp_path / "c")
    assert "Cartera simulada: Mi cartera" in (tmp_path / "c.html").read_text("utf-8")
    dialog.export("csv", tmp_path / "c.csv")
    assert "primera" in (tmp_path / "c.csv").read_text("utf-8-sig")

    dialog.trades.selectRow(0)
    dialog.delete_selected_trade()
    qtbot.waitUntil(lambda: dialog.report is not None and not dialog.report.trades,
                    timeout=10000)  # fmt: skip

    assert dialog.new_portfolio("Segunda", 2500)
    assert "Segunda" in dialog.portfolio.currentText()
    assert not dialog.new_portfolio("Segunda", 100)


def test_menu_opens_portfolio(qtbot: QtBot, settings: SettingsService, market: MarketDataService,
                              service: PaperPortfolioService) -> None:  # fmt: skip
    win = MainWindow(settings, market_service=market, portfolio_service=service)
    qtbot.addWidget(win)
    assert win.portfolio_action.isEnabled()
    win.portfolio_action.trigger()
    assert isinstance(win._portfolio_dialog, PortfolioDialog)
    plain = MainWindow(settings, market_service=market)
    qtbot.addWidget(plain)
    assert not plain.portfolio_action.isEnabled()
