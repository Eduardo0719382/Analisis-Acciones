from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pandas as pd
import pytest
from pytestqt.qtbot import QtBot

from analisis_acciones.alerts.service import AlertService
from analisis_acciones.models.errors import UserError
from analisis_acciones.portfolio.alerts import AlertThresholds, conditions
from analisis_acciones.portfolio.engine import BUY, PaperTrade, replay, value
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.paper_portfolio import PaperPortfolioService
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.storage.database import open_database
from analisis_acciones.ui.main_window import MainWindow
from tests.synthetic import FakeYahooClient, synthetic_daily

D = date(2024, 1, 2)


def test_conditions() -> None:
    state = replay([PaperTrade("AAA", BUY, 10, 100, D), PaperTrade("BBB", BUY, 10, 10, D)], 1100)
    val = value(state, 1100, {"AAA": 85.0, "BBB": 10.0})  # AAA -15 %, weights 89.5 / 10.5
    equity = pd.Series([1100.0, 1200.0, 950.0], index=pd.bdate_range(D, periods=3))
    limits = AlertThresholds(loss_pct=10, drift_pts=20, drawdown_pct=15)
    found = conditions(val, equity, {"AAA": 50, "BBB": 50}, limits)
    assert set(found) == {"loss:AAA", "drift:AAA", "drift:BBB", "drawdown"}
    assert "AAA pierde 15,0 %" in found["loss:AAA"][1]
    assert "20,8 %" in found["drawdown"][1]
    assert conditions(val, equity, {}, AlertThresholds()) == {}
    assert not AlertThresholds().active and limits.active
    milder = conditions(val, equity, {"AAA": 80, "BBB": 20}, AlertThresholds(20, 20, 25))
    assert milder == {}


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    bars = synthetic_daily(sessions=60)
    bars.loc[bars.index >= pd.Timestamp("2024-03-01"), ["open", "high", "low", "close"]] *= 0.7
    client = FakeYahooClient(bars)
    client.known = {"TEST", "SPY"}
    market = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                               clock=lambda: datetime(2024, 3, 30, 12, tzinfo=UTC))  # fmt: skip
    yield market
    market.close()


@pytest.fixture
def service(market: MarketDataService) -> PaperPortfolioService:
    return PaperPortfolioService(open_database(":memory:"), market,
                                 clock=lambda: datetime(2024, 3, 30, 12, tzinfo=UTC))  # fmt: skip


def test_service_announces_once_and_rearms(service: PaperPortfolioService) -> None:
    (p,) = service.portfolios()
    with pytest.raises(UserError):
        service.set_alerts(p.id, AlertThresholds(loss_pct=-1))
    service.add_trade(p.id, "TEST", BUY, 10, trade_date=date(2024, 1, 15))
    assert service.check_alerts() == []  # alerts off
    service.set_alerts(p.id, AlertThresholds(loss_pct=10))
    (notice,) = service.check_alerts()
    assert notice.symbol == "TEST" and notice.portfolio == "Mi cartera"
    assert "pierde" in notice.message
    assert service.check_alerts() == []  # already announced
    service.set_alerts(p.id, AlertThresholds(loss_pct=90))
    assert service.check_alerts() == []  # condition gone: forgotten (re-armed)
    service.set_alerts(p.id, AlertThresholds(loss_pct=10))
    assert len(service.check_alerts()) == 1  # announced again


def test_window_records_portfolio_notices(qtbot: QtBot, settings: SettingsService,
                                          market: MarketDataService,
                                          service: PaperPortfolioService) -> None:  # fmt: skip
    (p,) = service.portfolios()
    service.add_trade(p.id, "TEST", BUY, 10, trade_date=date(2024, 1, 15))
    service.set_alerts(p.id, AlertThresholds(loss_pct=10))
    alerts = AlertService(open_database(":memory:"), market)
    win = MainWindow(settings, market_service=market, alert_service=alerts,
                     portfolio_service=service)  # fmt: skip
    qtbot.addWidget(win)
    assert win.check_portfolio_alerts()
    assert not win.check_portfolio_alerts()  # one check at a time
    qtbot.waitUntil(lambda: bool(win.portfolio_notices), timeout=10000)
    (event,) = alerts.events()
    assert event.description == "Cartera «Mi cartera»" and event.symbol == "TEST"
    alerts.close()
