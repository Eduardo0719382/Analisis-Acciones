"""Weekly summary: exhaustion signs that appeared in the last 7 days, with each asset's record.

A sign "appears" on the first bar of a run of exhaustion signals (the same rule as the chart
markers). For each one the summary shows how the asset moved over the week and what followed
the same signs in its own past (``history`` and ``record_reading``). Completed daily bars
only; nothing here is a forecast.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from html import escape

import pandas as pd

from analisis_acciones.analysis.exhaustion import (
    DEFAULT_PARAMS,
    DOWN,
    HORIZONS,
    MIN_BARS,
    READ_CONTINUE,
    READ_USEFUL,
    UP,
    Outcome,
    Params,
    history,
    record_reading,
    signal_series,
)
from analisis_acciones.models.errors import AppError
from analisis_acciones.models.market import Interval
from analisis_acciones.services.exhaustion_compare import MAX_SYMBOLS, READING_LABELS
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scan_report import STYLE, num

logger = logging.getLogger(__name__)

WEEK_DAYS = 7
MAIN_HORIZON = HORIZONS[-1]


@dataclass(frozen=True)
class WeeklySignal:
    symbol: str
    started: date  # first bar of the run inside the week
    direction: str  # UP = exhaustion of a rise, DOWN = of a fall
    met: int  # conditions met on that bar
    active: bool  # still signalled on the last closed bar
    reading: str  # record_reading of this direction in the asset's past
    outcome: Outcome | None  # record at MAIN_HORIZON
    week_change_pct: float | None  # close change over the week


@dataclass
class WeeklySummary:
    start: date
    end: date
    params: Params = DEFAULT_PARAMS
    signals: list[WeeklySignal] = field(default_factory=list)
    quiet: list[str] = field(default_factory=list)  # analysed, no new signs this week
    problems: list[str] = field(default_factory=list)
    cancelled: bool = False

    @property
    def analysed(self) -> int:
        return len({s.symbol for s in self.signals}) + len(self.quiet)


def week_signals(symbol: str, bars: pd.DataFrame, today: date,
                 params: Params = DEFAULT_PARAMS) -> list[WeeklySignal]:  # fmt: skip
    """Signs that started in the ``WEEK_DAYS`` days up to ``today`` (completed bars)."""
    bars = bars[pd.DatetimeIndex(bars.index) <= pd.Timestamp(today)]  # nothing after today
    if len(bars) < MIN_BARS:
        raise ValueError(f"se necesitan al menos {MIN_BARS} sesiones (hay {len(bars)})")
    signals = signal_series(bars, params)
    index = pd.DatetimeIndex(bars.index)
    since = pd.Timestamp(today - timedelta(days=WEEK_DAYS - 1))
    in_week = index >= since
    values = signals.to_numpy()
    closes = bars["close"].to_numpy(dtype=float)
    first = int(in_week.argmax()) if in_week.any() else len(bars)
    change = (closes[-1] / closes[first - 1] - 1) * 100 if 0 < first < len(bars) else None
    records = {}
    found = []
    for i in range(first, len(bars)):
        value, before = int(values[i]), int(values[i - 1]) if i else 0
        if not value or (before and (before > 0) == (value > 0)):
            continue  # no sign, or the run started before
        direction = UP if value > 0 else DOWN
        if direction not in records:
            records[direction] = history(bars, direction, params)
        outcomes = records[direction]
        last = int(values[-1])
        found.append(WeeklySignal(
            symbol, index[i].date(), direction, abs(value),
            bool(last) and (last > 0) == (value > 0),
            record_reading(outcomes),
            next((o for o in outcomes if o.horizon == MAIN_HORIZON), None),
            change,
        ))  # fmt: skip
    return found


def weekly_summary(
    market: MarketDataService, symbols: list[str], today: date,
    params: Params = DEFAULT_PARAMS,
    progress: Callable[[int, int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> WeeklySummary:  # fmt: skip
    """Cache-first loads; problems are reported per symbol, never raised."""
    summary = WeeklySummary(today - timedelta(days=WEEK_DAYS - 1), today, params)
    targets = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))[:MAX_SYMBOLS]
    for done, symbol in enumerate(targets):
        if cancelled is not None and cancelled():
            summary.cancelled = True
            break
        if progress is not None:
            progress(done, len(targets), symbol)
        try:
            loaded = market.load(symbol, Interval.D1)
            bars = loaded.series.bars
            if loaded.session_in_progress:
                bars = bars.iloc[:-1]
            found = week_signals(loaded.series.symbol, bars, today, params)
        except AppError as exc:
            summary.problems.append(f"{symbol}: {exc.user_message}")
            continue
        except (ValueError, ArithmeticError, KeyError) as exc:
            logger.exception("Weekly summary of %s failed", symbol)
            summary.problems.append(f"{symbol}: no se pudo analizar ({exc})")
            continue
        if found:
            summary.signals.extend(found)
        else:
            summary.quiet.append(loaded.series.symbol)
    summary.signals.sort(key=lambda s: (s.reading != READ_USEFUL, s.started, s.symbol))
    return summary


def signal_sentence(s: WeeklySignal) -> str:
    what = "la subida" if s.direction == UP else "la bajada"
    state = "siguen activas" if s.active else "ya no están activas"
    return (f"Señales de agotamiento de {what} desde el {s.started:%d/%m} "
            f"({s.met} condiciones); {state}.")  # fmt: skip


def record_sentence(s: WeeklySignal) -> str:
    o = s.outcome
    if o is None or not o.events or o.against_pct is None:
        return "Sin casos anteriores comparables en este activo."
    moved = "bajó" if s.direction == UP else "subió"
    base = "—" if o.baseline_against_pct is None else f"{num(o.baseline_against_pct, 0)} %"
    return (f"Antes, {MAIN_HORIZON} sesiones después {moved} en {o.against} de {o.events} casos "
            f"({num(o.against_pct, 0)} %; un día normal: {base}).")  # fmt: skip


# HTML -------------------------------------------------------------------------------------
_EXTRA_STYLE = """
.tiles.three { grid-template-columns: repeat(3, 1fr); }
.signal { border: 1px solid var(--border); border-left: 6px solid var(--flat);
  border-radius: 10px; background: var(--card); padding: 12px 16px; margin: 10px 0;
  break-inside: avoid; }
.signal.up { border-left-color: var(--down); } .signal.down { border-left-color: var(--up); }
.signal h3 { margin: 0 0 4px; font-size: 16px; text-transform: none; letter-spacing: 0;
  color: var(--ink); }
.read { white-space: nowrap; border-radius: 999px; padding: 2px 8px; background: var(--flat-bg);
  font-size: 12.5px; }
.read.useful { background: var(--up-bg); } .read.continue { background: var(--down-bg); }
@media screen and (max-width: 760px) { .tiles.three { grid-template-columns: 1fr; } }
"""


def _card(s: WeeklySignal) -> str:
    css = {READ_USEFUL: "useful", READ_CONTINUE: "continue"}.get(s.reading, "")
    label = READING_LABELS[s.reading][s.direction]
    change = ("—" if s.week_change_pct is None
              else f"{num(s.week_change_pct, 1, sign=True)} %")  # fmt: skip
    arrow = "▼" if s.direction == UP else "▲"
    return (
        f'<div class="signal {"up" if s.direction == UP else "down"}">'
        f'<h3>{arrow} {escape(s.symbol)} <span class="read {css}">{escape(label)}</span></h3>'
        f"<div>{escape(signal_sentence(s))} Variación de la semana: {change}.</div>"
        f'<div class="muted">{escape(record_sentence(s))}</div></div>'
    )


def weekly_html(summary: WeeklySummary, generated: datetime) -> str:
    useful = sorted({s.symbol for s in summary.signals if s.reading == READ_USEFUL})
    p = summary.params
    problems = ""
    if summary.problems:
        items = "".join(f"<li>{escape(x)}</li>" for x in summary.problems)
        problems = f'<div class="problems"><b>No analizados:</b><ul>{items}</ul></div>'
    cards = "".join(_card(s) for s in summary.signals) or (
        '<p class="muted">Ningún activo de la lista mostró señales de agotamiento nuevas esta '
        "semana.</p>"
    )
    quiet = ", ".join(escape(q) for q in summary.quiet) or "—"
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resumen semanal de agotamiento</title>
<style>{STYLE}{_EXTRA_STYLE}</style></head>
<body>
<h1>Resumen semanal de agotamiento</h1>
<p class="intro">Del {summary.start:%d/%m/%Y} al {summary.end:%d/%m/%Y} · {summary.analysed}
activos analizados con velas diarias cerradas · generado el
{generated.strftime("%d/%m/%Y %H:%M")}. Señales que empezaron esta semana y qué pasó después
de las mismas señales en el pasado de cada activo. Es una descripción de los datos, <b>no una
predicción ni una recomendación</b>.</p>
<p class="intro small">Umbrales: RSI {num(p.rsi_high, 0)} / {num(p.rsi_low, 0)} ·
{num(p.atr_multiple, 1)} ATR · volumen bajo el {num(p.volume_ratio * 100, 0)} % ·
{num(p.z_limit, 1)} desviaciones · {p.threshold} señales.</p>
<div class="tiles three">
  <div class="tile"><div class="big">{len(summary.signals)}</div>
  <div>señales nuevas esta semana</div></div>
  <div class="tile"><div class="big">{len(useful)}</div>
  <div>en activos donde antes anticiparon giros</div>
  <div class="muted small">{escape(", ".join(useful)) or "—"}</div></div>
  <div class="tile"><div class="big">{len(summary.quiet)}</div>
  <div>activos sin señales nuevas</div></div>
</div>
<div class="howto"><b>Cómo leerlo</b><ul>
<li><b>▼ franja roja:</b> señales de agotamiento de una subida. <b>▲ franja azul:</b> de una
bajada.</li>
<li><b>Etiqueta:</b> «Anticipó…» solo si en ese activo las señales precedieron giros claramente
más a menudo que un día normal (10 casos o más, 10 puntos de diferencia y poca probabilidad de
azar). Aun así, muchas veces la tendencia continuó.</li></ul></div>
{problems}
<h2 class="section-title">Señales nuevas</h2>
{cards}
<h2 class="section-title">Sin señales nuevas</h2>
<p>{quiet}</p>
<footer>Análisis de Acciones · Datos: Yahoo Finance (pueden contener retrasos o errores). No es
asesoramiento financiero.</footer>
</body></html>"""
