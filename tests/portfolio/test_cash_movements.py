from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pandas as pd
import pytest
from PySide6.QtCore import QDate
from pytestqt.qtbot import QtBot

from analisis_acciones.models.errors import UserError
from analisis_acciones.portfolio.engine import (
    BUY,
    CASH_DIVIDEND,
    DEPOSIT,
    FEE,
    INTEREST,
    WITHDRAWAL,
    CashMovement,
    PaperTrade,
    daily_values,
    flows_by_day,
    replay,
    time_weighted,
    value,
    with_flows,
)
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.paper_portfolio import PaperPortfolioService
from analisis_acciones.services.portfolio_report import portfolio_html
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.portfolio_dialog import PortfolioDialog
from tests.synthetic import FakeYahooClient, synthetic_daily

D1, D2, D3 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4)


def test_order_and_cash_checks() -> None:
    # The deposit arrives the same day as the purchase it pays for (inflows go first) ...
    trades = [PaperTrade("A", BUY, 10, 100, D2, 0)]
    state = replay(trades, 100, movements=[CashMovement(D2, DEPOSIT, 1000)])
    assert state.cash == pytest.approx(100) and state.contributions == 1000
    # ... and a withdrawal is applied after the day's trades.
    with pytest.raises(UserError) as exc:
        replay(trades, 1000, movements=[CashMovement(D2, WITHDRAWAL, 50)])
    assert "retirar" in exc.value.user_message
    rich = replay([], 1000, movements=[
        CashMovement(D1, WITHDRAWAL, 200), CashMovement(D2, CASH_DIVIDEND, 30, "A"),
        CashMovement(D2, INTEREST, 5), CashMovement(D3, FEE, 10)])  # fmt: skip
    assert rich.cash == pytest.approx(825) and rich.contributions == -200
    assert rich.dividends == 30 and rich.interest == 5 and rich.other_fees == 10
    val = value(rich, 1000, {})
    assert val.invested == 800 and val.result == pytest.approx(25)
    assert val.total_return_pct == pytest.approx(25 / 800 * 100)


def test_time_weighted_return_ignores_deposits() -> None:
    days = pd.bdate_range(D1, periods=3)
    closes = {"A": pd.Series([10.0, 11.0, 12.0], index=days)}
    trades = [PaperTrade("A", BUY, 100, 10, D1, 0)]
    moves = [CashMovement(D3, DEPOSIT, 1000)]
    total, _ = daily_values(trades, 1000, closes, D3, movements=moves)
    assert list(total) == pytest.approx([1000, 1100, 2200])
    flows = flows_by_day(moves, pd.DatetimeIndex(total.index))
    growth = time_weighted(total, flows, 1000)
    assert growth.iloc[-1] == pytest.approx(1.2)  # the price return, deposit excluded
    bench = with_flows(closes["A"], flows, 1000)
    assert list(bench) == pytest.approx([1000, 1100, 2200])  # same money, same days


def test_weekend_movement_counts_next_trading_day() -> None:
    days = pd.bdate_range("2024-01-05", periods=2)  # Friday, Monday
    flows = flows_by_day([CashMovement(date(2024, 1, 6), DEPOSIT, 10)], days)
    assert list(flows) == [0, 10]


@pytest.fixture
def service() -> Iterator[PaperPortfolioService]:
    client = FakeYahooClient(synthetic_daily(sessions=60))
    client.known = {"TEST", "SPY"}
    now = datetime(2024, 3, 30, 12, tzinfo=UTC)
    market = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                               clock=lambda: now)  # fmt: skip
    yield PaperPortfolioService(open_database(":memory:"), market, clock=lambda: now)
    market.close()


def test_service_movements_and_report(service: PaperPortfolioService) -> None:
    (p,) = service.portfolios()
    with pytest.raises(UserError):
        service.make_movement(CASH_DIVIDEND, 10, D1)  # needs a ticker
    with pytest.raises(UserError):
        service.make_movement(DEPOSIT, -5, D1)
    with pytest.raises(UserError):
        service.make_movement("regalo", 5, D1)
    service.add_trade(p.id, "TEST", BUY, 50, trade_date=date(2024, 1, 15))
    dep = service.add_movement(p.id, service.make_movement(DEPOSIT, 5000, date(2024, 2, 1)))
    with pytest.raises(UserError):  # more than the cash available
        service.add_movement(p.id, service.make_movement(WITHDRAWAL, 1e6, date(2024, 2, 2)))
    report = service.report(p.id)
    assert report.valuation.invested == pytest.approx(15_000)
    assert report.invested.iloc[-1] == pytest.approx(15_000)
    spy = report.benchmark_prices["SPY"]
    assert report.time_weighted_pct is not None
    html = portfolio_html(report, datetime(2024, 3, 30))
    assert "Movimientos de efectivo" in html and "rentabilidad ponderada en el tiempo" in html
    assert "capital aportado" in html and len(spy) == len(report.equity)
    # Spend the deposit: removing it would make that purchase impossible.
    service.add_trade(p.id, "TEST", BUY, 1, price=9_000.0, trade_date=date(2024, 2, 5))
    with pytest.raises(UserError):
        service.delete_movement(p.id, dep.id or 0)
    assert len(service.movements(p.id)) == 1


def test_cash_tab(qtbot: QtBot, service: PaperPortfolioService) -> None:
    dialog = PortfolioDialog(service, lambda: "SPY", "TEST")
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.report is not None, timeout=10000)
    panel = dialog.cash
    assert not panel.symbol.isEnabled()
    panel.amount.setValue(2500)
    panel.day.setDate(QDate(2024, 2, 1))
    panel.add()
    qtbot.waitUntil(lambda: dialog.report is not None and len(dialog.report.movements) == 1,
                    timeout=10000)  # fmt: skip
    assert panel.table.rowCount() == 1 and panel.table.item(0, 1).text() == "Aportación"
    panel.kind.setCurrentIndex(panel.kind.findData(CASH_DIVIDEND))
    assert panel.symbol.isEnabled()
    panel.add()  # no ticker
    assert "ticker" in panel.status.text()
    panel.table.selectRow(0)
    panel.delete_selected()
    qtbot.waitUntil(lambda: dialog.report is not None and not dialog.report.movements,
                    timeout=10000)  # fmt: skip
