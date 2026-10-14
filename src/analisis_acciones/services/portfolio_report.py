"""Visual report of a paper portfolio (HTML for the dialog, export and PDF).

Same visual language as the other reports: tiles with the key numbers, the
portfolio value over time against a benchmark that started with the same
money, holdings with their weight and result, and the list of trades.
Self-contained (no scripts); data text is escaped.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from html import escape

import pandas as pd

from analisis_acciones.data.export import safe_cell
from analisis_acciones.portfolio.engine import BUY, DIVIDEND
from analisis_acciones.services.paper_portfolio import PortfolioReport
from analisis_acciones.services.scan_report import STYLE, num

EXTRA_STYLE = """
.curve { width: 100%; height: auto; display: block; }
.curve .pf { fill: none; stroke: var(--up); stroke-width: 2.2; }
.curve .bm { fill: none; stroke: var(--ink-2); stroke-width: 1.6; }
.curve .base { stroke: var(--flat); stroke-width: 1; stroke-dasharray: 4 4; }
.curve text { font-size: 11.5px; fill: var(--ink-2); }
.curve .axis { fill: var(--muted); font-size: 10.5px; }
.chart-legend { display: flex; gap: 14px; font-size: 12px; color: var(--ink-2); margin: 4px 0; }
.chart-legend i { display: inline-block; width: 14px; height: 3px; vertical-align: 3px;
  margin-right: 5px; border-radius: 2px; }
.alloc { display: flex; height: 22px; border-radius: 4px; overflow: hidden; gap: 2px; margin: 6px 0 10px; }
.alloc span { display: block; height: 100%; background: var(--up); color: #fff; font-size: 11.5px;
  line-height: 22px; padding: 0 6px; white-space: nowrap; overflow: hidden; text-overflow: clip; }
.alloc span.cash { background: var(--flat); }
.wbar { height: 8px; background: var(--flat-bg); border-radius: 4px; min-width: 80px; }
.wbar div { height: 8px; background: var(--up); border-radius: 4px; }
td.up::before { content: "▲ "; color: var(--up); } td.down::before { content: "▼ "; color: var(--down); }
.panel { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 16px; margin: 14px 0; break-inside: avoid; }
.warn { color: var(--ink-2); font-size: 12px; }
.review { color: var(--ink-2); font-size: 12px; margin-top: 2px; }
.review b { color: var(--ink); }
"""  # noqa: E501


def qty(value: float) -> str:
    text = num(value, 4)
    return text.rstrip("0").rstrip(",") if "," in text else text


def _signed_cell(value: float | None, decimals: int = 2, suffix: str = "") -> str:
    if value is None:
        return "<td class=n>—</td>"
    css = "up" if value > 0 else "down" if value < 0 else ""
    return f'<td class="n {css}">{num(value, decimals, sign=True)}{suffix}</td>'


def curve_svg(
    equity: pd.Series,
    benchmark: pd.Series,
    initial: float,
    bench_name: str,
    width: int = 900,
    height: int = 240,
) -> str:
    if len(equity) < 2:
        return '<p class="muted">La curva aparecerá cuando haya operaciones en más de un día.</p>'
    values = [float(v) for v in [*equity, *benchmark.dropna(), initial]]
    low, high = min(values), max(values)
    span = (high - low) or 1.0
    left, right, top, bottom = 4, width - 130, 10, height - 24
    index = pd.DatetimeIndex(equity.index)
    first, last = index[0], index[-1]
    total_days = max((last - first).days, 1)

    def x(ts: pd.Timestamp) -> float:
        return left + (ts - first).days / total_days * (right - left)

    def y(v: float) -> float:
        return top + (high - v) * (bottom - top) / span

    def poly(series: pd.Series, css: str, label: str) -> str:
        clean = series.dropna()
        pts = " ".join(
            f"{x(ts):.1f},{y(float(v)):.1f}"
            for ts, v in zip(pd.DatetimeIndex(clean.index), clean, strict=True)
        )
        return (
            f'<polyline class="{css}" points="{pts}"><title>{escape(label)}: '
            f"{num(float(series.dropna().iloc[-1]))}</title></polyline>"
        )

    parts = [
        f'<svg class="curve" viewBox="0 0 {width} {height}" role="img" '
        'aria-label="Valor de la cartera frente a la referencia">',
        f'<line class="base" x1="{left}" x2="{right}" y1="{y(initial):.1f}" '
        f'y2="{y(initial):.1f}"><title>Capital inicial {num(initial)}</title></line>',
    ]
    labels = [(y(initial) + 4, f"Inicial {num(initial)}")]
    if len(benchmark.dropna()) >= 2:
        parts.append(poly(benchmark, "bm", bench_name))
        labels.append(
            (
                y(float(benchmark.dropna().iloc[-1])) + 4,
                f"{escape(bench_name)} {num(float(benchmark.dropna().iloc[-1]))}",
            )
        )
    parts.append(poly(equity, "pf", "Cartera"))
    labels.append((y(float(equity.iloc[-1])) + 4, f"Cartera {num(float(equity.iloc[-1]))}"))
    labels.sort()
    placed: list[float] = []
    for ly, text in labels:
        ly = max(ly, placed[-1] + 14) if placed else ly
        placed.append(ly)
        parts.append(f'<text x="{right + 8}" y="{ly:.1f}">{text}</text>')
    parts.append(
        f'<text class="axis" x="{left}" y="{height - 6}">{first:%d/%m/%Y}</text>'
        f'<text class="axis" x="{right}" y="{height - 6}" text-anchor="end">'
        f"{last:%d/%m/%Y}</text></svg>"
    )
    legend = (
        '<div class="chart-legend"><span><i style="background:var(--up)"></i>cartera</span>'
        f'<span><i style="background:var(--ink-2)"></i>{escape(bench_name)} con el mismo '
        'capital inicial</span><span><i style="background:repeating-linear-gradient(90deg,'
        'var(--flat) 0 4px,transparent 4px 7px)"></i>capital inicial</span></div>'
    )
    return "".join(parts) + legend


def _journal(note: str, review: str) -> str:
    text = escape(note) if note else '<span class="muted">—</span>'
    if review:
        text += f'<div class="review"><b>Revisión:</b> {escape(review)}</div>'
    return text


def _events_panel(report: PortfolioReport) -> str:
    """Dividends and splits that affected the portfolio, newest first."""
    if not report.events:
        return ""
    rows = []
    for applied in reversed(report.events):
        e = applied.event
        shares = applied.shares
        if e.kind == DIVIDEND:
            what = "Dividendo"
            detail = f"{num(e.value, 4).rstrip('0').rstrip(',')} $ por acción"
            effect = f"+{num(applied.cash)} $ en efectivo"
            affected = shares
        else:
            what = "Split"
            ratio = qty(e.value)
            detail = (
                f"{ratio} acciones nuevas por cada una"
                if e.value >= 1
                else f"contrasplit: {ratio} por cada una"
            )
            affected = shares / e.value
            effect = f"de {qty(affected)} a {qty(shares)} acciones"
        rows.append(
            f"<tr><td>{e.day:%d/%m/%Y}</td><td><b>{escape(e.symbol)}</b></td><td>{what}</td>"
            f"<td>{detail}</td><td class=n>{qty(affected)}</td><td>{effect}</td></tr>"
        )
    return (
        '<div class="panel"><h3>Eventos corporativos</h3><p class="muted small">Dividendos '
        "cobrados y splits aplicados a las acciones que tenía la cartera en cada fecha.</p>"
        "<table><thead><tr><th>Fecha ex</th><th>Activo</th><th>Evento</th><th>Detalle</th>"
        "<th>Acciones afectadas</th><th>Efecto</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table></div>"
    )


def portfolio_html(report: PortfolioReport, generated: datetime) -> str:
    v = report.valuation
    p = report.portfolio
    total = v.total_value
    result = total - p.initial_cash if total is not None else None
    bench_ret = None
    if len(report.benchmark.dropna()) and total is not None:
        bench_ret = (float(report.benchmark.dropna().iloc[-1]) / p.initial_cash - 1) * 100
    diff = (
        v.total_return_pct - bench_ret
        if v.total_return_pct is not None and bench_ret is not None
        else None
    )

    def tile(big: str, label: str, detail: str = "", css: str = "") -> str:
        return (
            f'<div class="tile {css}"><div class="big">{big}</div><div>{label}</div>'
            f'<div class="muted small">{detail}</div></div>'
        )

    result_css = "up" if (result or 0) > 0 else "down" if (result or 0) < 0 else ""
    tiles = "".join(
        [
            tile(
                num(total) if total is not None else "—",
                "valor total",
                f"capital inicial {num(p.initial_cash)}",
            ),
            tile(
                f"{num(v.total_return_pct, 2, sign=True)} %",
                "resultado total",
                f"{num(result, 2, sign=True)} (realizado {num(v.realized, 2, sign=True)}, "
                f"latente {num(v.unrealized, 2, sign=True)})",
                result_css,
            ),
            tile(
                num(v.cash),
                "efectivo disponible",
                f"comisiones pagadas {num(v.commissions)} · dividendos cobrados {num(v.dividends)}",
            ),
            tile(
                f"{num(diff, 1, sign=True)} pts" if diff is not None else "—",
                f"frente a {escape(report.benchmark_symbol)}",
                f"{escape(report.benchmark_symbol)} {num(bench_ret, 2, sign=True)} % con el mismo "
                "capital y fechas",
            ),
        ]
    )
    holdings = v.holdings
    alloc = ""
    if total:
        spans = "".join(
            f'<span style="width:{h.weight_pct:.2f}%" title="{escape(h.symbol)} '
            f'{num(h.weight_pct, 1)} %">{escape(h.symbol)} {num(h.weight_pct, 0)} %</span>'
            for h in holdings
            if h.weight_pct
        )
        cash_pct = v.cash / total * 100
        spans += (
            f'<span class="cash" style="width:{cash_pct:.2f}%" title="Efectivo '
            f'{num(cash_pct, 1)} %">Efectivo {num(cash_pct, 0)} %</span>'
        )
        alloc = f'<div class="alloc">{spans}</div>'
    rows = (
        "".join(
            f"<tr><td><b>{escape(h.symbol)}</b></td><td class=n>{qty(h.quantity)}</td>"
            f"<td class=n>{num(h.average_cost)}</td><td class=n>{num(h.price)}</td>"
            f"<td class=n>{num(h.market_value)}</td>{_signed_cell(h.unrealized)}"
            f"{_signed_cell(h.unrealized_pct, 2, ' %')}"
            f'<td><div class="wbar" title="{num(h.weight_pct, 1)} %"><div style="width:'
            f'{min(h.weight_pct or 0, 100):.1f}%"></div></div></td></tr>'
            for h in holdings
        )
        or '<tr><td colspan="8" class="muted">Sin posiciones abiertas.</td></tr>'
    )
    trades = (
        "".join(
            f"<tr><td>{t.trade_date:%d/%m/%Y}</td><td><b>{escape(t.symbol)}</b></td>"
            f"<td>{'Compra ▲' if t.side == BUY else 'Venta ▼'}</td>"
            f"<td class=n>{qty(t.quantity)}</td><td class=n>{num(t.price)}</td>"
            f"<td class=n>{num(t.commission)}</td><td class=n>{num(t.value)}</td>"
            f"<td>{_journal(t.note, t.review)}</td></tr>"
            for t in reversed(report.trades)
        )
        or '<tr><td colspan="8" class="muted">Todavía no hay operaciones.</td></tr>'
    )
    events = _events_panel(report)
    problems = ""
    if report.problems:
        items = "".join(f"<li>{escape(x)}</li>" for x in report.problems)
        problems = f'<div class="problems"><b>Avisos:</b><ul>{items}</ul></div>'
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cartera simulada</title>
<style>{STYLE}{EXTRA_STYLE}</style></head>
<body>
<h1>Cartera simulada: {escape(p.name)}</h1>
<p class="intro"><b>Operaciones ficticias</b>, sin dinero real, valoradas con el último cierre
diario · generado el {generated:%d/%m/%Y %H:%M}. Los importes se suman sin conversión de moneda.
</p>
<div class="tiles">{tiles}</div>
{problems}
<div class="panel"><h3>Valor de la cartera en el tiempo</h3>
{curve_svg(report.equity, report.benchmark, p.initial_cash, report.benchmark_symbol)}</div>
<div class="panel"><h3>Posiciones y distribución</h3>{alloc}
<table><thead><tr><th>Activo</th><th>Cantidad</th><th>Coste medio</th><th>Último cierre</th>
<th>Valor</th><th>Resultado latente</th><th>%</th><th>Peso</th></tr></thead>
<tbody>{rows}</tbody></table></div>
{events}
<h2 class="section-title">Operaciones</h2>
<table><thead><tr><th>Fecha</th><th>Activo</th><th>Operación</th><th>Cantidad</th><th>Precio</th>
<th>Comisión</th><th>Importe</th><th>Diario (motivo y revisión)</th></tr></thead>
<tbody>{trades}</tbody></table>
<footer>Análisis de Acciones · Cartera simulada: importes en dólares (sin conversión de moneda);
no refleja impuestos ni retenciones sobre dividendos. Los splits se aplican a la cantidad de
acciones y los dividendos se cobran en efectivo en su fecha ex-dividendo. No es asesoramiento
financiero.
</footer>
</body></html>"""


def portfolio_trades_csv(report: PortfolioReport) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        [
            "fecha",
            "ticker",
            "operacion",
            "cantidad",
            "precio",
            "comision",
            "importe",
            "motivo",
            "revision",
        ]
    )
    for t in report.trades:
        writer.writerow(
            [
                safe_cell(c)
                for c in (
                    t.trade_date.isoformat(),
                    t.symbol,
                    "compra" if t.side == BUY else "venta",
                    t.quantity,
                    t.price,
                    t.commission,
                    round(t.value, 4),
                    t.note,
                    t.review,
                )
            ]
        )
    return buffer.getvalue()
