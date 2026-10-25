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
from analisis_acciones.portfolio.engine import BUY, DIVIDEND, ClosedTrade
from analisis_acciones.services.journal_stats import journal_stats
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
.pspark { width: 120px; height: 28px; display: block; }
.pspark polyline { fill: none; stroke: var(--up); stroke-width: 1.6; }
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


def position_spark(report: PortfolioReport, symbol: str, width: int = 120,
                   height: int = 28) -> str:  # fmt: skip
    """Market value of one holding per day (0 while not held)."""
    frame = report.position_values
    if symbol not in frame.columns or len(frame) < 2:
        return '<span class="muted">—</span>'
    values = [float(v) for v in frame[symbol]]
    high = max(values) or 1.0
    step = width / (len(values) - 1)
    pts = " ".join(
        f"{i * step:.1f},{2 + (high - v) * (height - 4) / high:.1f}" for i, v in enumerate(values)
    )
    first = pd.Timestamp(frame.index[0])
    return (
        f'<svg class="pspark" viewBox="0 0 {width} {height}" role="img" aria-label="Valor de '
        f'{escape(symbol)}"><title>{escape(symbol)}: valor desde el {first:%d/%m/%Y}, '
        f"máximo {num(high)}, hoy {num(values[-1])}</title>"
        f'<polyline points="{pts}"></polyline></svg>'
    )


def closed_panel(report: PortfolioReport) -> str:
    """Each sale's result and, per year, the net result and the estimated tax."""
    if not report.closed:
        return ""
    rows = []
    for c in reversed(report.closed):
        t = c.trade
        rows.append(
            f"<tr><td>{t.trade_date:%d/%m/%Y}</td><td><b>{escape(t.symbol)}</b></td>"
            f"<td class=n>{qty(t.quantity)}</td><td class=n>{num(t.price)}</td>"
            f"<td class=n>{num(c.cost)}</td><td class=n>{num(c.proceeds)}</td>"
            f"{_signed_cell(c.result)}{_signed_cell(c.result_pct, 2, ' %')}</tr>"
        )
    rate = report.portfolio.capital_gains_tax_pct
    years = "".join(
        f"<tr><td>{year}</td>{_signed_cell(net)}<td class=n>{num(tax)}</td></tr>"
        for year, net, tax in report.taxes
    )
    total_tax = sum(tax for _y, _n, tax in report.taxes)
    tax_note = (
        f"Impuesto estimado al {num(rate, 1)} % de la ganancia neta de cada año: "
        f"<b>{num(total_tax)}</b> en total (no se descuenta del efectivo)."
        if rate
        else "Sin tipo de impuesto configurado (botón «Impuestos…» de la cartera)."
    )
    return (
        '<div class="panel"><h3>Resultado de las ventas</h3><p class="muted small">Cada venta '
        "frente al coste medio de las acciones vendidas (comisiones incluidas).</p>"
        "<table><thead><tr><th>Fecha</th><th>Activo</th><th>Cantidad</th><th>Precio</th>"
        "<th>Coste</th><th>Importe neto</th><th>Resultado</th><th>%</th></tr></thead><tbody>"
        + "".join(rows)
        + '</tbody></table><h3>Por año</h3><table class="taxes"><thead><tr><th>Año</th>'
        "<th>Resultado neto</th><th>Impuesto estimado</th></tr></thead><tbody>"
        + years
        + f'</tbody></table><p class="muted small">{tax_note}</p></div>'
    )


def stats_panel(report: PortfolioReport) -> str:
    """Journal statistics: how the sales went, in plain words."""
    st = journal_stats(report.closed, report.trades)
    if not st.sales:
        return ""

    def tile(big: str, label: str, detail: str = "", css: str = "") -> str:
        return (
            f'<div class="tile {css}"><div class="big">{big}</div><div>{label}</div>'
            f'<div class="muted small">{detail}</div></div>'
        )

    pf = st.profit_factor
    tiles = "".join(
        [
            tile(
                f"{num(st.win_rate, 0)} %",
                "ventas con ganancia",
                f"{st.winners} de {st.sales} ({st.losers} con pérdida)",
            ),
            tile(
                num(pf, 2) if pf is not None else "—",
                "factor de beneficio",
                "ganancias / pérdidas; >1 = se ganó más de lo que se perdió"
                if pf is not None
                else "sin ventas con pérdida",
            ),
            tile(
                f"{num(st.average_gain, 2, sign=True)} / {num(st.average_loss, 2, sign=True)}",
                "ganancia media / pérdida media",
                f"relación {num(st.payoff_ratio, 2)}" if st.payoff_ratio is not None else "",
            ),
            tile(
                f"{num(st.average_days_held, 0)} días" if st.average_days_held is not None else "—",
                "tiempo medio mantenida",
                "desde la primera compra hasta la venta",
            ),
        ]
    )
    extremes = ""
    pairs: list[tuple[str, ClosedTrade | None]] = [("Mejor venta", st.best),
                                                    ("Peor venta", st.worst)]  # fmt: skip
    if st.sales == 1:
        pairs = [("Única venta", st.best)]
    for label, c in pairs:
        if c is not None:
            css = "up" if c.result > 0 else "down" if c.result < 0 else ""
            extremes += (
                f"<li><b>{label}:</b> {escape(c.trade.symbol)} el {c.trade.trade_date:%d/%m/%Y} · "
                f'<span class="{css}">{num(c.result, 2, sign=True)} '
                f"({num(c.result_pct, 1, sign=True)} %)</span></li>"
            )
    rows = "".join(
        f"<tr><td><b>{escape(s.symbol)}</b></td><td class=n>{s.sales}</td>"
        f"<td class=n>{num(s.winners / s.sales * 100, 0)} %</td>{_signed_cell(s.result)}</tr>"
        for s in st.by_symbol
    )
    journal = (
        f"Diario: {num(st.with_reason_pct, 0)} % de las operaciones tienen motivo escrito y "
        f"{num(st.with_review_pct, 0)} % tienen revisión."
    )
    warning = (
        f'<p class="warn">Solo {st.sales} venta{"s" if st.sales != 1 else ""}: con tan '
        "pocas operaciones estas cifras pueden deberse al azar y no son representativas.</p>"
        if st.small_sample
        else ""
    )
    return (
        '<div class="panel"><h3>Estadísticas del diario</h3><p class="muted small">Calculadas '
        "con las ventas de esta cartera simulada. Describen lo ocurrido, no lo que pasará."
        f'</p><div class="tiles">{tiles}</div><ul>{extremes}</ul>'
        "<table><thead><tr><th>Activo</th><th>Ventas</th><th>Con ganancia</th>"
        f"<th>Resultado</th></tr></thead><tbody>{rows}</tbody></table>"
        f'<p class="muted small">{journal}</p>{warning}</div>'
    )


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
            if applied.withheld:
                effect += f" (retenido {num(applied.withheld)} $)"
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
                f"comisiones pagadas {num(v.commissions)} · dividendos cobrados {num(v.dividends)}"
                + (f" (retenido {num(v.withheld)})" if v.withheld else ""),
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
            f'{min(h.weight_pct or 0, 100):.1f}%"></div></div></td>'
            f"<td>{position_spark(report, h.symbol)}</td></tr>"
            for h in holdings
        )
        or '<tr><td colspan="9" class="muted">Sin posiciones abiertas.</td></tr>'
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
<th>Valor</th><th>Resultado latente</th><th>%</th><th>Peso</th><th>Valor en el tiempo</th>
</tr></thead>
<tbody>{rows}</tbody></table></div>
{closed_panel(report)}
{stats_panel(report)}
{events}
<h2 class="section-title">Operaciones</h2>
<table><thead><tr><th>Fecha</th><th>Activo</th><th>Operación</th><th>Cantidad</th><th>Precio</th>
<th>Comisión</th><th>Importe</th><th>Diario (motivo y revisión)</th></tr></thead>
<tbody>{trades}</tbody></table>
<footer>Análisis de Acciones · Cartera simulada: importes en dólares (sin conversión de moneda);
impuestos simplificados (retención fija sobre dividendos e impuesto estimado sobre las ganancias
netas de cada año, sin compensar pérdidas entre años). Los splits se aplican a la cantidad de
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
            "resultado_venta",
        ]
    )
    results = {c.trade.id: c.result for c in report.closed if c.trade.id is not None}
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
                    round(results[t.id], 4) if t.id in results else "",
                )
            ]
        )
    return buffer.getvalue()
