from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from analisis_acciones.alerts.rules import AlertKind, AlertRule, bar_key, evaluate
from analisis_acciones.alerts.service import AlertService
from analisis_acciones.models.errors import UserError
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.storage.database import open_database
from tests.synthetic import FakeYahooClient, synthetic_intraday

LATER = datetime.now(UTC) + timedelta(days=1)  # every synthetic bar is complete by then


@pytest.fixture
def alerts() -> Iterator[AlertService]:
    market = MarketDataService(YahooFinanceProvider(FakeYahooClient()), open_database(":memory:"),
                               clock=lambda: LATER)  # fmt: skip
    service = AlertService(open_database(":memory:"), market, clock=lambda: LATER)
    yield service
    service.close()
    market.close()


def test_bar_key() -> None:
    assert bar_key(pd.Timestamp("2025-03-07")) == "2025-03-07"
    assert bar_key(pd.Timestamp("2025-03-07 10:30")) == "2025-03-07T10:30"


def test_intraday_level_alert_fires_once_with_bar_time(alerts: AlertService) -> None:
    rule = alerts.create("TEST", AlertKind.PRICE_ABOVE, {"value": 1}, interval="1h")
    assert rule.description == "TEST (1 hora): Cierre > 1.00"
    first = alerts.check_all()
    assert len(first.events) == 1 and first.problems == ()
    assert "vela de las 15:30" in first.events[0].message
    assert alerts.check_all().events == ()
    stored = alerts.alerts()[0]
    assert stored.interval == "1h" and stored.last_bar is not None and "T15:30" in stored.last_bar


def test_event_alerts_dedupe_per_intraday_bar() -> None:
    bars = synthetic_intraday(start="2025-03-06", days=2)
    bars.loc[bars.index[-1], ["close", "high"]] = 1000.0  # breakout on the last hourly bar
    rule = AlertRule("TEST", AlertKind.BREAKOUT_HIGH, {"window": 5}, interval="1h")
    assert evaluate(rule, bars).fired
    assert not evaluate(rule, bars).fired  # same bar
    later = pd.concat([bars, bars.iloc[[-1]].set_axis([bars.index[-1] + pd.Timedelta(days=1)])])
    later.loc[later.index[-1], ["close", "high"]] = 2000.0
    assert evaluate(rule, later).fired  # a new bar, even if it is the same time of day


def test_invalid_interval_and_csv(alerts: AlertService) -> None:
    with pytest.raises(UserError):
        alerts.create("TEST", AlertKind.PRICE_ABOVE, {"value": 1}, interval="4h")
    with pytest.raises(UserError):
        alerts.create("CSV:MINE", AlertKind.PRICE_ABOVE, {"value": 1}, interval="15m")


def test_level_alerts_keep_interval(alerts: AlertService) -> None:
    created = alerts.create_level_alerts("TEST", 100, [("Fibo 61,8 %", 95.0)], interval="15m")
    assert created[0].interval == "15m" and alerts.has_intraday_alerts()
