"""MarketDataService with a fake provider client and a controllable clock."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from analisis_acciones.data.freshness import NEW_YORK
from analisis_acciones.models.errors import NetworkError, UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from tests.synthetic import FakeYahooClient, synthetic_daily

FULL = synthetic_daily(start="2024-01-01", sessions=120)  # ends 2024-06-14 (Friday)


class Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def ny(*args: int) -> datetime:
    return datetime(*args, tzinfo=NEW_YORK).astimezone(UTC)


@pytest.fixture
def client() -> FakeYahooClient:
    return FakeYahooClient(FULL.iloc[:100].copy())


@pytest.fixture
def clock() -> Clock:
    return Clock(ny(2024, 5, 20, 18, 0))  # Monday evening, after close


@pytest.fixture
def service(conn: sqlite3.Connection, client: FakeYahooClient, clock: Clock) -> MarketDataService:
    return MarketDataService(YahooFinanceProvider(client), conn, clock)


def test_intervals_include_derived(service: MarketDataService) -> None:
    assert service.available_intervals() == [
        Interval.M15,
        Interval.H1,
        Interval.D1,
        Interval.W1,
        Interval.MN1,
    ]


def test_first_load_fetches_full_history_and_caches(
    service: MarketDataService, client: FakeYahooClient
) -> None:
    result = service.load("test", Interval.D1)
    assert not result.from_cache
    assert len(result.series) == 100
    assert client.history_calls == [("TEST", None, None)]

    again = service.load("TEST", Interval.D1)
    assert again.from_cache
    assert len(client.history_calls) == 1  # no second download
    pd.testing.assert_frame_equal(again.series.bars, result.series.bars, check_freq=False)


def test_refresh_after_next_close_fetches_only_recent(
    service: MarketDataService, client: FakeYahooClient, clock: Clock
) -> None:
    service.load("TEST", Interval.D1)
    client.bars = FULL.iloc[:101].copy()  # one new session published
    clock.now = ny(2024, 5, 21, 17, 0)
    result = service.load("TEST", Interval.D1)
    assert not result.from_cache
    assert len(result.series) == 101
    _, start, _ = client.history_calls[-1]
    assert start is not None and start > FULL.index[0].date()  # incremental


def test_split_triggers_full_refetch(
    service: MarketDataService, client: FakeYahooClient, clock: Clock
) -> None:
    service.load("TEST", Interval.D1)
    adjusted = FULL.iloc[:101].copy()
    adjusted[["open", "high", "low", "close", "adj_close"]] /= 2  # 2:1 split re-adjusts history
    adjusted.iloc[-1, adjusted.columns.get_loc("splits")] = 2.0
    client.bars = adjusted
    clock.now = ny(2024, 5, 21, 17, 0)
    result = service.load("TEST", Interval.D1)
    assert client.history_calls[-1] == ("TEST", None, None)
    assert result.series.bars["close"].iloc[0] == pytest.approx(FULL["close"].iloc[0] / 2)


def test_offline_serves_stale_cache(
    service: MarketDataService, client: FakeYahooClient, clock: Clock
) -> None:
    service.load("TEST", Interval.D1)
    client.error = ConnectionError("no internet")
    clock.now = ny(2024, 5, 21, 17, 0)
    result = service.load("TEST", Interval.D1)
    assert result.stale and result.from_cache
    assert len(result.series) == 100
    assert result.notices


def test_offline_without_cache_raises(service: MarketDataService, client: FakeYahooClient) -> None:
    client.error = ConnectionError("no internet")
    with pytest.raises(NetworkError):
        service.load("TEST", Interval.D1)


def test_invalid_ticker(service: MarketDataService) -> None:
    with pytest.raises(UserError):
        service.load("NOPE", Interval.D1)


def test_weekend_needs_no_refetch(
    service: MarketDataService, client: FakeYahooClient, clock: Clock
) -> None:
    clock.now = ny(2024, 5, 24, 18, 0)  # Friday after close
    service.load("TEST", Interval.D1)
    clock.now = ny(2024, 5, 26, 12, 0)  # Sunday
    assert service.load("TEST", Interval.D1).from_cache
    assert len(client.history_calls) == 1


def test_weekly_and_monthly_from_cache(service: MarketDataService) -> None:
    weekly = service.load("TEST", Interval.W1)
    assert weekly.series.interval is Interval.W1
    assert len(weekly.series) == 20  # 100 business days
    monthly = service.load("TEST", Interval.MN1)
    assert monthly.series.interval is Interval.MN1
    assert monthly.from_cache


def test_session_in_progress_flag(
    service: MarketDataService, client: FakeYahooClient, clock: Clock
) -> None:
    last = FULL.index[99].date()
    clock.now = (
        datetime.combine(last, datetime.min.time(), NEW_YORK).replace(hour=12).astimezone(UTC)
    )
    result = service.load("TEST", Interval.D1)
    assert result.session_in_progress


def test_search_is_cached(
    service: MarketDataService, client: FakeYahooClient, clock: Clock
) -> None:
    client.search_payload = [{"symbol": "TEST", "shortname": "Test", "quoteType": "EQUITY"}]
    assert service.search("tes")[0].symbol == "TEST"
    client.search_payload = []
    assert service.search("TES")  # cached (case-insensitive)
    clock.now += timedelta(minutes=11)
    assert service.search("tes") == []


def test_recent_symbols(service: MarketDataService) -> None:
    service.remember("TEST", "Test Corp")
    assert service.recent()[0].symbol == "TEST"


def test_csv_import_and_reload(service: MarketDataService, tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text(
        "date,open,high,low,close,volume\n2024-01-02,10,11,9,10.5,100\n2024-01-03,10.5,12,10,11,200\n",
        encoding="utf-8",
    )
    imported = service.import_csv(path, "mi-serie")
    assert imported.series.symbol == "CSV:MI-SERIE"
    assert len(imported.series) == 2
    reloaded = service.load("csv:mi-serie", Interval.D1)
    assert reloaded.from_cache
    assert reloaded.series.bars["close"].tolist() == [10.5, 11.0]


def test_csv_name_validation(service: MarketDataService, tmp_path: Path) -> None:
    with pytest.raises(UserError):
        service.import_csv(tmp_path / "x.csv", "bad/name")
    with pytest.raises(UserError):
        service.import_csv(tmp_path / "x.csv", "with space")


def test_csv_series_loads_without_network(
    service: MarketDataService, client: FakeYahooClient, tmp_path: Path
) -> None:
    path = tmp_path / "data.csv"
    path.write_text(
        "date,open,high,low,close\n2024-01-02,10,11,9,10.5\n2024-01-03,10.5,12,10,11\n",
        encoding="utf-8",
    )
    service.import_csv(path, "MIO")
    client.error = ConnectionError("offline")
    result = service.load("CSV:MIO", Interval.D1)
    assert len(result.series) == 2
    assert result.series.source == "Archivo CSV"
    with pytest.raises(UserError):
        service.load("CSV:OTRO", Interval.D1)


def test_details_with_live_quote(service: MarketDataService, client: FakeYahooClient) -> None:
    service.load("TEST", Interval.D1)
    service.remember("TEST", "Test Corp")
    client.info_payload = {"regularMarketPrice": 50.0, "regularMarketPreviousClose": 40.0,
                           "longName": "Test Corporation"}  # fmt: skip
    details = service.details("test")
    assert details.price_source == "quote"
    assert details.change_pct == pytest.approx(25.0)
    assert details.name == "Test Corporation"
    assert details.notice is None


def test_details_offline_uses_bars(service: MarketDataService, client: FakeYahooClient) -> None:
    service.load("TEST", Interval.D1)
    client.error = ConnectionError("offline")
    details = service.details("TEST")
    assert details.price_source == "bars"
    assert details.price == pytest.approx(FULL["close"].iloc[99])
    assert details.notice and "conectar" in details.notice


def test_details_for_csv_never_uses_network(
    service: MarketDataService, client: FakeYahooClient, tmp_path: Path
) -> None:
    path = tmp_path / "d.csv"
    path.write_text("date,open,high,low,close\n2024-01-02,10,11,9,10.5\n2024-01-03,10.5,12,10,11\n",
                    encoding="utf-8")  # fmt: skip
    service.import_csv(path, "D")
    client.error = AssertionError("network must not be used")
    details = service.details("CSV:D")
    assert details.price == 11.0
    assert details.change == pytest.approx(0.5)


def test_snapshot_rows(service: MarketDataService, client: FakeYahooClient) -> None:
    rows = service.snapshot(["TEST", "NOPE"])
    ok, bad = rows
    assert ok.last_close == pytest.approx(FULL["close"].iloc[99])
    expected = (FULL["close"].iloc[99] / FULL["close"].iloc[98] - 1) * 100
    assert ok.change_pct == pytest.approx(expected)
    assert ok.error is None
    assert bad.last_close is None and bad.error and "NOPE" in bad.error
