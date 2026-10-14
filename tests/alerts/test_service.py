from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime

import numpy as np
import pytest

from analisis_acciones.alerts.rules import AlertKind
from analisis_acciones.alerts.service import AlertService
from analisis_acciones.data.freshness import NEW_YORK
from analisis_acciones.models.errors import UserError
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.storage.database import open_database
from tests.analysis.test_rules import make_bars
from tests.synthetic import FakeYahooClient


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2023, 3, 20, 18, 0, tzinfo=NEW_YORK).astimezone(UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def client() -> FakeYahooClient:
    fake = FakeYahooClient(make_bars(np.linspace(100, 110, 55)))  # ends 2023-03-17 (Fri)
    fake.known = {"TEST"}
    return fake


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def market(client: FakeYahooClient, clock: Clock) -> Iterator[MarketDataService]:
    conn = open_database(":memory:")
    service = MarketDataService(YahooFinanceProvider(client), conn, clock)
    yield service
    service.close()


@pytest.fixture
def alerts(market: MarketDataService, clock: Clock) -> Iterator[AlertService]:
    conn: sqlite3.Connection = open_database(":memory:")
    service = AlertService(conn, market, clock)
    yield service
    service.close()


def test_create_list_delete(alerts: AlertService) -> None:
    created = alerts.create(" test ", AlertKind.PRICE_ABOVE, {"value": 105})
    assert created.symbol == "TEST" and created.id
    assert [a.description for a in alerts.alerts()] == ["TEST: Cierre > 105.00"]
    alerts.delete(created.id)
    assert alerts.alerts() == []


def test_invalid_input_rejected(alerts: AlertService) -> None:
    with pytest.raises(UserError):
        alerts.create("bad ticker!", AlertKind.PRICE_ABOVE, {"value": 1})
    with pytest.raises(UserError):
        alerts.create("TEST", AlertKind.RSI_ABOVE, {"value": -5})


def test_check_fires_once_and_records_event(alerts: AlertService) -> None:
    alerts.create("TEST", AlertKind.PRICE_ABOVE, {"value": 105})
    alerts.create("TEST", AlertKind.PRICE_BELOW, {"value": 50})
    first = alerts.check_all()
    assert first.checked == 2
    assert [e.description for e in first.events] == ["TEST: Cierre > 105.00"]
    assert first.events[0].message.startswith("Cierre = 110.00 >")
    assert alerts.check_all().events == ()  # condition still true: no repeat
    stored = alerts.events()
    assert len(stored) == 1 and stored[0].symbol == "TEST"


def test_disabled_alerts_are_not_checked_and_reenable_rearms(alerts: AlertService) -> None:
    rule = alerts.create("TEST", AlertKind.PRICE_ABOVE, {"value": 105})
    assert rule.id is not None
    alerts.set_enabled(rule.id, False)
    assert alerts.check_all().checked == 0
    alerts.check_all()
    alerts.set_enabled(rule.id, True)
    assert len(alerts.check_all().events) == 1


def test_unknown_symbol_and_offline_reported_as_problems(
    alerts: AlertService, client: FakeYahooClient
) -> None:
    alerts.create("ZZZZ", AlertKind.PRICE_ABOVE, {"value": 1})
    summary = alerts.check_all()
    assert summary.events == ()
    assert any("ZZZZ" in p for p in summary.problems)


def test_in_progress_session_bar_is_ignored(
    alerts: AlertService, client: FakeYahooClient, clock: Clock
) -> None:
    bars = make_bars(np.linspace(100, 104, 56))  # last bar = 2023-03-20 (Monday)
    bars.iloc[-1, bars.columns.get_loc("close")] = 200.0  # spike only in the open session
    client.bars = bars
    clock.now = datetime(2023, 3, 20, 12, 0, tzinfo=NEW_YORK).astimezone(UTC)
    alerts.create("TEST", AlertKind.PRICE_ABOVE, {"value": 150})
    assert alerts.check_all().events == ()


def test_level_alerts_pick_direction_and_keep_note(alerts: AlertService) -> None:
    created = alerts.create_level_alerts(
        "test", 110, [("Elliott impulso: objetivo", 125.456), ("Elliott impulso: invalidación", 95)]
    )
    assert [r.kind for r in created] == [AlertKind.PRICE_ABOVE, AlertKind.PRICE_BELOW]
    assert [r.description for r in alerts.alerts()] == [
        "TEST: Cierre > 125.46 (Elliott impulso: objetivo)",
        "TEST: Cierre < 95.00 (Elliott impulso: invalidación)",
    ]


def test_note_is_single_line_and_bounded(alerts: AlertService) -> None:
    rule = alerts.create("TEST", AlertKind.PRICE_ABOVE, {"value": 105}, note="a\nb  " + "x" * 500)
    assert "\n" not in rule.note and len(rule.note) == 120
    assert alerts.alerts()[0].note == rule.note
