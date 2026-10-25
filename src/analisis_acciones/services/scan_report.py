"""Visual scanner report: one self-contained HTML page (also used for the PDF).

Design goals: understandable at a glance by someone who is not a technical
analyst. Each asset gets a card with a plain-language verdict, a mini price
chart with its nearest support and resistance, a signal balance bar, an RSI
gauge and where the price sits between support and resistance. Bullish and
bearish are always shown with an icon (▲/▼) and a word, never by colour
alone; the blue/red pair passes colour-blindness separation checks.

No scripts and no external resources: the file opens anywhere, prints well
and cannot run code. Every text that comes from data is HTML-escaped.
Pure functions (no Qt).
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime
from html import escape

from analisis_acciones.data.export import safe_cell
from analisis_acciones.services.scanner import BREAKOUT_NOTE, ScanResult, ScanRow

UP_ICON, DOWN_ICON, FLAT_ICON = "▲", "▼", "●"
RSI_LOW, RSI_HIGH = 30, 70


# ---------------------------------------------------------------------------
# Formatting (Spanish conventions: 1.234,56)
# ---------------------------------------------------------------------------
def num(value: float | None, decimals: int = 2, sign: bool = False) -> str:
    if value is None:
        return "—"
    text = f"{abs(value):,.{decimals}f}".replace(",", "_").replace(".", ",").replace("_", ".")
    if value < 0 and text.strip("0,.") != "":
        return "−" + text
    return ("+" + text) if sign and value > 0 else text


def _date(day: date | None) -> str:
    return day.strftime("%d/%m/%Y") if day else "—"


# ---------------------------------------------------------------------------
# Plain-language reading of a row
# ---------------------------------------------------------------------------
def verdict(row: ScanRow) -> tuple[str, str, str]:
    """(css class, icon, sentence) summarising the balance of signals."""
    up, down = len(row.bullish), len(row.bearish)
    if up > down:
        return "up", UP_ICON, "Predominan las señales alcistas"
    if down > up:
        return "down", DOWN_ICON, "Predominan las señales bajistas"
    if up == 0:
        return "flat", FLAT_ICON, "Sin señales destacadas"
    return "flat", FLAT_ICON, "Señales mixtas: alcistas y bajistas a la par"


def rsi_reading(value: float | None) -> str:
    if value is None:
        return "sin datos"
    if value >= RSI_HIGH:
        return "zona de sobrecompra (subió mucho en poco tiempo)"
    if value <= RSI_LOW:
        return "zona de sobreventa (bajó mucho en poco tiempo)"
    return "zona neutral"


# ---------------------------------------------------------------------------
# Graphics (inline SVG / HTML)
# ---------------------------------------------------------------------------
def sparkline(row: ScanRow, width: int = 520, height: int = 120) -> str:
    """Closes as a line; nearest support/resistance as dashed lines labelled on the right."""
    values = list(row.history)
    if len(values) < 2:
        return '<div class="muted small">Sin historial suficiente para el gráfico.</div>'
    levels = [v for v in (row.support, row.resistance) if v is not None]
    low, high = min(values + levels), max(values + levels)
    span = (high - low) or 1.0
    left, right, top, bottom = 4, width - 118, 10, height - 10

    def x(i: int) -> float:
        return left + i * (right - left) / (len(values) - 1)

    def y(v: float) -> float:
        return top + (high - v) * (bottom - top) / span

    points = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(values))
    parts = [
        f'<svg class="spark" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Precio de cierre de {escape(row.symbol)}">',
        f"<title>{escape(row.symbol)}: cierres del {_date(row.history_start)} al "
        f"{_date(row.as_of)} · mín. {num(min(values))} · máx. {num(max(values))}</title>",
    ]
    label_ys: list[float] = []
    for value, css, label in ((row.resistance, "res", "Resistencia"),
                              (row.support, "sup", "Soporte")):  # fmt: skip
        if value is None:
            continue
        ly = y(value)
        text_y = ly + 4
        for other in label_ys:  # keep the two labels from overlapping
            if abs(text_y - other) < 13:
                text_y = other + 13 if css == "sup" else other - 13
        label_ys.append(text_y)
        parts.append(f'<line class="{css}" x1="{left}" x2="{right + 6}" y1="{ly:.1f}" '
                     f'y2="{ly:.1f}"><title>{label}: {num(value)}</title></line>')  # fmt: skip
        parts.append(f'<text class="lvl" x="{right + 10}" y="{text_y:.1f}">'
                     f"{label} {num(value)}</text>")  # fmt: skip
    parts.append(f'<polyline class="price" points="{points}"/>')
    lx, ly = x(len(values) - 1), y(values[-1])
    parts.append(f'<circle class="last" cx="{lx:.1f}" cy="{ly:.1f}" r="4.5">'
                 f"<title>Último cierre: {num(values[-1])}</title></circle>")  # fmt: skip
    parts.append("</svg>")
    return "".join(parts)


def candles_svg(row: ScanRow, width: int = 520, height: int = 190) -> str:
    """Candlestick chart of the last bars with SMA 20/50, volume and the nearest S/R."""
    candles = list(row.candles)
    if len(candles) < 2:
        return sparkline(row)
    n = len(candles)
    levels = [v for v in (row.support, row.resistance) if v is not None]
    smas = [v for v in (*row.sma20, *row.sma50) if v == v]  # drop NaN
    lows = [c[2] for c in candles] + levels + smas
    highs = [c[1] for c in candles] + levels + smas
    low, high = min(lows), max(highs)
    span = (high - low) or 1.0
    left, right, top, price_bottom = 4, width - 118, 8, height - 46
    vol_top, vol_bottom = height - 40, height - 18
    step = (right - left) / n
    body = max(step * 0.62, 1.0)

    def x(i: int) -> float:
        return left + (i + 0.5) * step

    def y(v: float) -> float:
        return top + (high - v) * (price_bottom - top) / span

    parts = [
        f'<svg class="candles" viewBox="0 0 {width} {height}" role="img" '
        f'aria-label="Gráfico de velas de {escape(row.symbol)}">',
        f"<title>{escape(row.symbol)}: últimas {n} sesiones, del {_date(row.candles_start)} "
        f"al {_date(row.as_of)}</title>",
    ]
    vols = [c[4] for c in candles if c[4] == c[4] and c[4] > 0]
    max_vol = max(vols) if vols else 0.0
    for i, (o, h, lo, c, v) in enumerate(candles):
        css = "up" if c >= o else "down"
        cx = x(i)
        y1, y2 = y(max(o, c)), y(min(o, c))
        parts.append(
            f'<g class="{css}"><title>{num(o)} → {num(c)} (máx. {num(h)}, mín. {num(lo)})'
            f'</title><line x1="{cx:.1f}" x2="{cx:.1f}" y1="{y(h):.1f}" y2="{y(lo):.1f}"/>'
            f'<rect x="{cx - body / 2:.1f}" y="{y1:.1f}" width="{body:.1f}" '
            f'height="{max(y2 - y1, 1):.1f}" rx="1"/></g>'
        )
        if max_vol and v == v and v > 0:
            vh = (vol_bottom - vol_top) * v / max_vol
            parts.append(f'<rect class="vol" x="{cx - body / 2:.1f}" y="{vol_bottom - vh:.1f}" '
                         f'width="{body:.1f}" height="{vh:.1f}"/>')  # fmt: skip

    def line(values: tuple[float, ...], css: str, label: str) -> None:
        points = [(x(i), y(v)) for i, v in enumerate(values) if v == v]
        if len(points) < 2:
            return
        coords = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
        parts.append(f'<polyline class="{css}" points="{coords}"><title>{label}: '
                     f"{num(values[-1])}</title></polyline>")  # fmt: skip

    line(row.sma50, "sma50", "Media de 50 sesiones")
    line(row.sma20, "sma20", "Media de 20 sesiones")
    labels: list[tuple[float, str, str]] = []
    for value, css, label in ((row.resistance, "res", "Resistencia"),
                              (row.support, "sup", "Soporte")):  # fmt: skip
        if value is None:
            continue
        ly = y(value)
        parts.append(f'<line class="{css}" x1="{left}" x2="{right + 6}" y1="{ly:.1f}" '
                     f'y2="{ly:.1f}"><title>{label}: {num(value)}</title></line>')  # fmt: skip
        labels.append((ly + 4, f"{label} {num(value)}", "lvl"))
    for values, label in ((row.sma20, "Media 20"), (row.sma50, "Media 50")):
        if values and values[-1] == values[-1]:
            labels.append((y(values[-1]) + 4, label, "lvl"))
    labels.sort()
    placed: list[float] = []
    for ly, text, css in labels:  # direct labels, nudged apart so they never overlap
        ly = max(ly, placed[-1] + 13) if placed else ly
        placed.append(ly)
        parts.append(f'<text class="{css}" x="{right + 10}" y="{ly:.1f}">{text}</text>')
    parts.append(f'<text class="axis" x="{left}" y="{height - 4}">{_date(row.candles_start)}'
                 f'</text><text class="axis" x="{right}" y="{height - 4}" text-anchor="end">'
                 f"{_date(row.as_of)}</text>")  # fmt: skip
    parts.append("</svg>")
    parts.append(
        '<div class="chart-legend"><span><i class="k-up"></i>vela alcista</span>'
        '<span><i class="k-down"></i>vela bajista</span>'
        '<span><i class="k-sma20"></i>media 20 sesiones</span>'
        '<span><i class="k-sma50"></i>media 50</span>'
        '<span><i class="k-lvl"></i>soporte / resistencia</span></div>'
    )
    return "".join(parts)


def balance_bar(row: ScanRow, scale: int) -> str:
    """Two-sided bar: bearish signals to the left, bullish to the right."""
    up, down = len(row.bullish), len(row.bearish)
    scale = max(scale, 1)
    up_list = "".join(f'<li><i class="up">{UP_ICON}</i> {escape(t)}</li>' for t in row.bullish)
    down_list = "".join(
        f'<li><i class="down">{DOWN_ICON}</i> {escape(t)}</li>' for t in row.bearish
    )
    return f"""
<div class="balance" title="{down} bajistas · {up} alcistas">
  <div class="side left"><span class="count">{DOWN_ICON} {down} bajista{"s" if down != 1 else ""}</span>
    <div class="track"><div class="fill down" style="width:{100 * down / scale:.0f}%"></div></div></div>
  <div class="axis"></div>
  <div class="side right"><div class="track"><div class="fill up" style="width:{100 * up / scale:.0f}%"></div></div>
    <span class="count">{up} alcista{"s" if up != 1 else ""} {UP_ICON}</span></div>
</div>
<ul class="signals">{down_list}{up_list}</ul>"""  # noqa: E501


def rsi_gauge(value: float | None) -> str:
    if value is None:
        return '<div class="muted small">RSI sin datos.</div>'
    pos = min(max(value, 0.0), 100.0)
    return f"""
<div class="gauge" title="RSI 14 = {num(value, 1)}">
  <div class="zones"><span class="z lo" style="width:{RSI_LOW}%">sobreventa</span><span class="z mid" style="width:{RSI_HIGH - RSI_LOW}%">neutral</span><span class="z hi" style="width:{100 - RSI_HIGH}%">sobrecompra</span></div>
  <div class="marker" style="left:{pos:.1f}%"></div>
</div>
<div class="small"><b>RSI {num(value, 1)}</b> · {rsi_reading(value)}</div>"""  # noqa: E501


def position_meter(row: ScanRow) -> str:
    if row.support is None and row.resistance is None:
        return '<div class="muted small">No hay soportes ni resistencias claros cerca.</div>'
    if row.support is None or row.resistance is None:
        if row.support is not None:
            return (f'<div class="small">Soporte más cercano en <b>{num(row.support)}</b>, '
                    f"un {num(row.support_pct, 1)} % por debajo. Sin resistencia clara por "
                    "encima.</div>")  # fmt: skip
        return (f'<div class="small">Resistencia más cercana en <b>{num(row.resistance)}</b>, '
                f"un {num(row.resistance_pct, 1)} % por encima. Sin soporte claro por "
                "debajo.</div>")  # fmt: skip
    span = row.resistance - row.support
    pos = 50.0 if span <= 0 else min(max((row.close - row.support) / span * 100, 0), 100)
    return f"""
<div class="meter" title="Precio entre soporte y resistencia">
  <span class="end">{num(row.support)}</span>
  <div class="rail"><div class="dot" style="left:{pos:.1f}%"></div></div>
  <span class="end">{num(row.resistance)}</span>
</div>
<div class="small">A <b>{num(row.support_pct, 1)} %</b> del soporte y a
<b>{num(row.resistance_pct, 1)} %</b> de la resistencia.</div>"""


def _pattern_chips(row: ScanRow) -> str:
    if not row.pattern_notes and not row.elliott:
        return '<div class="muted small">Sin patrones activos ni cuenta de Elliott en curso.</div>'
    chips = []
    for note in row.pattern_notes:
        css = "up" if note.bias > 0 else "down" if note.bias < 0 else "flat"
        icon = UP_ICON if note.bias > 0 else DOWN_ICON if note.bias < 0 else FLAT_ICON
        state = "ruptura reciente" if note.state == BREAKOUT_NOTE else "en formación"
        chips.append(f'<span class="chip {css}">{icon} {escape(note.name)} · {state}</span>')
    if row.elliott:
        icon = UP_ICON if row.elliott_direction > 0 else DOWN_ICON
        css = "up" if row.elliott_direction > 0 else "down"
        chips.append(f'<span class="chip {css}">{icon} Elliott: posible '
                     f"{escape(row.elliott)}</span>")  # fmt: skip
    return f'<div class="chips">{"".join(chips)}</div>'


def card(row: ScanRow, scale: int) -> str:
    css, icon, sentence = verdict(row)
    change_icon = UP_ICON if (row.change_pct or 0) > 0 else DOWN_ICON \
        if (row.change_pct or 0) < 0 else FLAT_ICON  # fmt: skip
    change_css = "up" if (row.change_pct or 0) > 0 else "down" if (row.change_pct or 0) < 0 \
        else "flat"  # fmt: skip
    return f"""
<article class="card {css}">
  <header>
    <div><h2>{escape(row.symbol)}</h2><div class="muted small">Cierre del {_date(row.as_of)}{_fundamentals(row)}</div></div>
    <div class="price"><b>{num(row.close)}</b>
      <span class="chg"><i class="{change_css}">{change_icon}</i> {num(row.change_pct, 2, sign=True)} %</span></div>
  </header>
  <div class="verdict {css}"><i>{icon}</i> {sentence}</div>
  <section><h3>Precio de las últimas sesiones</h3>{candles_svg(row)}</section>
  <section><h3>Balance de señales</h3>{balance_bar(row, scale)}</section>
  <div class="two">
    <section><h3>Fuerza reciente (RSI)</h3>{rsi_gauge(row.rsi14)}</section>
    <section><h3>Entre soporte y resistencia</h3>{position_meter(row)}</section>
  </div>
  <section><h3>Patrones y ondas</h3>{_pattern_chips(row)}</section>
</article>"""  # noqa: E501


def _fundamentals(row: ScanRow) -> str:
    if not row.fundamentals_checked:
        return ""

    def pct(v: float | None) -> float | None:
        return None if v is None else v * 100

    cap = "—" if row.market_cap is None else num(row.market_cap / 1e9, 1) + " mil M"
    return (
        f" · PER {num(row.pe, 1)} · dividendo {num(pct(row.dividend_yield), 2)} %"
        f" · cap. {cap} · ingresos {num(pct(row.revenue_growth), 1, sign=True)} %"
        f" · margen {num(pct(row.profit_margin), 1)} %"
    )


def _tile(value: int, label: str, names: list[str], css: str = "") -> str:
    listed = ", ".join(escape(n) for n in names[:8]) + ("…" if len(names) > 8 else "")
    return (f'<div class="tile {css}"><div class="big">{value}</div><div>{label}</div>'
            f'<div class="muted small">{listed or "—"}</div></div>')  # fmt: skip


def _table(rows: list[ScanRow]) -> str:
    body = []
    for row in rows:
        _css, icon, _sentence = verdict(row)
        body.append(
            "<tr>"
            f"<td><b>{escape(row.symbol)}</b></td><td class=n>{num(row.close)}</td>"
            f"<td class=n>{num(row.change_pct, 2, sign=True)} %</td>"
            f"<td class=n>{num(row.rsi14, 1)}</td>"
            f"<td class=n>{len(row.bullish)} {UP_ICON}</td>"
            f"<td class=n>{len(row.bearish)} {DOWN_ICON}</td>"
            f"<td>{icon}</td>"
            f"<td>{escape('; '.join(row.patterns)) or '—'}</td>"
            f"<td>{escape(row.elliott) or '—'}</td>"
            f"<td class=n>{num(row.support)}</td><td class=n>{num(row.resistance)}</td>"
            "</tr>"
        )
    return f"""
<table>
<thead><tr><th>Ticker</th><th>Cierre</th><th>Cambio</th><th>RSI 14</th><th>Alcistas</th>
<th>Bajistas</th><th>Balance</th><th>Patrones</th><th>Elliott</th><th>Soporte</th>
<th>Resistencia</th></tr></thead>
<tbody>{"".join(body)}</tbody></table>"""


STYLE = """
:root {
  color-scheme: light;
  --surface: #fcfcfb; --card: #ffffff; --border: #e3e2de;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #77766f;
  --up: #2a78d6; --down: #e34948; --flat: #8a8984; --sma20: #008300;
  --up-bg: #e8f1fc; --down-bg: #fdecec; --flat-bg: #f0efec;
  --zone-lo: #e8f1fc; --zone-mid: #f0efec; --zone-hi: #fdecec;
}
@media screen and (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --surface: #1a1a19; --card: #232321; --border: #3a3a37;
    --ink: #f0efec; --ink-2: #c3c2b7; --muted: #9a998f;
    --up: #3987e5; --down: #e66767; --flat: #9a998f; --sma20: #008300;
    --up-bg: #1c2d44; --down-bg: #44201f; --flat-bg: #2c2c2a;
    --zone-lo: #1c2d44; --zone-mid: #2c2c2a; --zone-hi: #44201f;
  }
}
@page { size: A4; margin: 12mm; }
* { box-sizing: border-box; }
body { margin: 0; padding: 24px; background: var(--surface); color: var(--ink);
  font: 14px/1.45 "Segoe UI", system-ui, -apple-system, Roboto, Arial, sans-serif; }

h1 { font-size: 26px; margin: 0 0 4px; }
h2 { font-size: 22px; margin: 0; letter-spacing: .5px; }
h3 { font-size: 12px; text-transform: uppercase; letter-spacing: .6px; color: var(--ink-2);
  margin: 14px 0 6px; font-weight: 600; }
.muted { color: var(--muted); } .small { font-size: 12.5px; }
.intro { max-width: 900px; color: var(--ink-2); margin: 0 0 18px; }
.tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0 20px; }
.tile { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 14px; }
.tile .big { font-size: 34px; font-weight: 700; line-height: 1.1; }
.tile.up .big::after { content: " ▲"; color: var(--up); font-size: 20px; }
.tile.down .big::after { content: " ▼"; color: var(--down); font-size: 20px; }
.howto { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 16px; margin-bottom: 20px; }
.howto ul { margin: 6px 0; padding-left: 18px; } .howto li { margin: 3px 0; }
.cards { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
@media screen and (max-width: 760px) { .cards, .tiles { grid-template-columns: 1fr; } }
.card { background: var(--card); border: 1px solid var(--border);
  border-left: 6px solid var(--flat); border-radius: 10px; padding: 14px 16px;
  break-inside: avoid; page-break-inside: avoid; }
.card.up { border-left-color: var(--up); } .card.down { border-left-color: var(--down); }
.card header { display: flex; justify-content: space-between; align-items: flex-start; }
.price { text-align: right; font-size: 20px; }
.chg { display: block; font-size: 14px; color: var(--ink-2); }
i.up, .verdict.up i { color: var(--up); font-style: normal; }
i.down, .verdict.down i { color: var(--down); font-style: normal; }
i.flat, .verdict.flat i { color: var(--flat); font-style: normal; }
.verdict { margin-top: 10px; padding: 7px 10px; border-radius: 8px; font-weight: 600;
  background: var(--flat-bg); }
.verdict.up { background: var(--up-bg); } .verdict.down { background: var(--down-bg); }
.spark { width: 100%; height: auto; display: block; }
.spark .price { fill: none; stroke: var(--ink-2); stroke-width: 2; stroke-linejoin: round; }
.spark .last { fill: var(--ink); stroke: var(--card); stroke-width: 2; }
.spark .sup { stroke: var(--up); stroke-width: 1.5; stroke-dasharray: 5 4; }
.spark .res { stroke: var(--down); stroke-width: 1.5; stroke-dasharray: 5 4; }
.spark .lvl { font-size: 12px; fill: var(--ink-2); }
.candles { width: 100%; height: auto; display: block; }
.candles .up { stroke: var(--up); fill: var(--up); }
.candles .down { stroke: var(--down); fill: var(--down); }
.candles line { stroke-width: 1; }
.candles .vol { fill: var(--flat); opacity: .45; }
.candles .sma20 { fill: none; stroke: var(--sma20); stroke-width: 1.6; }
.candles .sma50 { fill: none; stroke: var(--ink-2); stroke-width: 1.6; }
.candles .sup { stroke: var(--up); stroke-width: 1.2; stroke-dasharray: 5 4; }
.candles .res { stroke: var(--down); stroke-width: 1.2; stroke-dasharray: 5 4; }
.candles .lvl { font-size: 11.5px; fill: var(--ink-2); }
.candles .axis { font-size: 10.5px; fill: var(--muted); }
.chart-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; font-size: 11.5px;
  color: var(--ink-2); margin-top: 2px; }
.chart-legend i { display: inline-block; width: 14px; height: 3px; vertical-align: 3px;
  margin-right: 5px; border-radius: 2px; }
.k-up { background: var(--up); height: 9px !important; vertical-align: 0 !important; }
.k-down { background: var(--down); height: 9px !important; vertical-align: 0 !important; }
.k-sma20 { background: var(--sma20); } .k-sma50 { background: var(--ink-2); }
.k-lvl { background: repeating-linear-gradient(90deg, var(--ink-2) 0 4px, transparent 4px 7px); }
.balance { display: grid; grid-template-columns: 1fr 2px 1fr; align-items: center; gap: 6px; }
.balance .side { display: flex; align-items: center; gap: 6px; }
.balance .left { flex-direction: row; } .balance .left .track { transform: scaleX(-1); }
.balance .track { flex: 1; height: 12px; background: var(--flat-bg); border-radius: 4px; }
.balance .fill { height: 12px; border-radius: 4px; }
.fill.up { background: var(--up); } .fill.down { background: var(--down); }
.balance .axis { height: 22px; background: var(--ink-2); }
.balance .count { font-size: 12.5px; white-space: nowrap; color: var(--ink-2); }
.signals { list-style: none; padding: 0; margin: 6px 0 0; font-size: 12.5px; color: var(--ink-2);
  columns: 2; column-gap: 16px; }
.signals li { break-inside: avoid; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.gauge { position: relative; margin: 4px 0 8px; }
.zones { display: flex; height: 18px; border-radius: 4px; overflow: hidden; font-size: 10px;
  color: var(--ink-2); }
.z { display: flex; align-items: center; justify-content: center; }
.z.lo { background: var(--zone-lo); } .z.mid { background: var(--zone-mid); }
.z.hi { background: var(--zone-hi); }
.gauge { padding-top: 9px; }
.marker { position: absolute; top: 0; width: 0; height: 0; margin-left: -7px;
  border-left: 7px solid transparent; border-right: 7px solid transparent;
  border-top: 9px solid var(--ink); }
.meter { display: flex; align-items: center; gap: 8px; margin: 6px 0 8px; font-size: 12px; }
.meter .end { color: var(--ink-2); white-space: nowrap; }
.rail { position: relative; flex: 1; height: 8px; border-radius: 4px;
  background: linear-gradient(90deg, var(--up) 0 6px, var(--flat-bg) 6px calc(100% - 6px),
  var(--down) calc(100% - 6px)); }
.dot { position: absolute; top: -5px; width: 18px; height: 18px; margin-left: -9px;
  border-radius: 50%; background: var(--ink); border: 3px solid var(--card); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { border-radius: 999px; padding: 3px 10px; font-size: 12.5px; background: var(--flat-bg); }
.chip.up { background: var(--up-bg); } .chip.down { background: var(--down-bg); }
table { width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 12.5px; }
th, td { border-bottom: 1px solid var(--border); padding: 5px 6px; text-align: left;
  vertical-align: top; }
th { color: var(--ink-2); font-weight: 600; } td.n { text-align: right; white-space: nowrap; }
.section-title { margin: 28px 0 6px; font-size: 18px; break-after: avoid; }
.glossary dt { font-weight: 600; margin-top: 6px; } .glossary dd { margin: 0 0 4px 0;
  color: var(--ink-2); }
.problems { color: var(--ink-2); font-size: 12.5px; }
footer { margin-top: 24px; color: var(--muted); font-size: 12px; }
@media print {
  body { padding: 0; font-size: 11.5px; background: #ffffff; }
  .tile .big { font-size: 26px; }
  /* Chromium does not paginate grid rows well: one card per row, two per page. */
  .cards { display: block; }
  .card { margin-bottom: 10px; padding: 10px 14px; }
  h3 { margin: 8px 0 4px; }
  .spark { max-height: 105px; }
  .newpage { break-before: page; }
}"""


def scan_report_html(result: ScanResult, generated: datetime, title: str = "Escáner",
                     note: str = "") -> str:  # fmt: skip
    """``note`` (e.g. the active filter) is shown under the introduction."""
    rows = sorted(result.rows, key=lambda r: r.symbol)
    scale = max([len(r.bullish) for r in rows] + [len(r.bearish) for r in rows] + [3])
    up = [r.symbol for r in rows if verdict(r)[0] == "up"]
    down = [r.symbol for r in rows if verdict(r)[0] == "down"]
    active = [r.symbol for r in rows if r.pattern_notes]
    as_of = max((r.as_of for r in rows if r.as_of), default=None)
    problems = ""
    if result.problems:
        items = "".join(f"<li>{escape(p)}</li>" for p in result.problems)
        problems = f'<div class="problems"><b>No analizados:</b><ul>{items}</ul></div>'
    cards = "".join(card(r, scale) for r in rows) or '<p class="muted">Sin resultados.</p>'
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Informe del escáner · {escape(title)}</title>
<style>{STYLE}</style></head>
<body>
<h1>Informe del escáner</h1>
<p class="intro">{len(rows)} activos analizados con datos diarios hasta el {_date(as_of)} ·
generado el {generated.strftime("%d/%m/%Y %H:%M")}. Este informe <b>describe</b> lo que muestran
los datos con reglas fijas; no predice el futuro ni es una recomendación de inversión.</p>
<div class="tiles">
  {_tile(len(rows), "activos analizados", [r.symbol for r in rows])}
  {_tile(len(up), "con más señales alcistas", up, "up")}
  {_tile(len(down), "con más señales bajistas", down, "down")}
  {_tile(len(active), "con patrones activos", active)}
</div>
<div class="howto"><b>Cómo leer cada ficha</b><ul>
<li><b>Franja de color y frase de arriba:</b> {UP_ICON} azul si hay más señales alcistas que
bajistas, {DOWN_ICON} roja si ocurre lo contrario y {FLAT_ICON} gris si están igualadas o no hay
ninguna.</li>
<li><b>Gráfico:</b> velas de las últimas sesiones (azul = cerró por encima de la apertura, roja =
por debajo) con el volumen debajo y las medias de 20 y 50 sesiones. La línea discontinua azul es
el <b>soporte</b> (zona donde el precio dejó de bajar otras veces) y la roja, la
<b>resistencia</b> (zona donde dejó de subir).</li>
<li><b>Balance de señales:</b> barra roja hacia la izquierda = señales bajistas; barra azul hacia
la derecha = señales alcistas. Debajo se lista cada señal.</li>
<li><b>RSI:</b> mide si el precio ha subido o bajado muy deprisa. Por encima de 70 suele
llamarse «sobrecompra»; por debajo de 30, «sobreventa».</li>
<li><b>Entre soporte y resistencia:</b> el punto indica dónde está el precio dentro de ese
rango.</li></ul></div>
{f'<p class="intro"><b>{escape(note)}</b></p>' if note else ""}
{problems}
<div class="cards">{cards}</div>
<h2 class="section-title newpage">Tabla resumen</h2>
{_table(rows)}
<h2 class="section-title">Glosario</h2>
<dl class="glossary">
<dt>Señal alcista / bajista</dt><dd>Una regla técnica que se cumple en la última sesión (por
ejemplo, una media móvil que cruza a otra). No garantiza la dirección futura del precio.</dd>
<dt>Patrón en formación / ruptura reciente</dt><dd>Figura clásica del gráfico (doble techo,
hombro-cabeza-hombro, triángulo, bandera). «En formación» significa que aún no se ha confirmado;
«ruptura reciente», que el precio la confirmó en las últimas 10 sesiones.</dd>
<dt>Elliott</dt><dd>Interpretación del movimiento en ondas. Es subjetiva: suele haber varias
cuentas posibles.</dd>
</dl>
<footer>Análisis de Acciones · Datos: Yahoo Finance (pueden contener retrasos o errores). Los
patrones y señales técnicas fallan con frecuencia. No es asesoramiento financiero.</footer>
</body></html>"""


def scan_csv(result: ScanResult) -> str:
    """Spreadsheet-friendly results (formula-safe cells)."""
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow([
        "ticker", "fecha", "cierre", "cambio_pct", "rsi14", "senales_alcistas",
        "senales_bajistas", "balance", "detalle_alcistas", "detalle_bajistas", "patrones",
        "elliott", "soporte", "dist_soporte_pct", "resistencia", "dist_resistencia_pct",
        "per", "rentabilidad_dividendo_pct", "capitalizacion", "crecimiento_ingresos_pct",
        "margen_neto_pct",
    ])  # fmt: skip
    for row in sorted(result.rows, key=lambda r: r.symbol):
        _css, _icon, sentence = verdict(row)
        cells = [
            row.symbol, row.as_of.isoformat() if row.as_of else "", round(row.close, 4),
            _round(row.change_pct), _round(row.rsi14), len(row.bullish), len(row.bearish),
            sentence, "; ".join(row.bullish), "; ".join(row.bearish), "; ".join(row.patterns),
            row.elliott, _round(row.support), _round(row.support_pct), _round(row.resistance),
            _round(row.resistance_pct), _round(row.pe),
            _round(None if row.dividend_yield is None else row.dividend_yield * 100),
            _round(row.market_cap),
            _round(None if row.revenue_growth is None else row.revenue_growth * 100),
            _round(None if row.profit_margin is None else row.profit_margin * 100),
        ]  # fmt: skip
        writer.writerow([safe_cell(c) for c in cells])
    return buffer.getvalue()


def _round(value: float | None) -> float | str:
    return "" if value is None else round(value, 4)


def default_file_stem(now: datetime) -> str:
    return f"escaner_{now:%Y-%m-%d}"
