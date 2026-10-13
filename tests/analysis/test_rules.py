"""Analysis rules on hand-constructed series with known conditions."""

from __future__ import annotations

import numpy as np
import pandas as pd

from analisis_acciones.analysis.engine import analyze
from analisis_acciones.analysis.model import Direction
from analisis_acciones.indicators import functions as f


def make_bars(closes: list[float] | np.ndarray, *, spread: float = 0.5,
              volume: float = 1_000_000.0) -> pd.DataFrame:  # fmt: skip
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    index = pd.bdate_range("2023-01-02", periods=len(closes), name="date")
    return pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) + spread,
            "low": np.minimum(opens, closes) - spread,
            "close": closes,
            "adj_close": closes,
            "volume": volume,
            "dividends": 0.0,
            "splits": 0.0,
        },
        index=index,
    )


def by_rule(report_bars: pd.DataFrame, **kwargs: object) -> dict[str, list]:  # type: ignore[type-arg]
    report = analyze("T", report_bars, **kwargs)  # type: ignore[arg-type]
    out: dict[str, list] = {}  # type: ignore[type-arg]
    for s in report.signals:
        out.setdefault(s.rule_id, []).append(s)
    return out


def test_uptrend_signals_with_evidence() -> None:
    bars = make_bars(np.linspace(50, 150, 120))
    signals = by_rule(bars)
    trend = signals["trend"][0]
    assert trend.direction is Direction.BULLISH
    assert "EMA 20 > EMA 50" in trend.evidence
    ema20 = f.ema(bars["close"], 20).iloc[-1]
    assert any(f"{ema20:,.2f}" in line for line in trend.evidence)  # actual value shown
    assert signals["rsi"][0].title.startswith("Condición de sobrecompra")
    assert signals["breakout"][0].direction is Direction.BULLISH


def test_downtrend_signals() -> None:
    bars = make_bars(np.linspace(150, 50, 120))
    signals = by_rule(bars)
    assert signals["trend"][0].direction is Direction.BEARISH
    assert signals["rsi"][0].direction is Direction.BULLISH  # oversold
    assert "sobreventa" in signals["rsi"][0].title
    assert signals["breakdown"][0].direction is Direction.BEARISH


def test_sideways_market_without_momentum_extremes() -> None:
    closes = 100 + np.tile([0.4, -0.4], 60)
    signals = by_rule(make_bars(closes))
    assert signals["trend"][0].direction is Direction.NEUTRAL
    assert "rsi" not in signals
    assert "breakout" not in signals and "breakdown" not in signals


def test_recent_ema_crossover_is_dated() -> None:
    closes = np.concatenate([np.linspace(100, 60, 80), np.linspace(60, 120, 60)])
    full = make_bars(closes)
    fast, slow = f.ema(full["close"], 20), f.ema(full["close"], 50)
    above = fast > slow
    cross_at = int(
        np.flatnonzero(above.to_numpy() & ~above.shift(1, fill_value=True).to_numpy())[-1]
    )
    bars = full.iloc[: cross_at + 3]  # cross happened 2 bars before the end
    signal = by_rule(bars)["ema_cross"][0]
    assert signal.direction is Direction.BULLISH
    assert signal.bar_date == full.index[cross_at].date()
    # Outside the 5-bar window it is no longer reported.
    assert "ema_cross" not in by_rule(full.iloc[: cross_at + 10])


def test_abnormal_volume() -> None:
    bars = make_bars(np.linspace(100, 101, 40))
    bars.iloc[-1, bars.columns.get_loc("volume")] = 3_500_000
    signal = by_rule(bars)["volume"][0]
    assert any("3.50" in line for line in signal.evidence)  # ratio 3.5×
    bars.iloc[-1, bars.columns.get_loc("volume")] = 1_500_000
    assert "volume" not in by_rule(bars)


def test_volatility_increase() -> None:
    closes = np.linspace(100, 101, 80)
    calm = make_bars(closes, spread=0.2)
    wild = make_bars(closes, spread=0.2)
    wild.loc[wild.index[-15:], "high"] += 3
    wild.loc[wild.index[-15:], "low"] -= 3
    assert "volatility" not in by_rule(calm)
    signal = by_rule(wild)["volatility"][0]
    assert signal.title == "Aumento de volatilidad"


def test_insufficient_history_is_reported_not_guessed() -> None:
    report = analyze("T", make_bars(np.linspace(1, 2, 10)))
    assert report.signals == ()
    assert len(report.skipped) == 7
    assert "requiere 51 barras" in report.skipped[0]


def test_in_progress_bar_excluded() -> None:
    bars = make_bars(100 + np.tile([0.4, -0.4], 30))
    bars.iloc[-1, bars.columns.get_loc("volume")] = 9_000_000  # only on the partial bar
    assert "volume" in by_rule(bars)
    report = analyze("T", bars, session_in_progress=True)
    assert report.excluded_partial_bar
    assert report.bars_used == len(bars) - 1
    assert report.as_of == bars.index[-2].date()
    assert all(s.rule_id != "volume" for s in report.signals)


def test_no_advice_language() -> None:
    bars = make_bars(np.linspace(50, 150, 120))
    text = " ".join(" ".join((s.title, *s.evidence)) for s in analyze("T", bars).signals).lower()
    for forbidden in ("compra", "vende", "subirá", "bajará", "garant", "recomend"):
        assert forbidden not in text.replace("sobrecompra", "")
