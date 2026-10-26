"""What an agent sees about each asset: the program's own tools, summarized as JSON.

Nothing is recalculated here: rules, exhaustion, Elliott, chart patterns and support /
resistance come from ``services.scanner.scan_bars`` (the same code as the scanner and the
chart), the projection from ``forecast.projection`` and fundamentals from the market data
service. Only completed bars are analysed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

from analisis_acciones.indicators.functions import sma
from analisis_acciones.lab import costs
from analisis_acciones.models.errors import AppError
from analisis_acciones.models.market import Fundamentals
from analisis_acciones.services.scanner import scan_bars

READINGS = {
    "none": "sin historial comparable",
    "few": "muy pocos casos en el historial",
    "mixed": "el historial apunta en sentidos opuestos",
    "useful": "en este activo la tendencia giró más a menudo de lo normal tras estas señales",
    "continue": "en este activo la tendencia siguió más a menudo de lo normal",
    "no_edge": "diferencia pequeña o posible casualidad",
}
#: Bars projected ahead for each analysis timeframe.
HORIZON = {"1h": 24, "4h": 18, "1d": 20, "1w": 8, "1mo": 6}
TIMEFRAME_SPAN = {"1h": timedelta(hours=1), "4h": timedelta(hours=4), "1d": timedelta(days=1)}


def alpaca_bars_frame(bars: list[dict[str, Any]], timeframe: str, now: datetime) -> pd.DataFrame:
    """Alpaca bars as the program's OHLCV frame, without the bar still in progress."""
    if not bars:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(
        {"open": [b.get("o") for b in bars], "high": [b.get("h") for b in bars],
         "low": [b.get("l") for b in bars], "close": [b.get("c") for b in bars],
         "volume": [b.get("v") for b in bars]},
        index=pd.DatetimeIndex(pd.to_datetime([str(b.get("t")) for b in bars], utc=True)),
    ).astype(float)  # fmt: skip
    frame = frame[~frame.index.duplicated()].sort_index().dropna(subset=["close"])
    span = TIMEFRAME_SPAN.get(timeframe)
    if span is not None and len(frame) and frame.index[-1].to_pydatetime() + span > now:
        frame = frame.iloc[:-1]
    if timeframe == "1d":
        frame.index = pd.DatetimeIndex(frame.index).tz_convert(None).normalize()
    # the program's bar schema (crypto has no adjustments)
    frame["adj_close"], frame["dividends"], frame["splits"] = frame["close"], 0.0, 0.0
    return frame


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None or not np.isfinite(x) else round(float(x), nd)


def summarize(
    symbol: str, bars: pd.DataFrame, timeframe: str, tools: tuple[str, ...]
) -> dict[str, Any]:
    """The tools' reading of one asset on completed ``bars``."""
    out: dict[str, Any] = {"marco": timeframe, "barras": len(bars)}
    if len(bars) < 2:
        out["aviso"] = "sin datos suficientes"
        return out
    close = bars["close"]
    last = float(close.iloc[-1])
    out |= {"cierre": _r(last, 6), "fecha_ultima_barra": str(bars.index[-1])[:16],
            "cambio_ultima_barra_pct": _r((last / float(close.iloc[-2]) - 1) * 100)}  # fmt: skip
    for n in (20, 50, 200):
        if len(close) >= n:
            out[f"sobre_sma{n}"] = bool(last > float(sma(close, n).iloc[-1]))
    for back in (5, 20):
        if len(close) > back:
            out[f"rend_{back}_barras_pct"] = _r((last / float(close.iloc[-1 - back]) - 1) * 100)
    try:
        row = scan_bars(symbol, bars)
    except (ValueError, ArithmeticError, KeyError, AppError) as exc:
        out["aviso"] = f"análisis completo no disponible: {exc}"
        return out
    out["rsi14"] = _r(row.rsi14, 1)
    if "reglas" in tools:
        out["senales_alcistas"] = list(row.bullish)
        out["senales_bajistas"] = list(row.bearish)
    if "agotamiento" in tools:
        if row.exhaustion:
            side = "subida" if row.exhaustion > 0 else "caída"
            out["agotamiento"] = (f"agotamiento de la {side}: {abs(row.exhaustion)} de "
                                  f"{row.exhaustion_total} señales")  # fmt: skip
            out["agotamiento_historial"] = READINGS.get(row.exhaustion_reading,
                                                        row.exhaustion_reading)  # fmt: skip
        else:
            out["agotamiento"] = "sin señales de agotamiento"
    if "elliott" in tools:
        out["elliott"] = row.elliott or "sin conteo en curso"
    if "patrones" in tools:
        out["patrones"] = list(row.patterns)
        out["soporte"] = _r(row.support, 6)
        out["distancia_soporte_pct"] = _r(row.support_pct)
        out["resistencia"] = _r(row.resistance, 6)
        out["distancia_resistencia_pct"] = _r(row.resistance_pct)
    if "proyeccion" in tools:
        out["proyeccion"] = _projection(close, timeframe)
    return out


def _projection(close: pd.Series, timeframe: str) -> dict[str, Any] | str:
    from analisis_acciones.forecast.projection import volatility_cone

    horizon = HORIZON.get(timeframe, 20)
    lookback = min(252, len(close) - 1)
    if lookback < 20:
        return "historial corto para proyectar"
    try:
        cone = volatility_cone(close.to_numpy(), horizon, lookback)
    except AppError as exc:
        return exc.user_message
    bands = cone.at_horizon()
    base = cone.base_price
    return {"barras_adelante": horizon,
            **{f"{k}_pct": _r((v / base - 1) * 100)
               for k, v in sorted(bands.items())},
            "nota": "rango por volatilidad, sin tendencia supuesta; no es una predicción",
            }  # fmt: skip


def fundamentals_summary(f: Fundamentals) -> dict[str, Any]:
    def pct(v: float | None) -> float | None:
        return None if v is None else round(v * 100, 1)

    return {
        "per": _r(f.trailing_pe, 1), "per_futuro": _r(f.forward_pe, 1),
        "precio_valor_contable": _r(f.price_to_book, 2), "dividendo_pct": pct(f.dividend_yield),
        "margen_neto_pct": pct(f.profit_margin), "roe_pct": pct(f.return_on_equity),
        "crecimiento_ingresos_pct": pct(f.revenue_growth),
        "crecimiento_beneficios_pct": pct(f.earnings_growth),
        "capitalizacion_miles_millones": _r((f.market_cap or 0) / 1e9, 1) if f.market_cap else None,
        "proximos_resultados": str(f.earnings_date) if f.earnings_date else None,
    }  # fmt: skip


def cost_line(symbol: str, crypto: bool, price: float | None,
              quote: tuple[float | None, float | None] | None,
              day: Any) -> dict[str, Any]:  # fmt: skip
    bid, ask = quote or (None, None)
    spread, measured = costs.effective_spread(crypto, bid, ask)
    out: dict[str, Any] = {"bid": bid, "ask": ask, "spread_pct": _r(spread, 3)}
    if not measured:
        out["spread_nota"] = ("cotización IEX ausente o poco fiable: se usa "
                              f"{costs.STOCK_SPREAD_FALLBACK:g} %" if not crypto
                              else "sin cotización")  # fmt: skip
    if price:
        out["coste_ida_vuelta_pct"] = _r(costs.round_trip_cost_pct(crypto, price, spread, day), 3)
    return out
