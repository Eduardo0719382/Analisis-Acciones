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
    assert dialog.trades.rowCount() == 1 and dialog.trades.item(0, 8).text() == "primera"
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


def test_dollars_commission_and_journal(qtbot: QtBot, service: PaperPortfolioService) -> None:
    dialog = PortfolioDialog(service, lambda: "SPY", "TEST")
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.report is not None, timeout=10000)
    assert dialog.commission_auto.isChecked() and not dialog.commission.isEnabled()
    dialog.set_costs(2.5, 0, 0, True, 15, 19)
    qtbot.waitUntil(lambda: "2,50 $" in dialog.costs_label.text(), timeout=10000)
    stored = service.portfolios()[0]
    assert (stored.dividend_withholding_pct, stored.capital_gains_tax_pct) == (15, 19)
    dialog.set_costs(2.5, 0, 0, True)  # taxes unchanged when not given
    assert service.portfolios()[0].capital_gains_tax_pct == 19

    dialog.mode.setCurrentIndex(dialog.mode.findData("dollars"))
    assert dialog.quantity_label.text() == "Importe ($)"
    dialog.quantity.setValue(500)
    dialog.price.setValue(80)
    dialog.trade_date.setDate(QDate(2024, 2, 1))
    dialog.note.setText("rotura de resistencia")
    dialog.add_trade()
    qtbot.waitUntil(lambda: dialog.report is not None and len(dialog.report.trades) == 1,
                    timeout=10000)  # fmt: skip
    trade = dialog.report.trades[0]
    assert trade.quantity == pytest.approx(6.25) and trade.commission == 2.5
    assert dialog.trades.item(0, 3).text() == "6,25"

    dialog.commission_auto.setChecked(False)
    dialog.commission.setValue(0.75)
    dialog.mode.setCurrentIndex(dialog.mode.findData("shares"))
    dialog.quantity.setValue(0.5)
    dialog.add_trade()
    qtbot.waitUntil(lambda: dialog.report is not None and len(dialog.report.trades) == 2,
                    timeout=10000)  # fmt: skip
    assert dialog.report.trades[1].commission == 0.75

    dialog.set_review(trade.id or 0, "Salió bien")
    qtbot.waitUntil(lambda: dialog.trades.item(1, 9) is not None
                    and dialog.trades.item(1, 9).text() == "Salió bien", timeout=10000)  # fmt: skip


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


def test_rebalance_tab(qtbot: QtBot, service: PaperPortfolioService) -> None:
    dialog = PortfolioDialog(service, lambda: "SPY", "TEST")
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.report is not None, timeout=10000)
    panel = dialog.rebalance
    assert "Defina primero" in panel.summary.text() or panel.plan is None
    panel.add_target_row("TEST", 60)
    panel.add_target_row("SPY")
    panel.targets.item(1, 1).setText("abc")
    panel.save_targets()
    assert "no es un número" in panel.summary.text()
    panel.targets.item(1, 1).setText("30,5")
    assert "90,5 %" in panel.total_label.text()
    panel.save_targets()
    assert service.targets(dialog.portfolio_id) == {"TEST": 60.0, "SPY": 30.5}
    qtbot.waitUntil(lambda: panel.plan is not None and len(panel.plan.orders) == 2,
                    timeout=10000)  # fmt: skip
    assert panel.apply_button.isEnabled()
    panel.apply()
    qtbot.waitUntil(lambda: dialog.report is not None and len(dialog.report.trades) == 2,
                    timeout=10000)  # fmt: skip
    weights = {h.symbol: h.weight_pct for h in dialog.report.valuation.holdings}
    assert weights["TEST"] == pytest.approx(60, abs=0.01)
    assert weights["SPY"] == pytest.approx(30.5, abs=0.01)
    assert dialog.report.trades[0].note == "Rebalanceo hacia los pesos objetivo"
    qtbot.waitUntil(lambda: panel.plan is not None and not panel.plan.orders, timeout=10000)
    assert "ya está en sus pesos" in panel.summary.text()
