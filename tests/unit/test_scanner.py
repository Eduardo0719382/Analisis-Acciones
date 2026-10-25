from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scan_report import scan_csv
from analisis_acciones.services.scanner import (
    FundamentalLimits,
    ScanResult,
    passes_fundamentals,
    run_scan,
    scan_bars,
)
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
    client.info_payload = {"regularMarketPrice": 100.0, "trailingPE": 15.0, "dividendRate": 3.0,
                           "marketCap": 2.5e11, "revenueGrowth": 0.08,
                           "profitMargins": 0.21}  # fmt: skip
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
    assert (row.market_cap, row.revenue_growth, row.profit_margin) == (2.5e11, 0.08, 0.21)
    L = FundamentalLimits
    assert passes_fundamentals(row, L()) and not L().active
    assert passes_fundamentals(row, L(20, 2.5)) and not passes_fundamentals(row, L(10))
    assert not passes_fundamentals(row, L(min_yield_pct=4))
    assert passes_fundamentals(row, L(min_market_cap_bn=200, min_revenue_growth_pct=5,
                                      min_profit_margin_pct=20))  # fmt: skip
    assert not passes_fundamentals(row, L(min_market_cap_bn=300))
    assert not passes_fundamentals(row, L(min_revenue_growth_pct=10))
    assert not passes_fundamentals(row, L(min_profit_margin_pct=25))
    shrinking = replace(row, revenue_growth=-0.05)
    assert passes_fundamentals(shrinking, L(min_revenue_growth_pct=-10))  # negative limit
    missing = replace(row, pe=None, dividend_yield=None, market_cap=None)
    assert passes_fundamentals(missing, L())
    assert not passes_fundamentals(missing, L(20)) and not passes_fundamentals(missing, L(None, 1))
    assert not passes_fundamentals(missing, L(min_market_cap_bn=1))
    assert not passes_fundamentals(replace(row, pe=-5.0), L(20))  # losses
    assert L(20, min_profit_margin_pct=-5).describe() == "PER ≤ 20, margen neto ≥ -5 %"
    csv_text = scan_csv(ScanResult([row]))
    assert "per,rentabilidad_dividendo_pct,capitalizacion" in csv_text.splitlines()[0]
    assert ",15.0,3.0,250000000000.0,8.0,21.0," in csv_text.splitlines()[1]


def test_run_scan_can_be_cancelled(market: MarketDataService) -> None:
    seen: list[str] = []
    result = run_scan(market, ["AAA", "BBB"], progress=lambda _d, _t, s: seen.append(s),
                      cancelled=lambda: len(seen) >= 1)  # fmt: skip
    assert result.cancelled and [r.symbol for r in result.rows] == ["AAA"]
    assert not run_scan(market, ["AAA"]).cancelled


def test_exhaustion_in_scan_rows_and_daily_items() -> None:
    from analisis_acciones.services.daily_scan import notable_items
    from tests.unit.test_exhaustion import bars_from, rally

    row = scan_bars("RUN", bars_from(rally()))
    assert row.exhaustion >= 3 and row.exhaustion_total == 5
    assert "Señales de agotamiento de la subida (ver pestaña Agotamiento)" in notable_items(row)
    assert scan_csv(ScanResult([row])).splitlines()[1].endswith(f",subida {row.exhaustion}/5")
