"""Build weekly and monthly bars from daily bars.

Each output bar is labelled with the date of the first trading session in the
period, so a bar never carries a date on which no trading happened.
Partial periods (e.g. the current week) are kept and contain the sessions so far.
"""

from __future__ import annotations

import pandas as pd

from analisis_acciones.models.errors import InternalError
from analisis_acciones.models.market import Interval

_PERIOD = {Interval.W1: "W-SUN", Interval.MN1: "M"}


def resample_daily(daily: pd.DataFrame, interval: Interval) -> pd.DataFrame:
    if interval is Interval.D1:
        return daily
    if interval not in _PERIOD:
        raise InternalError(f"cannot resample daily bars to {interval}")
    if daily.empty:
        return daily.copy()

    periods = pd.DatetimeIndex(daily.index).to_period(_PERIOD[interval])
    groups = daily.groupby(periods, sort=True)
    out = groups.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        adj_close=("adj_close", "last"),
        # min_count=1: a period with no volume data stays NaN instead of 0.
        volume=("volume", lambda s: s.sum(min_count=1)),
        dividends=("dividends", "sum"),
        splits=("splits", lambda s: s[s > 0].prod() if (s > 0).any() else 0.0),
    )
    first_dates = daily.index.to_series().groupby(periods, sort=True).first()
    out.index = pd.DatetimeIndex(first_dates.to_numpy(), name="date")
    return out.astype("float64")
