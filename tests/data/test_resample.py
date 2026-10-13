from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.data.resample import resample_daily
from analisis_acciones.models.errors import InternalError
from analisis_acciones.models.market import Interval
from tests.synthetic import synthetic_daily


def test_daily_is_returned_as_is() -> None:
    bars = synthetic_daily(sessions=10)
    assert resample_daily(bars, Interval.D1) is bars


def test_weekly_aggregation_by_hand() -> None:
    # 2024-01-01 is a Monday: 10 business days = two full weeks.
    bars = synthetic_daily(start="2024-01-01", sessions=10)
    weekly = resample_daily(bars, Interval.W1)
    assert list(weekly.index) == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-08")]
    week1 = bars.iloc[:5]
    row = weekly.iloc[0]
    assert row["open"] == week1["open"].iloc[0]
    assert row["high"] == week1["high"].max()
    assert row["low"] == week1["low"].min()
    assert row["close"] == week1["close"].iloc[-1]
    assert row["volume"] == pytest.approx(week1["volume"].sum())


def test_week_label_is_first_trading_day() -> None:
    bars = synthetic_daily(start="2024-01-01", sessions=10).drop(pd.Timestamp("2024-01-08"))
    weekly = resample_daily(bars, Interval.W1)
    assert weekly.index[1] == pd.Timestamp("2024-01-09")  # Monday was a holiday


def test_monthly_aggregation() -> None:
    bars = synthetic_daily(start="2024-01-01", sessions=60)
    monthly = resample_daily(bars, Interval.MN1)
    jan = bars[bars.index.month == 1]
    assert monthly.index[0] == pd.Timestamp("2024-01-01")
    assert monthly.iloc[0]["close"] == jan["close"].iloc[-1]
    assert monthly.iloc[0]["high"] == jan["high"].max()
    assert len(monthly) == 3


def test_missing_volume_stays_nan() -> None:
    bars = synthetic_daily(sessions=10)
    bars["volume"] = np.nan
    assert resample_daily(bars, Interval.W1)["volume"].isna().all()


def test_unsupported_interval() -> None:
    with pytest.raises(InternalError):
        resample_daily(synthetic_daily(sessions=5), Interval.H1)


def test_empty_input() -> None:
    assert resample_daily(synthetic_daily(sessions=5).iloc[0:0], Interval.W1).empty
