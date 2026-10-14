"""Indicator metadata: parameters, placement, outputs and how to compute them.

The UI builds its configuration forms and chart series from this registry, so
adding an indicator means adding one ``IndicatorSpec`` here (plus its tests).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd

from analisis_acciones.indicators import functions as f
from analisis_acciones.models.errors import UserError

Placement = Literal["overlay", "pane"]
Style = Literal["line", "histogram"]


@dataclass(frozen=True)
class ParamSpec:
    key: str
    label: str
    default: int | float
    minimum: int | float
    maximum: int | float
    kind: Literal["int", "float"] = "int"
    decimals: int = 0


@dataclass(frozen=True)
class OutputSpec:
    key: str
    label: str
    style: Style = "line"
    color: str = "#f5a623"
    #: Name of the parameter giving a display shift in bars (+ ahead, − behind),
    #: e.g. Ichimoku's Senkou spans (+displacement) and Chikou (−displacement).
    shift_param: str | None = None
    shift_sign: int = 1
    #: Colour each point up/down by the sign of this other output column.
    color_sign: str | None = None

    def shift(self, params: dict[str, Any]) -> int:
        if self.shift_param is None:
            return 0
        return self.shift_sign * int(params[self.shift_param])


@dataclass(frozen=True)
class IndicatorSpec:
    id: str
    name: str
    short: str
    description: str
    params: tuple[ParamSpec, ...]
    outputs: tuple[OutputSpec, ...]
    placement: Placement
    compute: Callable[[pd.DataFrame, dict[str, Any]], pd.DataFrame]
    #: Horizontal reference levels drawn in the indicator pane (e.g. RSI 70/30).
    levels: tuple[float, ...] = ()
    #: Fixed number of decimals for display (None = same as the price).
    decimals: int | None = None
    #: Shaded areas between two outputs (Ichimoku cloud): green where the first
    #: is above the second, red otherwise.
    fills: tuple[tuple[str, str], ...] = ()

    def defaults(self) -> dict[str, int | float]:
        return {p.key: p.default for p in self.params}

    def label(self, params: dict[str, Any]) -> str:
        values = ", ".join(_fmt(params[p.key]) for p in self.params)
        return f"{self.short} ({values})" if values else self.short


def _fmt(value: int | float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _frame(**columns: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(columns)


SPECS: tuple[IndicatorSpec, ...] = (
    IndicatorSpec(
        id="sma",
        name="Media móvil simple (SMA)",
        short="SMA",
        description="Promedio aritmético de los últimos N cierres.",
        params=(ParamSpec("period", "Periodo", 20, 1, 500),),
        outputs=(OutputSpec("value", "SMA", color="#f5a623"),),
        placement="overlay",
        compute=lambda b, p: _frame(value=f.sma(b["close"], int(p["period"]))),
    ),
    IndicatorSpec(
        id="ema",
        name="Media móvil exponencial (EMA)",
        short="EMA",
        description="Media que da más peso a los cierres recientes (alfa = 2/(N+1)).",
        params=(ParamSpec("period", "Periodo", 50, 1, 500),),
        outputs=(OutputSpec("value", "EMA", color="#4c8dff"),),
        placement="overlay",
        compute=lambda b, p: _frame(value=f.ema(b["close"], int(p["period"]))),
    ),
    IndicatorSpec(
        id="bollinger",
        name="Bandas de Bollinger",
        short="BB",
        description="SMA(N) ± K desviaciones estándar de los cierres.",
        params=(
            ParamSpec("period", "Periodo", 20, 2, 500),
            ParamSpec("k", "Desviaciones (K)", 2.0, 0.1, 10.0, kind="float", decimals=1),
        ),
        outputs=(
            OutputSpec("upper", "Superior", color="#26c6da"),
            OutputSpec("middle", "Media", color="#ab47bc"),
            OutputSpec("lower", "Inferior", color="#26c6da"),
        ),
        placement="overlay",
        compute=lambda b, p: f.bollinger(b["close"], int(p["period"]), float(p["k"])),
    ),
    IndicatorSpec(
        id="rsi",
        name="Índice de fuerza relativa (RSI)",
        short="RSI",
        description="Oscilador 0-100 de Wilder. 70/30 son niveles de referencia habituales.",
        params=(ParamSpec("period", "Periodo", 14, 2, 200),),
        outputs=(OutputSpec("value", "RSI", color="#ab47bc"),),
        placement="pane",
        compute=lambda b, p: _frame(value=f.rsi(b["close"], int(p["period"]))),
        levels=(70.0, 30.0),
    ),
    IndicatorSpec(
        id="macd",
        name="MACD",
        short="MACD",
        description="EMA rápida - EMA lenta, su línea de señal y el histograma.",
        params=(
            ParamSpec("fast", "EMA rápida", 12, 1, 200),
            ParamSpec("slow", "EMA lenta", 26, 2, 400),
            ParamSpec("signal", "Señal", 9, 1, 200),
        ),
        outputs=(
            OutputSpec("histogram", "Histograma", style="histogram", color="#8a93a3"),
            OutputSpec("macd", "MACD", color="#4c8dff"),
            OutputSpec("signal", "Señal", color="#f5a623"),
        ),
        placement="pane",
        compute=lambda b, p: f.macd(b["close"], int(p["fast"]), int(p["slow"]), int(p["signal"])),
        levels=(0.0,),
    ),
    IndicatorSpec(
        id="atr",
        name="Rango verdadero medio (ATR)",
        short="ATR",
        description="Volatilidad media de Wilder basada en el rango verdadero.",
        params=(ParamSpec("period", "Periodo", 14, 1, 200),),
        outputs=(OutputSpec("value", "ATR", color="#ec407a"),),
        placement="pane",
        compute=lambda b, p: _frame(value=f.atr(b["high"], b["low"], b["close"], int(p["period"]))),
    ),
)

SPECS = (
    *SPECS,
    IndicatorSpec(
        id="ichimoku",
        name="Ichimoku Kinko Hyo",
        short="Ichimoku",
        description=(
            "Tenkan y Kijun: punto medio del máximo y mínimo de N barras. Senkou A = media de "
            "ambas y Senkou B = punto medio de 52 barras, dibujadas 26 barras adelante (la nube). "
            "Chikou = cierre dibujado 26 barras atrás."
        ),
        params=(
            ParamSpec("tenkan", "Tenkan", 9, 1, 200),
            ParamSpec("kijun", "Kijun", 26, 1, 200),
            ParamSpec("senkou_b", "Senkou B", 52, 2, 400),
            ParamSpec("displacement", "Desplazamiento", 26, 1, 200),
        ),
        outputs=(
            OutputSpec("tenkan", "Tenkan", color="#4c8dff"),
            OutputSpec("kijun", "Kijun", color="#ef5350"),
            OutputSpec("senkou_a", "Senkou A", color="#26a69a", shift_param="displacement"),
            OutputSpec("senkou_b", "Senkou B", color="#ab47bc", shift_param="displacement"),
            OutputSpec("chikou", "Chikou", color="#8a93a3", shift_param="displacement",
                       shift_sign=-1),
        ),
        placement="overlay",
        fills=(("senkou_a", "senkou_b"),),
        compute=lambda b, p: f.ichimoku(
            b["high"], b["low"], b["close"], int(p["tenkan"]), int(p["kijun"]),
            int(p["senkou_b"]),
        ),
    ),
    IndicatorSpec(
        id="supertrend",
        name="Supertrend",
        short="Supertrend",
        description="Banda de ATR (Wilder) × multiplicador que cambia de lado con la tendencia.",
        params=(
            ParamSpec("period", "Periodo ATR", 10, 1, 200),
            ParamSpec("multiplier", "Multiplicador", 3.0, 0.5, 10.0, kind="float", decimals=1),
        ),
        outputs=(OutputSpec("value", "Supertrend", color="#26a69a", color_sign="direction"),),
        placement="overlay",
        compute=lambda b, p: f.supertrend(
            b["high"], b["low"], b["close"], int(p["period"]), float(p["multiplier"])
        ),
    ),
    IndicatorSpec(
        id="stochastic",
        name="Estocástico lento",
        short="Estoc.",
        description="%K = SMA(posición del cierre en el rango de N barras); %D = SMA de %K.",
        params=(
            ParamSpec("k", "%K", 14, 2, 200),
            ParamSpec("smooth", "Suavizado", 3, 1, 50),
            ParamSpec("d", "%D", 3, 1, 50),
        ),
        outputs=(OutputSpec("k", "%K", color="#4c8dff"), OutputSpec("d", "%D", color="#f5a623")),
        placement="pane",
        compute=lambda b, p: f.stochastic(
            b["high"], b["low"], b["close"], int(p["k"]), int(p["smooth"]), int(p["d"])
        ),
        levels=(80.0, 20.0),
        decimals=2,
    ),
    IndicatorSpec(
        id="stoch_rsi",
        name="RSI estocástico",
        short="StochRSI",
        description="Estocástico aplicado al RSI (0-100).",
        params=(
            ParamSpec("rsi", "Periodo RSI", 14, 2, 200),
            ParamSpec("stoch", "Periodo estocástico", 14, 2, 200),
            ParamSpec("smooth", "Suavizado", 3, 1, 50),
            ParamSpec("d", "%D", 3, 1, 50),
        ),
        outputs=(OutputSpec("k", "%K", color="#4c8dff"), OutputSpec("d", "%D", color="#f5a623")),
        placement="pane",
        compute=lambda b, p: f.stoch_rsi(
            b["close"], int(p["rsi"]), int(p["stoch"]), int(p["smooth"]), int(p["d"])
        ),
        levels=(80.0, 20.0),
        decimals=2,
    ),
    IndicatorSpec(
        id="adx",
        name="ADX / DMI",
        short="ADX",
        description="Fuerza de la tendencia (ADX) y dirección (+DI / -DI), de Wilder.",
        params=(ParamSpec("period", "Periodo", 14, 2, 200),),
        outputs=(
            OutputSpec("adx", "ADX", color="#f5a623"),
            OutputSpec("plus_di", "+DI", color="#26a69a"),
            OutputSpec("minus_di", "-DI", color="#ef5350"),
        ),
        placement="pane",
        compute=lambda b, p: f.adx(b["high"], b["low"], b["close"], int(p["period"])),
        levels=(25.0,),
        decimals=2,
    ),
    IndicatorSpec(
        id="obv",
        name="On-Balance Volume (OBV)",
        short="OBV",
        description="Volumen acumulado con el signo del cambio diario del cierre.",
        params=(),
        outputs=(OutputSpec("value", "OBV", color="#26c6da"),),
        placement="pane",
        compute=lambda b, p: _frame(value=f.obv(b["close"], b["volume"])),
        decimals=0,
    ),
)  # fmt: skip

REGISTRY: dict[str, IndicatorSpec] = {spec.id: spec for spec in SPECS}


def get_spec(indicator_id: str) -> IndicatorSpec:
    try:
        return REGISTRY[indicator_id]
    except KeyError:
        raise UserError(
            f"unknown indicator {indicator_id!r}",
            user_message=f"Indicador desconocido: «{indicator_id}».",
        ) from None


def validate_params(spec: IndicatorSpec, raw: dict[str, Any]) -> dict[str, int | float]:
    """Typed, range-checked parameters; missing ones take their default."""
    params: dict[str, int | float] = {}
    for p in spec.params:
        value = raw.get(p.key, p.default)
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise UserError(
                f"{spec.id}.{p.key}={value!r} is not a number",
                user_message=f"{p.label}: el valor debe ser numérico.",
            ) from None
        if p.kind == "int":
            if not number.is_integer():
                raise UserError(
                    f"{spec.id}.{p.key}={value!r} is not an integer",
                    user_message=f"{p.label}: el valor debe ser un número entero.",
                )
            number = int(number)
        if not p.minimum <= number <= p.maximum:
            raise UserError(
                f"{spec.id}.{p.key}={number} out of range",
                user_message=(
                    f"{p.label}: el valor debe estar entre {_fmt(p.minimum)} y {_fmt(p.maximum)}."
                ),
            )
        params[p.key] = number
    if spec.id == "macd" and params["fast"] >= params["slow"]:
        raise UserError(
            "macd fast >= slow",
            user_message="MACD: la EMA rápida debe tener un periodo menor que la lenta.",
        )
    return params


@dataclass(frozen=True)
class IndicatorConfig:
    """One indicator instance on the chart."""

    indicator_id: str
    params: dict[str, int | float]
    visible: bool = True
    uid: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def spec(self) -> IndicatorSpec:
        return get_spec(self.indicator_id)

    @property
    def label(self) -> str:
        return self.spec.label(self.params)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.indicator_id, "params": dict(self.params), "visible": self.visible,
                "uid": self.uid}  # fmt: skip

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IndicatorConfig:
        spec = get_spec(str(data.get("id")))
        params = validate_params(spec, dict(data.get("params") or {}))
        uid = data.get("uid")
        return cls(
            spec.id,
            params,
            bool(data.get("visible", True)),
            uid if isinstance(uid, str) and uid.isalnum() else uuid.uuid4().hex[:12],
        )

    @classmethod
    def create(cls, indicator_id: str, params: dict[str, Any] | None = None) -> IndicatorConfig:
        spec = get_spec(indicator_id)
        return cls(spec.id, validate_params(spec, params or {}))


def compute(config: IndicatorConfig, bars: pd.DataFrame) -> pd.DataFrame:
    """Indicator values aligned to ``bars.index`` (NaN during warm-up)."""
    spec = config.spec
    result = spec.compute(bars, config.params)
    return result.reindex(bars.index)
