from __future__ import annotations

import pandas as pd
import pytest

from analisis_acciones.services.comparison import benchmark_line


def frame(values: list[float], start: str = "2024-01-01") -> pd.DataFrame:
    return pd.DataFrame({"close": values}, index=pd.bdate_range(start, periods=len(values)))


def test_benchmark_rebased_to_asset_at_window_start() -> None:
    asset = frame([100, 110, 120, 132])
    bench = frame([50, 50, 55, 60])
    line = benchmark_line(asset, bench, window=3)
    assert line is not None
    assert line.start == pd.Timestamp("2024-01-02")
    assert list(line.values) == pytest.approx([110, 121, 132])  # bench rebased to 110
    assert line.asset_return_pct == pytest.approx(20)
    assert line.benchmark_return_pct == pytest.approx(20)
    assert line.relative_pct == pytest.approx(0)


def test_missing_benchmark_days_are_gaps_and_no_overlap_is_none() -> None:
    asset = frame([100, 101, 102, 103])
    bench = frame([10, 11, 12, 13]).drop(pd.Timestamp("2024-01-03"))
    line = benchmark_line(asset, bench, window=4)
    assert line is not None and line.values.isna().sum() == 1
    assert benchmark_line(asset, frame([1, 2], start="2030-01-01")) is None
