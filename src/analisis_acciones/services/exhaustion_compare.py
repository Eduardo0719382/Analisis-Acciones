"""Exhaustion signs compared across several assets: where they anticipated turns and where not.

For every asset the record of past up-trend exhaustion (did the price fall afterwards?) and
of down-trend exhaustion (did it rise?) is measured with ``analysis.exhaustion.history`` and
read with ``record_reading``, using the same thresholds as the rest of the program. Each asset
only describes its own past; nothing here is a forecast.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from html import escape

import pandas as pd

from analisis_acciones.analysis.exhaustion import (
    DEFAULT_PARAMS,
    DOWN,
    HORIZONS,
    MIN_BARS,
    READ_CONTINUE,
    READ_FEW,
    READ_MIXED,
    READ_NO_EDGE,
    READ_NONE,
    READ_USEFUL,
    UP,
    Assessment,
    Outcome,
    Params,
    assess,
    history,
    record_reading,
)
from analisis_acciones.data.export import safe_cell
from analisis_acciones.models.errors import AppError
from analisis_acciones.models.market import Interval
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scan_report import STYLE, num

logger = logging.getLogger(__name__)

MAX_SYMBOLS = 200
MAIN_HORIZON = HORIZONS[-1]

#: Short labels of each reading, per direction (rises = exhaustion of up-trends).
READING_LABELS = {
    READ_USEFUL: {UP: "Anticipó bajadas", DOWN: "Anticipó rebotes"},
    READ_CONTINUE: {UP: "La subida siguió", DOWN: "La bajada siguió"},
    READ_NO_EDGE: {UP: "Sin diferencia", DOWN: "Sin diferencia"},
    READ_MIXED: {UP: "Contradictorio", DOWN: "Contradictorio"},
    READ_FEW: {UP: "Pocos casos", DOWN: "Pocos casos"},
    READ_NONE: {UP: "Sin historial", DOWN: "Sin historial"},
}


@dataclass(frozen=True)
class DirectionRecord:
    outcomes: list[Outcome]
    reading: str

    def at(self, horizon: int) -> Outcome | None:
        return next((o for o in self.outcomes if o.horizon == horizon), None)


@dataclass(frozen=True)
class AssetExhaustion:
    symbol: str
    now: Assessment  # signs at the last closed bar
    rises: DirectionRecord  # exhaustion of up-trends: did the price fall afterwards?
    falls: DirectionRecord  # exhaustion of down-trends: did the price rise afterwards?
    first: date | None
    last: date | None
    bars: int

    def record(self, direction: str) -> DirectionRecord:
        return self.rises if direction == UP else self.falls


@dataclass
class ExhaustionComparison:
    rows: list[AssetExhaustion] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    params: Params = DEFAULT_PARAMS
    cancelled: bool = False

    def by_reading(self, direction: str) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {code: [] for code in READING_LABELS}
        for row in self.rows:
            groups[row.record(direction).reading].append(row.symbol)
        return groups


def analyse_bars(symbol: str, bars: pd.DataFrame,
                 params: Params = DEFAULT_PARAMS) -> AssetExhaustion:  # fmt: skip
    """Record of one asset's completed daily bars."""
    if len(bars) < MIN_BARS:
        raise ValueError(f"se necesitan al menos {MIN_BARS} sesiones (hay {len(bars)})")
    rises = history(bars, UP, params)
    falls = history(bars, DOWN, params)
    index = pd.DatetimeIndex(bars.index)
    return AssetExhaustion(
        symbol, assess(bars, params),
        DirectionRecord(rises, record_reading(rises)),
        DirectionRecord(falls, record_reading(falls)),
        index[0].date(), index[-1].date(), len(bars),
    )  # fmt: skip


def compare_exhaustion(
    market: MarketDataService, symbols: list[str], params: Params = DEFAULT_PARAMS,
    progress: Callable[[int, int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ExhaustionComparison:  # fmt: skip
    """Cache-first loads of daily bars; problems are reported per symbol, never raised."""
    result = ExhaustionComparison(params=params)
    targets = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))[:MAX_SYMBOLS]
    for done, symbol in enumerate(targets):
        if cancelled is not None and cancelled():
            result.cancelled = True
            return result
        if progress is not None:
            progress(done, len(targets), symbol)
        try:
            loaded = market.load(symbol, Interval.D1)
            bars = loaded.series.bars
            if loaded.session_in_progress:
                bars = bars.iloc[:-1]  # completed bars only
            result.rows.append(analyse_bars(loaded.series.symbol, bars, params))
        except AppError as exc:
            result.problems.append(f"{symbol}: {exc.user_message}")
        except (ValueError, ArithmeticError, KeyError) as exc:
            logger.exception("Exhaustion comparison of %s failed", symbol)
            result.problems.append(f"{symbol}: no se pudo analizar ({exc})")
    return result


def now_text(a: Assessment) -> str:
    """Current situation in a few words."""
    if a.direction is None:
        return "Sin tendencia clara"
    trend = "Subida" if a.direction == UP else "Bajada"
    if a.signalled:
        return f"{trend} con agotamiento ({a.met}/{a.available})"
    return f"{trend} sin agotamiento ({a.met}/{a.available})"


# CSV --------------------------------------------------------------------------------------
def comparison_csv(result: ExhaustionComparison) -> str:
    """One row per asset; both horizons and both directions (formula-safe cells)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    header = ["ticker", "desde", "hasta", "sesiones", "situacion_actual"]
    for name in ("subidas", "bajadas"):
        for h in HORIZONS:
            header += [f"{name}_casos_{h}", f"{name}_giro_pct_{h}", f"{name}_normal_pct_{h}",
                       f"{name}_mediana_pct_{h}", f"{name}_p_valor_{h}"]  # fmt: skip
        header.append(f"{name}_lectura")
    writer.writerow(header)
    for row in sorted(result.rows, key=lambda r: r.symbol):
        cells: list[object] = [row.symbol, row.first, row.last, row.bars, now_text(row.now)]
        for direction in (UP, DOWN):
            record = row.record(direction)
            for h in HORIZONS:
                o = record.at(h)
                cells += [
                    o.events if o else "", _plain(o.against_pct if o else None),
                    _plain(o.baseline_against_pct if o else None),
                    _plain(o.median_return if o else None),
                    _plain(o.p_value if o else None, 4),
                ]  # fmt: skip
            cells.append(READING_LABELS[record.reading][direction])
        writer.writerow([safe_cell(c) for c in cells])
    return buffer.getvalue()


def _plain(value: float | None, decimals: int = 2) -> str:
    return "" if value is None else f"{value:.{decimals}f}"


# HTML -------------------------------------------------------------------------------------
_EXTRA_STYLE = """
.tiles.two { grid-template-columns: repeat(2, 1fr); }
.group { margin: 4px 0; } .group b { display: inline-block; min-width: 150px; }
.pair { display: grid; grid-template-columns: 74px 1fr 42px; gap: 2px 6px; align-items: center;
  font-size: 11.5px; min-width: 190px; }
.bar { height: 7px; border-radius: 0 4px 4px 0; background: var(--flat); min-width: 2px; }
.bar.down { background: var(--down); } .bar.up { background: var(--up); }
.read { white-space: nowrap; border-radius: 999px; padding: 2px 8px; background: var(--flat-bg); }
.read.useful { background: var(--up-bg); } .read.continue { background: var(--down-bg); }
@media screen and (max-width: 760px) { .tiles.two { grid-template-columns: 1fr; } }
"""


def _bars_cell(o: Outcome | None, direction: str) -> str:
    if o is None or not o.events or o.against_pct is None:
        return '<span class="muted">sin casos</span>'
    css = "down" if direction == UP else "up"
    base = o.baseline_against_pct
    base_row = (f'<span>Día normal</span><div class="bar" style="width:{base:.0f}%"></div>'
                f'<span class="n">{num(base, 0)} %</span>') if base is not None else ""  # fmt: skip
    return (
        f'<div class="pair"><span>Tras la señal</span>'
        f'<div class="bar {css}" style="width:{o.against_pct:.0f}%"></div>'
        f'<span class="n">{num(o.against_pct, 0)} %</span>{base_row}</div>'
    )


def _reading_chip(code: str, direction: str) -> str:
    css = {READ_USEFUL: "useful", READ_CONTINUE: "continue"}.get(code, "")
    return f'<span class="read {css}">{escape(READING_LABELS[code][direction])}</span>'


def _p_text(o: Outcome | None) -> str:
    p = o.p_value if o else None
    return "—" if p is None else ("< 0,001" if p < 0.001 else num(p, 3))


def _groups(result: ExhaustionComparison, direction: str) -> str:
    lines = []
    for code, symbols in result.by_reading(direction).items():
        if symbols:
            names = ", ".join(escape(s) for s in symbols)
            lines.append(f'<div class="group"><b>{escape(READING_LABELS[code][direction])}'
                         f" ({len(symbols)})</b> {names}</div>")  # fmt: skip
    return "".join(lines) or '<p class="muted">Sin resultados.</p>'


def _table(result: ExhaustionComparison, direction: str) -> str:
    h = MAIN_HORIZON
    moved = "bajó" if direction == UP else "subió"
    body = []
    for row in sorted(result.rows, key=lambda r: r.symbol):
        record = row.record(direction)
        o = record.at(h)
        median = num(o.median_return, 1, sign=True) + " %" if o and o.median_return is not None \
            else "—"  # fmt: skip
        body.append(
            f"<tr><td><b>{escape(row.symbol)}</b><br><span class=muted>"
            f"{escape(now_text(row.now))}</span></td>"
            f"<td class=n>{o.events if o else 0}</td>"
            f"<td>{_bars_cell(o, direction)}</td><td class=n>{median}</td>"
            f"<td class=n>{_p_text(o)}</td><td>{_reading_chip(record.reading, direction)}</td></tr>"
        )
    return (
        f"<table><tr><th>Activo · ahora</th><th>Casos</th><th>% de veces que {moved} a {h} "
        "sesiones</th><th>Variación mediana</th><th>p (azar)</th><th>Lectura</th></tr>"
        + "".join(body)
        + "</table>"
    )


def comparison_html(result: ExhaustionComparison, generated: datetime) -> str:
    p = result.params
    useful_up = result.by_reading(UP)[READ_USEFUL]
    useful_down = result.by_reading(DOWN)[READ_USEFUL]
    problems = ""
    if result.problems:
        items = "".join(f"<li>{escape(x)}</li>" for x in result.problems)
        problems = f'<div class="problems"><b>No analizados:</b><ul>{items}</ul></div>'
    last = max((r.last for r in result.rows if r.last), default=None)
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agotamiento en varios activos</title>
<style>{STYLE}{_EXTRA_STYLE}</style></head>
<body>
<h1>Señales de agotamiento en varios activos</h1>
<p class="intro">{len(result.rows)} activos con datos diarios hasta el
{last.strftime("%d/%m/%Y") if last else "—"} · generado el {generated.strftime("%d/%m/%Y %H:%M")}.
Para cada activo se buscan todas las veces pasadas con {p.threshold} o más señales de
agotamiento (sin solapar, usando solo los datos de cada fecha) y se compara qué pasó
{MAIN_HORIZON} sesiones después con un día cualquiera de la misma tendencia. Es una descripción
del pasado de cada activo, <b>no una predicción ni una recomendación</b>.</p>
<p class="intro small">Umbrales: RSI {num(p.rsi_high, 0)} / {num(p.rsi_low, 0)} ·
{num(p.atr_multiple, 1)} ATR · volumen bajo el {num(p.volume_ratio * 100, 0)} % ·
{num(p.z_limit, 1)} desviaciones · {p.threshold} señales.</p>
<div class="tiles two">
  <div class="tile down"><div class="big">{len(useful_up)}</div>
  <div>activos donde el agotamiento de las subidas anticipó bajadas</div>
  <div class="muted small">{escape(", ".join(useful_up[:12])) or "—"}</div></div>
  <div class="tile up"><div class="big">{len(useful_down)}</div>
  <div>activos donde el agotamiento de las bajadas anticipó rebotes</div>
  <div class="muted small">{escape(", ".join(useful_down[:12])) or "—"}</div></div>
</div>
<div class="howto"><b>Cómo leerlo</b><ul>
<li><b>Barra de color:</b> % de veces que el precio giró tras la señal. <b>Barra gris:</b> lo
mismo en un día cualquiera de la misma tendencia. Solo si la de color es claramente más larga
la señal aportó algo en ese activo.</li>
<li><b>p (azar):</b> probabilidad de ver una diferencia así por pura suerte. Por debajo de 0,05
se considera poco probable que sea azar.</li>
<li><b>Lectura:</b> «Anticipó…» exige al menos 10 casos, 10 puntos de diferencia y p &lt; 0,05
en algún plazo (10 o 20 sesiones) sin que el otro diga lo contrario.</li></ul></div>
{problems}
<h2 class="section-title">Agotamiento de las subidas (¿bajó después?)</h2>
{_groups(result, UP)}
{_table(result, UP)}
<h2 class="section-title newpage">Agotamiento de las bajadas (¿subió después?)</h2>
{_groups(result, DOWN)}
{_table(result, DOWN)}
<footer>Análisis de Acciones · Datos: Yahoo Finance (pueden contener retrasos o errores).
Comparar muchos activos aumenta la probabilidad de encontrar alguno «que funcionó» por
casualidad. No es asesoramiento financiero.</footer>
</body></html>"""
