from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from analisis_acciones.models.errors import DataError
from analisis_acciones.services.comparison import compare
from tests.analysis.test_rules import make_bars


def test_normalised_performance_by_hand() -> None:
    a = make_bars([100, 110, 121])
    b = make_bars([50, 45, 60])
    result = compare({"A": a, "B": b}, None)
    assert result.performance["A"].round(6).tolist() == [0.0, 10.0, 21.0]
    assert result.performance["B"].round(6).tolist() == [0.0, -10.0, 20.0]
    metrics = {m.symbol: m for m in result.metrics}
    assert metrics["A"].total_return_pct == pytest.approx(21.0)
    assert metrics["B"].max_drawdown_pct == pytest.approx(-10.0)
    expected_vol = np.std(np.log([110 / 100, 121 / 110]), ddof=1) * math.sqrt(252) * 100
    assert metrics["A"].volatility_pct == pytest.approx(expected_vol)
    assert metrics["A"].avg_volume == 1_000_000


def test_common_dates_and_period() -> None:
    long = make_bars(np.linspace(100, 200, 400))
    short = make_bars(np.linspace(10, 20, 400)).iloc[-100:]
    result = compare({"L": long, "S": short}, None)
    assert result.start == short.index[0].date()  # first session both have
    assert len(result.performance) == 100
    one_month = compare({"L": long}, 31)
    assert len(one_month.performance) <= 24  # 31 calendar days, both ends inclusive


def test_not_enough_overlap() -> None:
    a = make_bars([1, 2, 3])
    b = make_bars([1, 2, 3])
    b.index = b.index + pd.Timedelta(days=30)
    with pytest.raises(DataError):
        compare({"A": a, "B": b}, None)
