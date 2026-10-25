"""Cryptocurrencies: Yahoo pairs quoted every day, with the daily bar closing at 00:00 UTC."""

from __future__ import annotations

import math
import sqlite3
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.charts.payload import future_times, trades_every_day
from analisis_acciones.data.freshness import is_crypto, needs_refresh, session_in_progress
from analisis_acciones.models.errors import UserError
from analisis_acciones.models.market import Interval
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.comparison import compare
from analisis_acciones.services.market_data_service import (
    MarketDataService,
    intraday_bar_in_progress,
)
from tests.synthetic import FakeYahooClient, synthetic_daily


def crypto_daily(start: str = "2024-01-01", days: int = 200) -> pd.DataFrame:
    """Synthetic bars on every calendar day, weekends included."""
    bars = synthetic_daily(start=start, sessions=days)
    bars.index = pd.date_range(start, periods=days, freq="D", name="date")
    return bars


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


@pytest.mark.parametrize("symbol", ["BTC-USD", "eth-eur", "SOL-USDT", "1INCH-USD", "ETH-BTC"])
def test_crypto_pairs_are_recognised(symbol: str) -> None:
    assert is_crypto(symbol)


@pytest.mark.parametrize("symbol", ["AAPL", "BRK-B", "BF-B", "SPY", "^GSPC", "EURUSD=X", "CSV:X"])
def test_stocks_and_share_classes_are_not_crypto(symbol: str) -> None:
    assert not is_crypto(symbol)


def test_crypto_daily_bar_forms_until_utc_midnight() -> None:
    # Saturday: a crypto bar is forming.
    saturday = utc(2024, 6, 15, 12, 0)
    assert session_in_progress(date(2024, 6, 15), saturday, crypto=True)
    assert not session_in_progress(date(2024, 6, 14), saturday, crypto=True)
    # 23:59 UTC still forming; after midnight that bar is complete.
    assert session_in_progress(date(2024, 6, 15), utc(2024, 6, 15, 23, 59), crypto=True)
    assert not session_in_progress(date(2024, 6, 15), utc(2024, 6, 16, 0, 1), crypto=True)


def test_crypto_cache_refreshes_after_midnight_and_hourly() -> None:
    now = utc(2024, 6, 16, 10, 0)  # Sunday
    assert not needs_refresh(utc(2024, 6, 16, 9, 30), now, crypto=True)
    assert needs_refresh(utc(2024, 6, 16, 8, 59), now, crypto=True)  # over an hour old
    assert needs_refresh(utc(2024, 6, 15, 23, 50), utc(2024, 6, 16, 0, 20), crypto=True)
    # The stock rule would not refresh on a Sunday after Friday's close.
    assert not needs_refresh(utc(2024, 6, 14, 22, 0), now)


def test_crypto_intraday_bar_has_no_session_close() -> None:
    start = datetime(2024, 6, 15, 21, 0)  # 21:00 UTC Saturday (wall time, naive)
    assert intraday_bar_in_progress(start, Interval.H1, utc(2024, 6, 15, 21, 30), crypto=True)
    assert not intraday_bar_in_progress(start, Interval.H1, utc(2024, 6, 15, 22, 0), crypto=True)


def test_future_times_step_every_calendar_day_for_crypto() -> None:
    bars = crypto_daily(days=60)  # ends 2024-02-29 (Thursday)
    assert trades_every_day(pd.DatetimeIndex(bars.index))
    assert future_times(bars, 3) == ["2024-03-01", "2024-03-02", "2024-03-03"]
    stock = synthetic_daily(start="2024-01-01", sessions=60)
    assert not trades_every_day(pd.DatetimeIndex(stock.index))


def test_future_times_intraday_crypto_is_continuous() -> None:
    index = pd.date_range("2024-06-14 20:00", periods=48, freq="h")
    bars = synthetic_daily(sessions=48)
    bars.index = index
    times = future_times(bars, 2)
    expected = [int(pd.Timestamp(t).timestamp()) for t in ("2024-06-16 20:00", "2024-06-16 21:00")]
    assert times == expected


def test_search_keeps_crypto_results() -> None:
    client = FakeYahooClient()
    client.search_payload = [
        {"symbol": "BTC-USD", "shortname": "Bitcoin USD", "quoteType": "CRYPTOCURRENCY",
         "exchDisp": "CCC"},
        {"symbol": "BTC-EUR", "shortname": "Bitcoin EUR", "quoteType": "CRYPTOCURRENCY"},
        {"symbol": "BITO", "shortname": "ProShares Bitcoin ETF", "quoteType": "ETF"},
    ]  # fmt: skip
    results = YahooFinanceProvider(client).search_symbol("bitcoin")
    assert [r.symbol for r in results] == ["BTC-USD", "BTC-EUR", "BITO"]
    assert results[0].asset_type == "CRYPTOCURRENCY"


def test_service_marks_todays_crypto_bar_in_progress(conn: sqlite3.Connection) -> None:
    bars = crypto_daily(start="2024-01-01", days=167)  # last bar 2024-06-15 (Saturday)
    client = FakeYahooClient(bars)
    client.known = {"BTC-USD"}
    service = MarketDataService(YahooFinanceProvider(client), conn,
                                lambda: utc(2024, 6, 15, 14, 0))  # fmt: skip
    result = service.load("BTC-USD", Interval.D1)
    assert result.series.bars.index[-1] == pd.Timestamp("2024-06-15")
    assert result.session_in_progress
    assert len(result.series.bars) == 167  # weekends kept


def test_crypto_cache_refetches_within_the_same_day(conn: sqlite3.Connection) -> None:
    client = FakeYahooClient(crypto_daily(days=167))
    client.known = {"BTC-USD"}
    now = [utc(2024, 6, 15, 10, 0)]
    service = MarketDataService(YahooFinanceProvider(client), conn, lambda: now[0])
    service.load("BTC-USD", Interval.D1)
    calls = len(client.history_calls)
    now[0] += timedelta(minutes=20)
    service.load("BTC-USD", Interval.D1)
    assert len(client.history_calls) == calls  # cache still fresh
    now[0] += timedelta(hours=1)
    service.load("BTC-USD", Interval.D1)
    assert len(client.history_calls) == calls + 1


def test_no_company_fundamentals_for_crypto(conn: sqlite3.Connection) -> None:
    service = MarketDataService(YahooFinanceProvider(FakeYahooClient()), conn,
                                lambda: utc(2024, 6, 15))  # fmt: skip
    with pytest.raises(UserError) as info:
        service.fundamentals("BTC-USD")
    assert "criptomonedas" in info.value.user_message


def test_crypto_volatility_is_annualised_over_365_days() -> None:
    bars = crypto_daily(days=200)
    result = compare({"BTC-USD": bars}, None)
    logs = np.log(bars["close"] / bars["close"].shift(1)).dropna()
    expected = float(logs.std(ddof=1) * math.sqrt(365) * 100)
    assert result.metrics[0].volatility_pct == pytest.approx(expected)


def test_portfolio_with_crypto_is_valued_every_day() -> None:
    from analisis_acciones.portfolio.engine import BUY, PaperTrade, daily_values

    days = pd.date_range("2024-06-01", "2024-06-30", freq="D")  # 2024-06-01 is a Saturday
    btc = pd.Series(np.linspace(60_000, 66_000, len(days)), index=days)
    stock_days = pd.bdate_range("2024-06-01", "2024-06-30")
    spy = pd.Series(np.linspace(500, 520, len(stock_days)), index=stock_days)
    trades = [
        PaperTrade("BTC-USD", BUY, 0.1, 60_000, date(2024, 6, 1)),  # bought on a Saturday
        PaperTrade("SPY", BUY, 2, 500, date(2024, 6, 3)),
    ]
    total, per = daily_values(trades, 10_000, {"BTC-USD": btc, "SPY": spy}, date(2024, 6, 30))
    assert total.index[0] == pd.Timestamp("2024-06-01")
    assert pd.Timestamp("2024-06-08") in total.index  # weekend values present
    # SPY keeps Friday's close over the weekend; BTC moves.
    assert per.loc["2024-06-08", "SPY"] == per.loc["2024-06-07", "SPY"]
    assert per.loc["2024-06-08", "BTC-USD"] != per.loc["2024-06-07", "BTC-USD"]
    stocks_only, _ = daily_values(trades[1:], 10_000, {"SPY": spy}, date(2024, 6, 30))
    assert (pd.DatetimeIndex(stocks_only.index).day_of_week < 5).all()


def test_backtest_buys_fractions_of_an_expensive_coin() -> None:
    from analisis_acciones.backtesting.engine import BacktestConfig, run_backtest

    bars = crypto_daily(days=30)
    bars[["open", "high", "low", "close", "adj_close"]] *= 600  # about 60 000 per coin
    signals = pd.DataFrame({"entry": False, "exit": False}, index=bars.index)
    signals.iloc[2, 0] = True
    whole = run_backtest(bars, signals, BacktestConfig(10_000))
    assert whole.open_trade is None and whole.notes  # cannot buy one whole coin
    frac = run_backtest(bars, signals, BacktestConfig(10_000, fractional=True))
    assert frac.open_trade is not None
    shares = frac.open_trade.shares
    assert 0 < shares < 1 and round(shares, 8) == shares
    spent = shares * frac.open_trade.entry_price + frac.open_trade.entry_commission
    assert 9_990 < spent <= 10_000
