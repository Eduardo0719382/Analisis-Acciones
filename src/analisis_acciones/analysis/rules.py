"""Analysis rules. Each rule reads completed bars only and explains itself.

Rules evaluate the last bar of the frame they receive; the engine decides
which bars are passed (it drops an in-progress session bar).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from analisis_acciones.analysis.model import Category, Direction, NumberFormat, Signal
from analisis_acciones.indicators import functions as f


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    min_bars: int
    evaluate: Callable[[pd.DataFrame, NumberFormat], list[Signal]]


def _last_date(bars: pd.DataFrame) -> pd.Timestamp:
    return pd.Timestamp(bars.index[-1])


# Trend ------------------------------------------------------------------------
TREND_FAST, TREND_SLOW = 20, 50
#: Minimum relative gap between the EMAs before a trend is reported; below it
#: the averages are considered intertwined (sideways market).
TREND_MIN_GAP = 0.005


def trend(bars: pd.DataFrame, fmt: NumberFormat) -> list[Signal]:
    close = bars["close"]
    fast = f.ema(close, TREND_FAST).iloc[-1]
    slow = f.ema(close, TREND_SLOW).iloc[-1]
    price = close.iloc[-1]
    gap = (fast - slow) / slow
    day = _last_date(bars).date()
    facts = (
        f"EMA {TREND_FAST} = {fmt(fast, 2)}",
        f"EMA {TREND_SLOW} = {fmt(slow, 2)}",
        f"Separación entre medias = {fmt(gap * 100, 2)} % (mínimo ±{TREND_MIN_GAP * 100:g} %)",
        f"Cierre = {fmt(price, 2)}",
    )
    if gap >= TREND_MIN_GAP and price > fast:
        return [Signal("trend", Category.TREND, Direction.BULLISH,
                       "Tendencia alcista detectada",
                       (f"EMA {TREND_FAST} > EMA {TREND_SLOW}", f"Cierre > EMA {TREND_FAST}",
                        *facts), day)]  # fmt: skip
    if gap <= -TREND_MIN_GAP and price < fast:
        return [Signal("trend", Category.TREND, Direction.BEARISH,
                       "Tendencia bajista detectada",
                       (f"EMA {TREND_FAST} < EMA {TREND_SLOW}", f"Cierre < EMA {TREND_FAST}",
                        *facts), day)]  # fmt: skip
    return [Signal("trend", Category.TREND, Direction.NEUTRAL,
                   "Mercado lateral o sin tendencia clara",
                   ("No se cumplen las condiciones de tendencia: medias separadas al menos "
                    f"{TREND_MIN_GAP * 100:g} % y cierre del mismo lado que la EMA {TREND_FAST}.",
                    *facts), day)]  # fmt: skip


# RSI --------------------------------------------------------------------------
RSI_PERIOD, RSI_HIGH, RSI_LOW = 14, 70.0, 30.0


def rsi_levels(bars: pd.DataFrame, fmt: NumberFormat) -> list[Signal]:
    value = f.rsi(bars["close"], RSI_PERIOD).iloc[-1]
    day = _last_date(bars).date()
    if value >= RSI_HIGH:
        return [Signal("rsi", Category.MOMENTUM, Direction.BEARISH,
                       "Condición de sobrecompra (RSI)",
                       (f"RSI {RSI_PERIOD} = {fmt(value, 1)}, un nivel asociado habitualmente "
                        f"a sobrecompra (≥ {RSI_HIGH:.0f})",), day)]  # fmt: skip
    if value <= RSI_LOW:
        return [Signal("rsi", Category.MOMENTUM, Direction.BULLISH,
                       "Condición de sobreventa (RSI)",
                       (f"RSI {RSI_PERIOD} = {fmt(value, 1)}, un nivel asociado habitualmente "
                        f"a sobreventa (≤ {RSI_LOW:.0f})",), day)]  # fmt: skip
    return []


# Crossovers -------------------------------------------------------------------
CROSS_LOOKBACK = 5


def _crosses(a: pd.Series, b: pd.Series) -> pd.Series:
    """+1 where a crosses above b on that bar, -1 where it crosses below, else 0."""
    above = (a > b).astype(int)
    valid = a.notna() & b.notna() & a.shift(1).notna() & b.shift(1).notna()
    change = above.diff().where(valid, 0).fillna(0)
    return change.astype(int)


def _recent_cross(a: pd.Series, b: pd.Series, lookback: int) -> tuple[int, pd.Timestamp] | None:
    crosses = _crosses(a, b).iloc[-lookback:]
    hits = crosses[crosses != 0]
    if hits.empty:
        return None
    return int(hits.iloc[-1]), pd.Timestamp(hits.index[-1])


def ema_crossover(bars: pd.DataFrame, fmt: NumberFormat) -> list[Signal]:
    close = bars["close"]
    fast, slow = f.ema(close, TREND_FAST), f.ema(close, TREND_SLOW)
    hit = _recent_cross(fast, slow, CROSS_LOOKBACK)
    if hit is None:
        return []
    sign, when = hit
    bullish = sign > 0
    word = "alcista" if bullish else "bajista"
    op = ">" if bullish else "<"
    return [Signal("ema_cross", Category.CROSSOVER,
                   Direction.BULLISH if bullish else Direction.BEARISH,
                   f"Cruce {word} EMA {TREND_FAST}/{TREND_SLOW}",
                   (f"El {when:%d/%m/%Y} la EMA {TREND_FAST} pasó a estar {op} EMA {TREND_SLOW}",
                    f"EMA {TREND_FAST} = {fmt(fast.loc[when], 2)}, "
                    f"EMA {TREND_SLOW} = {fmt(slow.loc[when], 2)} en esa fecha",
                    f"Ventana de búsqueda: últimas {CROSS_LOOKBACK} barras"),
                   when.date())]  # fmt: skip


def macd_crossover(bars: pd.DataFrame, fmt: NumberFormat) -> list[Signal]:
    m = f.macd(bars["close"])
    hit = _recent_cross(m["macd"], m["signal"], CROSS_LOOKBACK)
    if hit is None:
        return []
    sign, when = hit
    bullish = sign > 0
    word = "alcista" if bullish else "bajista"
    op = "por encima" if bullish else "por debajo"
    return [Signal("macd_cross", Category.CROSSOVER,
                   Direction.BULLISH if bullish else Direction.BEARISH,
                   f"Cruce {word} del MACD con su señal",
                   (f"El {when:%d/%m/%Y} el MACD (12, 26) cruzó {op} de su señal (9)",
                    f"MACD = {fmt(m['macd'].loc[when], 3)}, "
                    f"señal = {fmt(m['signal'].loc[when], 3)} en esa fecha",
                    f"Ventana de búsqueda: últimas {CROSS_LOOKBACK} barras"),
                   when.date())]  # fmt: skip


# Volume -----------------------------------------------------------------------
VOLUME_WINDOW, VOLUME_FACTOR = 20, 2.0


def abnormal_volume(bars: pd.DataFrame, fmt: NumberFormat) -> list[Signal]:
    volume = bars["volume"]
    last = volume.iloc[-1]
    previous = volume.iloc[-VOLUME_WINDOW - 1 : -1].dropna()
    if pd.isna(last) or len(previous) < VOLUME_WINDOW or previous.mean() <= 0:
        return []
    ratio = last / previous.mean()
    if ratio < VOLUME_FACTOR:
        return []
    return [Signal("volume", Category.VOLUME, Direction.NEUTRAL,
                   "Volumen anormalmente alto",
                   (f"Volumen de la última barra = {fmt(last, 0)}",
                    f"Media de las {VOLUME_WINDOW} barras anteriores = {fmt(previous.mean(), 0)}",
                    f"Relación = {fmt(ratio, 2)}× (umbral {VOLUME_FACTOR:g}×)"),
                   _last_date(bars).date())]  # fmt: skip


# Volatility -------------------------------------------------------------------
ATR_PERIOD, VOL_LOOKBACK, VOL_CHANGE = 14, 20, 0.30


def volatility_change(bars: pd.DataFrame, fmt: NumberFormat) -> list[Signal]:
    atr = f.atr(bars["high"], bars["low"], bars["close"], ATR_PERIOD)
    now, before = atr.iloc[-1], atr.iloc[-1 - VOL_LOOKBACK]
    if pd.isna(now) or pd.isna(before) or before <= 0:
        return []
    change = now / before - 1.0
    if abs(change) < VOL_CHANGE:
        return []
    up = change > 0
    return [Signal("volatility", Category.VOLATILITY, Direction.NEUTRAL,
                   "Aumento de volatilidad" if up else "Disminución de volatilidad",
                   (f"ATR {ATR_PERIOD} actual = {fmt(now, 2)}",
                    f"ATR {ATR_PERIOD} hace {VOL_LOOKBACK} barras = {fmt(before, 2)}",
                    f"Variación = {'+' if up else ''}{fmt(change * 100, 1)} % "
                    f"(umbral ±{VOL_CHANGE * 100:.0f} %)"),
                   _last_date(bars).date())]  # fmt: skip


# Breakouts --------------------------------------------------------------------
BREAKOUT_WINDOW = 20


def breakout(bars: pd.DataFrame, fmt: NumberFormat) -> list[Signal]:
    previous = bars.iloc[-BREAKOUT_WINDOW - 1 : -1]
    close = bars["close"].iloc[-1]
    high, low = previous["high"].max(), previous["low"].min()
    day = _last_date(bars).date()
    if close > high:
        return [Signal("breakout", Category.BREAKOUT, Direction.BULLISH,
                       f"Ruptura por encima del máximo de {BREAKOUT_WINDOW} barras",
                       (f"Cierre = {fmt(close, 2)}",
                        f"Máximo de las {BREAKOUT_WINDOW} barras anteriores = {fmt(high, 2)}"),
                       day)]  # fmt: skip
    if close < low:
        return [Signal("breakdown", Category.BREAKOUT, Direction.BEARISH,
                       f"Ruptura por debajo del mínimo de {BREAKOUT_WINDOW} barras",
                       (f"Cierre = {fmt(close, 2)}",
                        f"Mínimo de las {BREAKOUT_WINDOW} barras anteriores = {fmt(low, 2)}"),
                       day)]  # fmt: skip
    return []


DEFAULT_RULES: tuple[Rule, ...] = (
    Rule("trend", "Tendencia (EMA 20/50)", TREND_SLOW + 1, trend),
    Rule("rsi", "RSI 14 (70/30)", RSI_PERIOD + 1, rsi_levels),
    Rule("ema_cross", "Cruce EMA 20/50", TREND_SLOW + CROSS_LOOKBACK, ema_crossover),
    Rule("macd_cross", "Cruce MACD/señal", 26 + 9 + CROSS_LOOKBACK, macd_crossover),
    Rule("volume", "Volumen anormal", VOLUME_WINDOW + 1, abnormal_volume),
    Rule(
        "volatility",
        "Cambio de volatilidad (ATR 14)",
        ATR_PERIOD + VOL_LOOKBACK + 1,
        volatility_change,
    ),
    Rule("breakout", "Rupturas de 20 barras", BREAKOUT_WINDOW + 1, breakout),
)
