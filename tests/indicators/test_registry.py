from __future__ import annotations

import pytest

from analisis_acciones.indicators.registry import (
    REGISTRY,
    IndicatorConfig,
    compute,
    get_spec,
    validate_params,
)
from analisis_acciones.models.errors import UserError
from tests.synthetic import synthetic_daily


def test_mvp_indicators_registered() -> None:
    assert {"sma", "ema", "rsi", "macd", "bollinger", "atr"} <= set(REGISTRY)
    assert get_spec("rsi").placement == "pane"
    assert get_spec("sma").placement == "overlay"
    assert get_spec("rsi").levels == (70.0, 30.0)


@pytest.mark.parametrize("indicator_id", sorted(REGISTRY))
def test_every_indicator_computes_aligned_output(indicator_id: str) -> None:
    bars = synthetic_daily(sessions=300)
    config = IndicatorConfig.create(indicator_id)
    out = compute(config, bars)
    assert out.index.equals(bars.index)
    # Every drawn output is present (helper columns such as a colour sign may be extra).
    assert {o.key for o in config.spec.outputs} <= set(out.columns)
    last = out.iloc[-1]
    assert last.notna().all()  # defined at the end of a long series


def test_validate_params() -> None:
    spec = get_spec("bollinger")
    assert validate_params(spec, {}) == {"period": 20, "k": 2.0}
    assert validate_params(spec, {"period": "30", "k": "2.5"}) == {"period": 30, "k": 2.5}
    cases = [
        (spec, {"period": 20.5}, "entero"),
        (spec, {"period": 1}, "entre"),
        (spec, {"k": "abc"}, "numérico"),
        (get_spec("macd"), {"fast": 30, "slow": 26}, "rápida"),
    ]
    for case_spec, raw, expected in cases:
        with pytest.raises(UserError) as info:
            validate_params(case_spec, raw)
        assert expected in info.value.user_message


def test_unknown_indicator() -> None:
    with pytest.raises(UserError):
        get_spec("nope")


def test_config_round_trip_and_label() -> None:
    config = IndicatorConfig.create("macd", {"fast": 8})
    assert config.label == "MACD (8, 26, 9)"
    restored = IndicatorConfig.from_dict(config.to_dict())
    assert restored == config


def test_from_dict_rejects_invalid_stored_values() -> None:
    with pytest.raises(UserError):
        IndicatorConfig.from_dict({"id": "sma", "params": {"period": -3}})
