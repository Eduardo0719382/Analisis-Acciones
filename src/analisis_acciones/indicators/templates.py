"""Named sets of indicators. Built-in templates plus the user's own (stored in settings)."""

from __future__ import annotations

from analisis_acciones.indicators.registry import IndicatorConfig
from analisis_acciones.models.errors import UserError

MAX_NAME = 40
MAX_TEMPLATES = 30

#: Read-only templates shipped with the program: name -> [(indicator id, params)].
BUILTIN: dict[str, list[tuple[str, dict[str, float]]]] = {
    "Tendencia": [("ema", {"period": 20}), ("ema", {"period": 50}), ("adx", {})],
    "Momento": [("rsi", {}), ("macd", {}), ("stochastic", {})],
    "Volatilidad": [("bollinger", {}), ("atr", {}), ("supertrend", {})],
    "Intradía": [("vwap", {}), ("ema", {"period": 9}), ("ema", {"period": 21}), ("rsi", {})],
    "Ichimoku": [("ichimoku", {})],
}


def builtin_configs(name: str) -> list[IndicatorConfig]:
    return [IndicatorConfig.create(i, p) for i, p in BUILTIN[name]]


def clean_name(raw: str) -> str:
    name = " ".join(str(raw).split())
    if not name:
        raise UserError("empty template name", user_message="Escriba un nombre para la plantilla.")
    if len(name) > MAX_NAME:
        raise UserError(
            "template name too long",
            user_message=f"El nombre puede tener como máximo {MAX_NAME} caracteres.",
        )
    if name in BUILTIN:
        raise UserError(
            "built-in template name",
            user_message=f"«{name}» es una plantilla predefinida: use otro nombre.",
        )
    return name
