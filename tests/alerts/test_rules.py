from __future__ import annotations

import numpy as np
import pytest

from analisis_acciones.alerts.rules import (
    ALERT_SPECS,
    AlertKind,
    AlertRule,
    evaluate,
    validate_alert_params,
)
from analisis_acciones.models.errors import UserError
from tests.analysis.test_rules import make_bars


def rule(kind: AlertKind, **params: float) -> AlertRule:
    return AlertRule("T", kind, validate_alert_params(kind, params))


def test_every_kind_has_a_spec_and_description() -> None:
    assert set(ALERT_SPECS) == set(AlertKind)
    assert rule(AlertKind.RSI_BELOW).description == "T: RSI 14 < 30.0"
    assert rule(AlertKind.PRICE_ABOVE, value=190).description == "T: Cierre > 190.00"


def test_price_level_with_hysteresis() -> None:
    r = rule(AlertKind.PRICE_ABOVE, value=105)
    closes = [100, 103, 106, 107, 104, 108]
    fired = [evaluate(r, make_bars(closes[: i + 1])).fired for i in range(len(closes))]
    # Fires when it first closes above 105, stays quiet while above, re-arms below it.
    assert fired == [False, False, True, False, False, True]


def test_level_message_shows_values() -> None:
    r = rule(AlertKind.PRICE_BELOW, value=50)
    outcome = evaluate(r, make_bars([60, 55, 49.5]))
    assert outcome.fired
    assert outcome.check is not None
    assert outcome.check.message == "Cierre = 49.50 < 50.00"


def test_daily_change_alert() -> None:
    r = rule(AlertKind.CHANGE_BELOW, value=-5)
    assert not evaluate(r, make_bars([100, 97])).fired  # -3 %
    outcome = evaluate(r, make_bars([100, 97, 90]))  # -7.2 %
    assert outcome.fired and "Cambio = -7.22 %" in outcome.check.message  # type: ignore[union-attr]


def test_rsi_alert_needs_history() -> None:
    r = rule(AlertKind.RSI_ABOVE, period=14, value=70)
    outcome = evaluate(r, make_bars(np.linspace(1, 2, 10)))
    assert not outcome.fired and outcome.skipped and "15 barras" in outcome.skipped
    assert evaluate(r, make_bars(np.linspace(50, 150, 60))).fired


def test_ema_cross_fires_once_per_event() -> None:
    closes = np.concatenate([np.linspace(100, 60, 80), np.linspace(60, 120, 60)])
    bars = make_bars(closes)
    r = rule(AlertKind.EMA_CROSS_UP, fast=20, slow=50)
    fired_at = []
    for i in range(60, len(bars)):
        window = bars.iloc[: i + 1]
        if evaluate(r, window).fired:
            fired_at.append(i)
            # A second check of the same bar (e.g. the timer runs again) does not repeat it.
            assert not evaluate(r, window).fired
    assert len(fired_at) == 1


def test_breakout_alert() -> None:
    r = rule(AlertKind.BREAKOUT_HIGH, window=5)
    flat = [100, 100.5, 100, 100.5, 100, 100.2]
    assert not evaluate(r, make_bars(flat)).fired
    assert evaluate(r, make_bars([*flat, 103])).fired


def test_param_validation() -> None:
    with pytest.raises(UserError):
        validate_alert_params(AlertKind.RSI_ABOVE, {"value": 150})
    with pytest.raises(UserError):
        validate_alert_params(AlertKind.EMA_CROSS_UP, {"fast": 50, "slow": 20})
    with pytest.raises(UserError):
        validate_alert_params(AlertKind.PRICE_ABOVE, {"value": "x"})
    assert validate_alert_params(AlertKind.EMA_CROSS_UP, {}) == {"fast": 20, "slow": 50}
