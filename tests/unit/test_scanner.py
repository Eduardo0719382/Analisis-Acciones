from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scan_report import scan_csv
from analisis_acciones.services.scanner import ScanResult, passes_fundamentals, run_scan, scan_bars
from analisis_acciones.storage.database import open_database
from tests.synthetic import FakeYahooClient, path, synthetic_daily


@pytest.fixture
def market() -> Iterator[MarketDataService]:
    client = FakeYahooClient(synthetic_daily(sessions=400))
    client.known = {"AAA", "BBB"}
    fixed = datetime(2025, 9, 1, 23, 0, tzinfo=UTC)
    service = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                                clock=lambda: fixed)  # fmt: skip
    yield service
    service.close()


def test_scan_row_describes_last_bar() -> None:
    bars = synthetic_daily(sessions=400)
    row = scan_bars("AAA", bars)
    close = bars["close"]
    assert row.close == pytest.approx(close.iloc[-1])
    assert row.change_pct == pytest.approx((close.iloc[-1] / close.iloc[-2] - 1) * 100)
    assert row.rsi14 is not None and 0 <= row.rsi14 <= 100
    if row.support_pct is not None:
        assert row.support_pct > 0
    if row.resistance_pct is not None:
        assert row.resistance_pct >= 0


def test_scan_reports_forming_pattern_and_recent_breakout() -> None:
    # Long flat lead-in so every indicator has data, then a double top that breaks down.
    lead = [100.0 + (i % 2) * 0.5 for i in range(8)]
    bars = path(*lead, 130, 115, 129.5, 108)
    row = scan_bars("XYZ", bars)
    assert "Doble techo (ruptura reciente)" in row.patterns
    assert "Doble techo" in row.bearish


def test_short_history_is_rejected() -> None:
    with pytest.raises(ValueError):
        scan_bars("AAA", synthetic_daily(sessions=30))


def test_run_scan_collects_rows_and_problems(market: MarketDataService) -> None:
    seen: list[str] = []
    result = run_scan(market, ["aaa", "BBB", "AAA", "ZZZ", " "],
                      progress=lambda _d, _t, s: seen.append(s))  # fmt: skip
    assert [r.symbol for r in result.rows] == ["AAA", "BBB"]
    assert seen == ["AAA", "BBB", "ZZZ"]
    assert len(result.problems) == 1 and result.problems[0].startswith("ZZZ")


def test_scan_with_fundamentals_and_filter() -> None:
    client = FakeYahooClient(synthetic_daily(sessions=400))
    client.known = {"AAA"}
    client.info_payload = {"regularMarketPrice": 100.0, "trailingPE": 15.0, "dividendRate": 3.0}
    fixed = datetime(2025, 9, 1, 23, 0, tzinfo=UTC)
    market = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                               clock=lambda: fixed)  # fmt: skip
    try:
        (plain,) = run_scan(market, ["AAA"]).rows
        assert not plain.fundamentals_checked and plain.pe is None
        (row,) = run_scan(market, ["AAA"], fundamentals=True).rows
    finally:
        market.close()
    assert row.fundamentals_checked and row.pe == 15.0
    assert row.dividend_yield == pytest.approx(0.03)
    assert passes_fundamentals(row, None, None)
    assert passes_fundamentals(row, 20, 2.5) and not passes_fundamentals(row, 10, None)
    assert not passes_fundamentals(row, None, 4)
    missing = replace(row, pe=None, dividend_yield=None)
    assert passes_fundamentals(missing, None, None)
    assert not passes_fundamentals(missing, 20, None) and not passes_fundamentals(missing, None, 1)
    assert not passes_fundamentals(replace(row, pe=-5.0), 20, None)  # losses
    csv_text = scan_csv(ScanResult([row]))
    assert "per,rentabilidad_dividendo_pct" in csv_text.splitlines()[0]
    assert csv_text.splitlines()[1].endswith(",15.0,3.0")
