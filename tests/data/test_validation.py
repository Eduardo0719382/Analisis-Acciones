from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.data.validation import validate_bars
from analisis_acciones.models.errors import DataError
from analisis_acciones.models.market import BAR_COLUMNS
from tests.synthetic import synthetic_daily


def test_valid_series_passes_unchanged() -> None:
    bars = synthetic_daily(sessions=50)
    clean, warnings = validate_bars(bars, "T")
    assert warnings == []
    assert list(clean.columns) == list(BAR_COLUMNS)
    pd.testing.assert_frame_equal(clean, bars.astype("float64"), check_freq=False)


def test_missing_optional_columns_are_added_without_inventing_data() -> None:
    bars = synthetic_daily(sessions=5)[["open", "high", "low", "close"]]
    clean, _ = validate_bars(bars, "T")
    assert clean["volume"].isna().all()  # unknown volume stays NaN, never 0
    assert clean["adj_close"].isna().all()
    assert (clean["dividends"] == 0).all()


def test_missing_price_column_is_rejected() -> None:
    with pytest.raises(DataError):
        validate_bars(synthetic_daily(sessions=5).drop(columns=["low"]), "T")


def test_empty_series_is_rejected() -> None:
    with pytest.raises(DataError) as info:
        validate_bars(synthetic_daily(sessions=5).iloc[0:0], "T")
    assert "No hay datos" in info.value.user_message


def test_all_nan_rows_dropped_silently() -> None:
    bars = synthetic_daily(sessions=40)
    bars.iloc[3, :4] = np.nan  # holiday-style empty row
    clean, warnings = validate_bars(bars, "T")
    assert len(clean) == 39
    assert warnings == []


def test_inconsistent_bars_dropped_with_warning() -> None:
    bars = synthetic_daily(sessions=100)
    bars.iloc[10, bars.columns.get_loc("high")] = bars.iloc[10]["low"] * 0.5  # high < low
    bars.iloc[20, bars.columns.get_loc("close")] = -1.0
    bars.iloc[30, bars.columns.get_loc("open")] = np.nan  # partial NaN
    bars.iloc[40, bars.columns.get_loc("volume")] = -5
    clean, warnings = validate_bars(bars, "T")
    assert len(clean) == 96
    assert any("4 barra" in w for w in warnings)


def test_too_many_invalid_bars_rejects_series() -> None:
    bars = synthetic_daily(sessions=20)
    bars.iloc[:5, bars.columns.get_loc("close")] = -1.0
    with pytest.raises(DataError) as info:
        validate_bars(bars, "T")
    assert "demasiadas" in info.value.user_message


def test_duplicates_and_order() -> None:
    bars = synthetic_daily(sessions=10)
    shuffled = pd.concat([bars.iloc[5:], bars.iloc[:5], bars.iloc[[2]]])
    clean, warnings = validate_bars(shuffled, "T")
    assert clean.index.is_monotonic_increasing
    assert not clean.index.has_duplicates
    assert len(clean) == 10
    assert any("duplicada" in w for w in warnings)


def test_infinite_values_are_invalid() -> None:
    bars = synthetic_daily(sessions=100)
    bars.iloc[5, bars.columns.get_loc("high")] = np.inf
    clean, _ = validate_bars(bars, "T")
    assert len(clean) == 99
