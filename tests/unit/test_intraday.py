from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from analisis_acciones.charts.payload import build_payload, chart_times, future_times
from analisis_acciones.models.errors import UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import (
    MarketDataService,
    intraday_bar_in_progress,
)
from analisis_acciones.storage.database import open_database
from tests.synthetic import FakeYahooClient, synthetic_daily, synthetic_intraday


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def client() -> FakeYahooClient:
    return FakeYahooClient()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def service(client: FakeYahooClient, clock: Clock) -> Iterator[MarketDataService]:
    svc = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"), clock)
    yield svc
    svc.close()


def test_provider_keeps_times_and_clamps_start(client: FakeYahooClient) -> None:
    provider = YahooFinanceProvider(client)
    series = provider.get_historical_data("TEST", Interval.M15)
    assert series.interval is Interval.M15
    times = pd.DatetimeIndex(series.bars.index)
    assert times[0].hour == 9 and times[0].minute == 30 and times[1].minute == 45
    symbol, start, _end, code = client.intraday_calls[-1]
    assert (symbol, code) == ("TEST", "15m")
    assert start is not None and (pd.Timestamp.today().date() - start).days == 59
    old = pd.Timestamp.today().date() - timedelta(days=2000)
    provider.get_historical_data("TEST", Interval.H1, start=old)
    assert (pd.Timestamp.today().date() - client.intraday_calls[-1][1]).days == 729


def test_cache_refresh_merge_and_stale(service: MarketDataService, client: FakeYahooClient,
                                       clock: Clock) -> None:  # fmt: skip
    first = service.load("test", Interval.H1)
    assert not first.from_cache and first.series.interval is Interval.H1
    assert len(first.series.bars) == len(client.intraday["1h"])
    calls = len(client.intraday_calls)
    assert service.load("TEST", Interval.H1).from_cache  # within the refresh window
    assert len(client.intraday_calls) == calls

    # Later: only recent bars are requested and merged; older stored bars are kept.
    clock.now += timedelta(minutes=30)
    client.intraday["1h"] = client.intraday["1h"].iloc[-30:]
    merged = service.load("TEST", Interval.H1)
    assert client.intraday_calls[-1][1] is not None
    assert len(merged.series.bars) == len(first.series.bars)

    clock.now += timedelta(minutes=30)
    client.error = ConnectionError("offline")
    stale = service.load("TEST", Interval.H1)
    assert stale.stale and stale.from_cache and len(stale.series.bars) == len(first.series.bars)


def test_csv_series_has_no_intraday(service: MarketDataService) -> None:
    with pytest.raises(UserError):
        service.load("CSV:MINE", Interval.H1)


def test_bar_in_progress() -> None:
    ny_10_45 = datetime(2025, 3, 7, 15, 45, tzinfo=UTC)  # 10:45 New York (EST)
    assert intraday_bar_in_progress(datetime(2025, 3, 7, 10, 30), Interval.H1, ny_10_45)
    assert not intraday_bar_in_progress(datetime(2025, 3, 7, 9, 30), Interval.H1, ny_10_45)
    assert not intraday_bar_in_progress(datetime(2025, 3, 7, 10, 30), Interval.M15, ny_10_45)
    # The last hourly bar (15:30) ends at the 16:00 close, not at 16:30.
    ny_16_10 = datetime(2025, 3, 7, 21, 10, tzinfo=UTC)
    assert not intraday_bar_in_progress(datetime(2025, 3, 7, 15, 30), Interval.H1, ny_16_10)
    assert not intraday_bar_in_progress(None, Interval.H1, ny_16_10)


def test_chart_times_and_payload() -> None:
    daily = synthetic_daily(sessions=3)
    assert chart_times(daily.index) == ["2024-01-01", "2024-01-02", "2024-01-03"]
    intraday = synthetic_intraday(start="2025-03-07", days=1)
    times = chart_times(intraday.index)
    assert times[0] == int(datetime(2025, 3, 7, 9, 30, tzinfo=UTC).timestamp())
    from analisis_acciones.models.market import BarSeries

    payload = build_payload(BarSeries("T", Interval.H1, intraday, "s"), "T", "#0f0", "#f00")
    assert payload["intraday"] is True and payload["candles"][0]["time"] == times[0]


def test_future_times_skip_nights_and_weekends() -> None:
    friday = synthetic_intraday(start="2025-03-07", days=1)  # last bar 15:30
    future = future_times(friday, 3)
    as_dt = [datetime.fromtimestamp(t, UTC).replace(tzinfo=None) for t in future]  # type: ignore[arg-type]
    assert as_dt == [datetime(2025, 3, 10, 9, 30), datetime(2025, 3, 10, 10, 30),
                     datetime(2025, 3, 10, 11, 30)]  # fmt: skip
