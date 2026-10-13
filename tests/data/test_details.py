from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.data.details import build_details, week52_range
from analisis_acciones.models.market import CompanyInfo, Quote
from tests.synthetic import synthetic_daily


def test_week52_range_by_hand() -> None:
    bars = synthetic_daily(start="2023-01-02", sessions=400)
    high, low = week52_range(bars)
    last = bars.index[-1]
    window = bars[bars.index > last - pd.Timedelta(days=365)]
    assert high == window["high"].max()
    assert low == window["low"].min()


def test_week52_requires_a_full_year() -> None:
    assert week52_range(synthetic_daily(sessions=100)) == (None, None)
    assert week52_range(synthetic_daily(sessions=1).iloc[0:0]) == (None, None)


def test_details_from_bars_only() -> None:
    bars = synthetic_daily(sessions=30)
    details = build_details("TEST", bars, fallback_name="Test Corp", notice="offline")
    assert details.price_source == "bars"
    assert details.price == bars["close"].iloc[-1]
    assert details.previous_close == bars["close"].iloc[-2]
    assert details.change == pytest.approx(bars["close"].iloc[-1] - bars["close"].iloc[-2])
    assert details.change_pct == pytest.approx(
        (bars["close"].iloc[-1] / bars["close"].iloc[-2] - 1) * 100
    )
    assert details.as_of == bars.index[-1].date()
    assert details.name == "Test Corp"
    assert details.notice == "offline"
    assert details.week52_high is None  # only 30 sessions: not computed, not guessed


def test_quote_overrides_price_fields_and_info_fills_metadata() -> None:
    bars = synthetic_daily(sessions=30)
    quote = Quote("TEST", 110.0, 100.0, open=101.0, day_high=111.0, day_low=99.0, volume=0.0,
                  currency="USD", market_state="REGULAR",
                  as_of=datetime(2025, 1, 2, 15, 0, tzinfo=UTC))  # fmt: skip
    info = CompanyInfo("TEST", name="Test Corp", sector="Tech", fifty_two_week_high=150.0,
                       fifty_two_week_low=80.0)  # fmt: skip
    details = build_details("TEST", bars, quote, info)
    assert details.price_source == "quote"
    assert details.price == 110.0
    assert details.change_pct == pytest.approx(10.0)
    assert details.volume == 0.0
    assert details.sector == "Tech"
    # Short history: 52-week range falls back to the provider's values.
    assert (details.week52_high, details.week52_low) == (150.0, 80.0)


def test_bar_52w_range_preferred_over_provider() -> None:
    bars = synthetic_daily(start="2023-01-02", sessions=400)
    info = CompanyInfo("TEST", fifty_two_week_high=999.0, fifty_two_week_low=1.0)
    details = build_details("TEST", bars, None, info)
    assert details.week52_high == week52_range(bars)[0]


def test_missing_volume_stays_unknown() -> None:
    bars = synthetic_daily(sessions=5)
    bars["volume"] = np.nan
    assert build_details("TEST", bars).volume is None


def test_no_data_at_all() -> None:
    details = build_details("TEST", synthetic_daily(sessions=1).iloc[0:0])
    assert details.price is None and details.change is None
    assert details.as_of is None


def test_single_bar_has_no_previous_close() -> None:
    details = build_details("TEST", synthetic_daily(sessions=1))
    assert details.previous_close is None
    assert details.change is None
    assert isinstance(details.as_of, date)
