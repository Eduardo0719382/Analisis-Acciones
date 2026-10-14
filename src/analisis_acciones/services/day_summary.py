"""'Resumen del día': the watchlist at a glance plus recent alerts and scan news.

A single self-contained HTML page (no scripts) shown inside the program.
Tickers link to ``http://abrir.local/<TICKER>``; the page that displays it
intercepts those links to open the symbol on the chart (they never reach
the network). Pure functions apart from the cache-first data loading.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from urllib.parse import quote

from analisis_acciones.alerts.service import AlertEvent
from analisis_acciones.models.errors import AppError
from analisis_acciones.models.market import Interval
from analisis_acciones.services import company_calendar
from analisis_acciones.services.company_calendar import CalendarEntry
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.scan_report import STYLE, num

logger = logging.getLogger(__name__)

OPEN_PREFIX = "http://abrir.local/"
HISTORY_BARS = 60
DAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


@dataclass(frozen=True)
class SummaryItem:
    symbol: str
    close: float | None
    change_pct: float | None
    as_of: date | None
    history: tuple[float, ...] = ()
    stale: bool = False
    error: str | None = None


def load_items(market: MarketDataService, symbols: list[str]) -> list[SummaryItem]:
    """Last close, daily change and recent closes per symbol (cache-first, never raises)."""
    items = []
    for symbol in symbols:
        try:
            result = market.load(symbol, Interval.D1)
        except AppError as exc:
            items.append(SummaryItem(symbol, None, None, None, error=exc.user_message))
            continue
        closes = result.series.bars["close"]
        last = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else None
        items.append(SummaryItem(
            result.series.symbol, last, (last / prev - 1) * 100 if prev else None,
            result.series.last_date, tuple(float(v) for v in closes.tail(HISTORY_BARS)),
            result.stale,
        ))  # fmt: skip
    return items


def load_calendar(market: MarketDataService, symbols: list[str],
                  today: date) -> list[CalendarEntry]:  # fmt: skip
    """Upcoming earnings/dividend dates from stored fundamentals only (no network)."""
    try:
        stored = market.cached_fundamentals([s.strip().upper() for s in symbols])
    except Exception as exc:  # the summary must still show
        logger.warning("Could not read stored fundamentals: %s", exc)
        return []
    return company_calendar.upcoming(stored, today)


def _calendar_rows(entries: list[CalendarEntry], today: date) -> str:
    if not entries:
        return (
            '<li class="flat">Sin fechas en los próximos '
            f"{company_calendar.UPCOMING_DAYS} días entre los datos guardados. Las fechas se "
            "guardan al abrir la pestaña «Fundamentales» de cada activo o al escanear con "
            "fundamentales.</li>"
        )
    rows = []
    for e in entries:
        estimated = " (estimada)" if e.estimated else ""
        rows.append(
            f'<li><a href="{open_link(e.symbol)}"><b>{escape(e.symbol)}</b></a> · {e.label}'
            f"{estimated}: {company_calendar.date_text(e)} · "
            f"{company_calendar.when(e, today)}</li>"
        )
    return "".join(rows)


def open_link(symbol: str) -> str:
    return OPEN_PREFIX + quote(symbol, safe="")


def _spark(values: tuple[float, ...], css: str, width: int = 160, height: int = 36) -> str:
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    pts = " ".join(
        f"{2 + i * (width - 4) / (len(values) - 1):.1f},{3 + (high - v) * (height - 6) / span:.1f}"
        for i, v in enumerate(values)
    )
    return (f'<svg class="mini" viewBox="0 0 {width} {height}" aria-hidden="true">'
            f'<polyline class="{css}" points="{pts}"/></svg>')  # fmt: skip


def _change_bar(change: float | None, scale: float) -> str:
    if change is None:
        return '<div class="cbar"></div>'
    width = min(abs(change) / scale, 1) * 50
    css = "up" if change > 0 else "down"
    return (f'<div class="cbar" title="{num(change, 2, sign=True)} %"><div class="zero"></div>'
            f'<div class="fill {css}" style="width:{width:.1f}%"></div></div>')  # fmt: skip


def _card(item: SummaryItem, scale: float) -> str:
    link = escape(open_link(item.symbol), quote=True)
    if item.error or item.close is None:
        error = escape(item.error or "Sin datos")
        return (f'<a class="wcard" href="{link}"><b>{escape(item.symbol)}</b>'
                f'<div class="muted small">{error}</div></a>')  # fmt: skip
    change = item.change_pct
    css = "up" if (change or 0) > 0 else "down" if (change or 0) < 0 else "flat"
    icon = "▲" if css == "up" else "▼" if css == "down" else "●"
    stale = ' · <span class="muted">datos guardados</span>' if item.stale else ""
    return f"""<a class="wcard {css}" href="{link}" title="Abrir {escape(item.symbol)} en el gráfico">
  <div class="whead"><b>{escape(item.symbol)}</b><span>{num(item.close)}</span></div>
  <div class="wchg"><i class="{css}">{icon}</i> {num(change, 2, sign=True)} %
    <span class="muted small">· {item.as_of.strftime("%d/%m") if item.as_of else ""}{stale}</span></div>
  {_change_bar(change, scale)}
  {_spark(item.history, css)}
</a>"""  # noqa: E501


def _event_row(event: AlertEvent) -> str:
    css = "up" if event.message.startswith("▲") else "down" \
        if event.message.startswith("▼") else "flat"  # fmt: skip
    text = event.message.lstrip("▲▼● ")  # the row's marker already shows the direction
    when = event.triggered_at.astimezone().strftime("%d/%m %H:%M")
    link = escape(open_link(event.symbol), quote=True)
    who = escape(event.description)
    return (f'<li class="{css}"><span class="when">{when}</span> '
            f'<a href="{link}"><b>{who}</b></a> — {escape(text)}</li>')  # fmt: skip


SUMMARY_STYLE = """
.wgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; }
a.wcard { display: block; text-decoration: none; color: var(--ink); background: var(--card);
  border: 1px solid var(--border); border-top: 4px solid var(--flat); border-radius: 10px;
  padding: 10px 12px; }
a.wcard:hover { border-color: var(--ink-2); }
a.wcard.up { border-top-color: var(--up); } a.wcard.down { border-top-color: var(--down); }
.whead { display: flex; justify-content: space-between; font-size: 16px; }
.wchg { font-size: 13px; margin: 2px 0 6px; color: var(--ink-2); }
i.up, i.down, i.flat { font-style: normal; } i.up { color: var(--up); }
i.down { color: var(--down); } i.flat { color: var(--flat); }
.cbar { position: relative; height: 8px; background: var(--flat-bg); border-radius: 4px; }
.cbar .zero { position: absolute; left: 50%; top: -2px; bottom: -2px; width: 2px;
  background: var(--ink-2); }
.cbar .fill { position: absolute; top: 1px; height: 6px; border-radius: 3px; }
.cbar .fill.up { left: 50%; background: var(--up); }
.cbar .fill.down { right: 50%; background: var(--down); }
.mini { width: 100%; height: 36px; display: block; margin-top: 6px; }
.mini polyline { fill: none; stroke-width: 1.6; stroke: var(--ink-2); }
.mini .up { stroke: var(--up); } .mini .down { stroke: var(--down); }
.events { list-style: none; padding: 0; margin: 0; }
.events li { padding: 7px 10px; border-bottom: 1px solid var(--border); font-size: 13px; }
.events li::before { content: "● "; color: var(--flat); }
.events li.up::before { content: "▲ "; color: var(--up); }
.events li.down::before { content: "▼ "; color: var(--down); }
.events a { color: var(--ink); text-decoration: none; }
.when { color: var(--muted); font-variant-numeric: tabular-nums; }
.status { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12.5px;
  background: var(--flat-bg); margin-left: 8px; vertical-align: 4px; }
.status.open { background: var(--up-bg); }
"""


def summary_html(items: list[SummaryItem], events: list[AlertEvent], now: datetime,
                 is_open: bool, list_name: str = "",
                 calendar: list[CalendarEntry] | None = None) -> str:  # fmt: skip
    ok = [i for i in items if i.change_pct is not None]
    up = sorted((i for i in ok if (i.change_pct or 0) > 0), key=lambda i: -(i.change_pct or 0))
    down = sorted((i for i in ok if (i.change_pct or 0) < 0), key=lambda i: i.change_pct or 0)
    scale = max([abs(i.change_pct or 0) for i in ok] + [1.0])
    local = now.astimezone()
    title_day = f"{DAYS[local.weekday()]} {local:%d/%m/%Y}"
    status = ('<span class="status open">● Mercado de EE. UU. abierto</span>' if is_open
              else '<span class="status">● Mercado de EE. UU. cerrado</span>')  # fmt: skip

    def names(rows: list[SummaryItem]) -> str:
        return ", ".join(f"{escape(r.symbol)} {num(r.change_pct, 1, sign=True)} %"
                         for r in rows[:3]) or "—"  # fmt: skip

    cards = "".join(_card(i, scale) for i in items) or (
        '<p class="muted">La lista de seguimiento está vacía: añada activos con «+» en el panel '
        "izquierdo.</p>"
    )
    event_rows = "".join(_event_row(e) for e in events[:25]) or (
        '<li class="flat">Sin avisos recientes.</li>'
    )
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Resumen del día</title>
<style>{STYLE}{SUMMARY_STYLE}</style></head>
<body>
<h1>Resumen del día {status}</h1>
<p class="intro">{title_day.capitalize()} · {escape(list_name) or "Lista de seguimiento"}.
Pulse un activo para abrirlo en el gráfico. Cambios respecto al cierre anterior; durante la
sesión el último precio puede no ser definitivo.</p>
<div class="tiles">
  <div class="tile"><div class="big">{len(items)}</div><div>activos en la lista</div></div>
  <div class="tile up"><div class="big">{len(up)}</div><div>suben</div>
    <div class="muted small">{names(up)}</div></div>
  <div class="tile down"><div class="big">{len(down)}</div><div>bajan</div>
    <div class="muted small">{names(down)}</div></div>
  <div class="tile"><div class="big">{len(events)}</div><div>avisos recientes</div>
    <div class="muted small">alertas y novedades del escaneo diario</div></div>
</div>
<h2 class="section-title">Tu lista</h2>
<div class="wgrid">{cards}</div>
<h2 class="section-title">Avisos recientes</h2>
<ul class="events">{event_rows}</ul>
<h2 class="section-title">Próximos resultados y dividendos</h2>
<ul class="events">{_calendar_rows(calendar or [], local.date())}</ul>
<footer>Datos: Yahoo Finance (pueden tener retrasos; la empresa puede cambiar las fechas). No es
asesoramiento financiero.</footer>
</body></html>"""
