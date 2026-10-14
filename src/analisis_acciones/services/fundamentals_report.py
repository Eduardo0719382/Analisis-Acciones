"""'Fundamentales' page: key company figures explained in plain words, with yearly charts.

Every number comes from the data source (or, for dividends, from the cached
daily bars); a missing value is shown as "—", never estimated. No scripts;
data text is escaped.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from html import escape

from analisis_acciones.models.market import Fundamentals
from analisis_acciones.services import company_calendar
from analisis_acciones.services.market_data_service import FundamentalsResult
from analisis_acciones.services.scan_report import STYLE, num

EXTRA_STYLE = """
body { padding: 14px; }
h1 { font-size: 20px; }
.metrics { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; }
.metric { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
.metric .v { font-size: 18px; font-weight: 700; }
.metric .k { font-size: 12.5px; }
.metric .d { font-size: 11.5px; color: var(--muted); margin-top: 2px; }
.bars { width: 100%; max-width: 380px; height: auto; display: block; margin: 0 auto; }
.bars .pos { fill: var(--up); } .bars .neg { fill: var(--down); }
.bars text { font-size: 11px; fill: var(--ink-2); }
.bars .val { font-size: 10.5px; fill: var(--ink-2); }
.charts { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
.chart { background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }
.cal { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px; }
.cal .metric.next { border-color: var(--up); }
.badge { display: inline-block; font-size: 11px; padding: 0 6px; border-radius: 8px;
  background: var(--flat-bg); color: var(--ink-2); margin-left: 4px; }
"""  # noqa: E501


def big(value: float | None) -> str:
    """Large amounts in Spanish words: millones, mil millones, billones."""
    if value is None:
        return "—"
    size = abs(value)
    if size >= 1e12:
        return f"{num(value / 1e12, 2)} billones"
    if size >= 1e9:
        return f"{num(value / 1e9, 1)} mil millones"
    if size >= 1e6:
        return f"{num(value / 1e6, 1)} millones"
    return num(value, 0)


def pct(value: float | None, sign: bool = False) -> str:
    return "—" if value is None else f"{num(value * 100, 1, sign=sign)} %"


def bar_chart(
    points: Sequence[tuple[int, float | None]],
    fmt: str = "big",
    width: int = 300,
    height: int = 150,
) -> str:
    """Vertical bars per year; negatives below the zero line in red. Gaps for unknown years."""
    known = [(y, v) for y, v in points if v is not None]
    if not known:
        return '<div class="muted small">Sin datos.</div>'
    values = [v for _y, v in known]
    top_value, bottom_value = max(max(values), 0.0), min(min(values), 0.0)
    span = (top_value - bottom_value) or 1.0
    top, bottom = 16, height - 18
    zero = top + top_value / span * (bottom - top)
    step = width / len(points)
    bar_w = min(step * 0.6, 40)
    parts = [f'<svg class="bars" viewBox="0 0 {width} {height}" role="img">']
    for i, (year, v) in enumerate(points):
        cx = step * (i + 0.5)
        parts.append(f'<text x="{cx:.1f}" y="{height - 4}" text-anchor="middle">{year}</text>')
        if v is None:
            parts.append(
                f'<text class="val" x="{cx:.1f}" y="{zero - 4:.1f}" '
                'text-anchor="middle">sin dato</text>'
            )
            continue
        y_end = top + (top_value - v) * (bottom - top) / span
        y0, h = min(zero, y_end), max(abs(y_end - zero), 1.0)
        label = big(v) if fmt == "big" else num(v, 2)
        parts.append(
            f'<rect class="{"pos" if v >= 0 else "neg"}" x="{cx - bar_w / 2:.1f}" '
            f'y="{y0:.1f}" width="{bar_w:.1f}" height="{h:.1f}" rx="2">'
            f"<title>{year}: {label}</title></rect>"
        )
        ty = y0 - 3 if v >= 0 else y0 + h + 10
        short = label.replace(" mil millones", " mil M").replace(" millones", " M")
        parts.append(
            f'<text class="val" x="{cx:.1f}" y="{ty:.1f}" text-anchor="middle">{short}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _metric(value: str, label: str, meaning: str) -> str:
    return (
        f'<div class="metric" title="{escape(meaning)}"><div class="v">{value}</div>'
        f'<div class="k">{label}</div><div class="d">{escape(meaning)}</div></div>'
    )


def metrics(f: Fundamentals) -> str:
    cur = f" {escape(f.currency)}" if f.currency else ""
    items = [
        (
            big(f.market_cap) + (cur if f.market_cap else ""),
            "Capitalización",
            "Valor en bolsa de todas las acciones.",
        ),
        (
            num(f.trailing_pe, 1),
            "PER (últimos 12 meses)",
            "Precio / beneficio por acción: años de beneficio actual que se pagan.",
        ),
        (
            num(f.forward_pe, 1),
            "PER estimado",
            "Igual, con el beneficio que esperan los analistas (estimación).",
        ),
        (num(f.trailing_eps, 2), "Beneficio por acción (BPA)", "Últimos 12 meses."),
        (
            num(f.price_to_book, 2),
            "Precio / valor contable",
            "Cuánto se paga por cada unidad de patrimonio contable.",
        ),
        (pct(f.dividend_yield), "Rentabilidad por dividendo", "Dividendo anual / precio actual."),
        (num(f.dividend_rate, 2), "Dividendo anual por acción", "Según el proveedor."),
        (pct(f.payout_ratio), "Pay-out", "Parte del beneficio que se reparte como dividendo."),
        (pct(f.profit_margin), "Margen neto", "Beneficio por cada 100 de ventas."),
        (pct(f.operating_margin), "Margen operativo", "Resultado del negocio sobre ventas."),
        (pct(f.return_on_equity), "ROE", "Beneficio sobre el patrimonio de los accionistas."),
        (
            pct(f.revenue_growth, sign=True),
            "Crecimiento de ingresos",
            "Respecto al mismo periodo del año anterior.",
        ),
        (
            pct(f.earnings_growth, sign=True),
            "Crecimiento del beneficio",
            "Respecto al mismo periodo del año anterior.",
        ),
        (num(f.beta, 2), "Beta", "1 = se mueve como el mercado; 2 = el doble de fuerte."),
    ]
    return '<div class="metrics">' + "".join(_metric(*i) for i in items) + "</div>"


def calendar_section(f: Fundamentals, today: date) -> str:
    items = company_calendar.entries(f)
    if not items:
        return (
            '<p class="muted small">El proveedor no publica fechas de resultados ni de '
            "dividendos para este activo.</p>"
        )
    cards = []
    for e in items:
        past = (e.day_end or e.day) < today
        badges = '<span class="badge">estimada</span>' if e.estimated else ""
        badges += '<span class="badge">pasada</span>' if past else ""
        meaning = company_calendar.MEANINGS[e.kind]
        cards.append(
            f'<div class="metric{"" if past else " next"}" title="{escape(meaning)}">'
            f'<div class="v">{company_calendar.date_text(e)}</div>'
            f'<div class="k">{e.label}{badges}</div>'
            f'<div class="d">{company_calendar.when(e, today).capitalize()}. {escape(meaning)}'
            "</div></div>"
        )
    return f'<div class="cal">{"".join(cards)}</div>'


def fundamentals_html(result: FundamentalsResult, name: str = "", today: date | None = None) -> str:
    f = result.data
    today = today or date.today()
    annual = f.annual[-8:]
    years = [a.year for a in annual]
    charts = []
    if annual:
        charts.append(("Ingresos por año", bar_chart([(a.year, a.revenue) for a in annual])))
        charts.append(
            ("Beneficio neto por año", bar_chart([(a.year, a.net_income) for a in annual]))
        )
        charts.append(
            (
                "Beneficio por acción (BPA) por año",
                bar_chart([(a.year, a.eps) for a in annual], fmt="num"),
            )
        )
    dividends = [(y, v) for y, v in result.dividends][-10:]
    if dividends:
        charts.append(
            (
                "Dividendos por acción cobrados cada año",
                bar_chart([(y, v) for y, v in dividends], fmt="num"),
            )
        )
    chart_html = "".join(f'<div class="chart"><h3>{t}</h3>{c}</div>' for t, c in charts) or (
        '<p class="muted">El proveedor no ofrece cuentas anuales para este activo.</p>'
    )
    stale = (
        f'<p class="problems"><b>Datos guardados del {result.fetched_at:%d/%m/%Y}</b> '
        f"(sin conexión: {escape(result.notice or '')}).</p>"
        if result.stale
        else ""
    )
    period = f" ({years[0]}–{years[-1]})" if years else ""
    title = escape(name or f.symbol)
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fundamentales</title><style>{STYLE}{EXTRA_STYLE}</style></head>
<body>
<h1>{title}</h1>
<p class="intro small">Datos de la empresa según Yahoo Finance, actualizados el
{result.fetched_at:%d/%m/%Y}. Pase el ratón sobre cada dato para ver qué significa. Un «—» indica
que el dato no está disponible.</p>
{stale}
{metrics(f)}
<h2 class="section-title">Calendario</h2>
{calendar_section(f, today)}
<h2 class="section-title">Evolución anual{period}</h2>
<div class="charts">{chart_html}</div>
<footer>«M» = millones. Las cifras anuales son las del ejercicio fiscal de la empresa. Los
dividendos por año se calculan con el historial de cotizaciones guardado. Las fechas del
calendario son las que publica Yahoo Finance; la empresa puede cambiarlas y una fecha «estimada»
aún no está confirmada. No es asesoramiento financiero.</footer>
</body></html>"""
