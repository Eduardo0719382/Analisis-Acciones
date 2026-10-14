"""Visual report of a chart-pattern backtest (HTML for screen, PDF and the dialog).

Written for non-specialists: tiles with the four numbers that matter, a bar
per pattern showing its average result per trade, how trades ended (target,
stop, time limit), plain-language tables and explicit warnings for small
samples. Positive is blue ▲ and negative red ▼, always with sign and icon.
Self-contained (no scripts, no external resources); data text is escaped.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from html import escape

from analisis_acciones.backtesting.patterns import (
    STOP,
    TARGET,
    GroupStats,
    PatternBacktestResult,
)
from analisis_acciones.data.export import safe_cell
from analisis_acciones.services.scan_report import STYLE, num

SMALL_SAMPLE = 20
MAX_LISTED_TRADES = 300
REASONS = {TARGET: "objetivo", STOP: "stop (invalidación)", "time": "plazo máximo"}

EXTRA_STYLE = """
.bars { display: grid; grid-template-columns: minmax(150px, 230px) 1fr 70px; gap: 8px 12px;
  align-items: center; margin: 8px 0 4px; }
.bars .label { font-size: 13px; } .bars .label small { color: var(--muted); display: block; }
.dbar { position: relative; height: 18px; background: var(--flat-bg); border-radius: 4px; }
.dbar .zero { position: absolute; left: 50%; top: -3px; bottom: -3px; width: 2px;
  background: var(--ink-2); }
.dbar .fill { position: absolute; top: 3px; height: 12px; border-radius: 3px; }
.dbar .fill.up { left: 50%; } .dbar .fill.down { right: 50%; }
.bars .val { text-align: right; font-weight: 600; white-space: nowrap; }
.stack { display: flex; height: 18px; border-radius: 4px; overflow: hidden; gap: 2px; }
.stack span { display: block; height: 100%; }
.s-target { background: var(--up); } .s-stop { background: var(--down); }
.s-time { background: var(--flat); }
.legend { display: flex; gap: 16px; font-size: 12.5px; color: var(--ink-2); margin: 6px 0; }
.legend i { display: inline-block; width: 12px; height: 12px; border-radius: 3px;
  vertical-align: -1px; margin-right: 5px; }
.warn { color: var(--ink-2); font-size: 12px; }
.panel { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
  padding: 12px 16px; margin: 14px 0; break-inside: avoid; }
td.up::before { content: "▲ "; color: var(--up); } td.down::before { content: "▼ "; color: var(--down); }
"""  # noqa: E501


def _signed_cell(value: float | None, decimals: int = 2, suffix: str = " %") -> str:
    if value is None:
        return "<td class=n>—</td>"
    css = "up" if value > 0 else "down" if value < 0 else ""
    return f'<td class="n {css}">{num(value, decimals, sign=True)}{suffix}</td>'


def _bar_rows(groups: list[GroupStats]) -> str:
    scale = max([abs(g.avg_return_pct) for g in groups] + [0.5])
    rows = []
    for g in groups:
        value = g.avg_return_pct
        width = abs(value) / scale * 50
        css = "up" if value > 0 else "down"
        icon = "▲" if value > 0 else "▼" if value < 0 else "●"
        small = " · muestra pequeña" if g.trades < SMALL_SAMPLE else ""
        rows.append(
            f'<div class="label">{escape(g.name)}<small>{g.trades} operaciones · '
            f"{num(g.win_rate_pct, 0)} % ganadoras{small}</small></div>"
            f'<div class="dbar" title="{escape(g.name)}: media {num(value, 2, sign=True)} % '
            f'por operación"><div class="zero"></div>'
            f'<div class="fill {css}" style="width:{width:.1f}%"></div></div>'
            f'<div class="val">{icon} {num(value, 2, sign=True)} %</div>'
        )
    return f'<div class="bars">{"".join(rows)}</div>'


def _exit_rows(groups: list[GroupStats]) -> str:
    rows = []
    for g in groups:
        parts = (("s-target", g.target_pct, "objetivo"), ("s-stop", g.stop_pct, "stop"),
                 ("s-time", g.time_pct, "plazo"))  # fmt: skip
        spans = "".join(
            f'<span class="{css}" style="width:{pct:.1f}%" title="{label}: {num(pct, 0)} %"></span>'
            for css, pct, label in parts
            if pct > 0
        )
        rows.append(
            f'<div class="label">{escape(g.name)}</div><div class="stack">{spans}</div>'
            f'<div class="val small">{num(g.target_pct, 0)} / {num(g.stop_pct, 0)} / '
            f"{num(g.time_pct, 0)}</div>"
        )
    return f'<div class="bars">{"".join(rows)}</div>'


def _group_table(groups: list[GroupStats], first: str) -> str:
    body = "".join(
        f"<tr><td><b>{escape(g.name)}</b>{' ⚠' if g.trades < SMALL_SAMPLE else ''}</td>"
        f"<td class=n>{g.trades}</td><td class=n>{num(g.win_rate_pct, 0)} %</td>"
        f"{_signed_cell(g.avg_return_pct)}{_signed_cell(g.median_return_pct)}"
        f"{_signed_cell(g.avg_win_pct)}{_signed_cell(g.avg_loss_pct)}"
        f"<td class=n>{num(g.profit_factor, 2)}</td><td class=n>{num(g.avg_bars, 0)}</td>"
        f"{_signed_cell(g.edge_pct)}</tr>"
        for g in groups
    )
    return (
        f"<table><thead><tr><th>{first}</th><th>Operaciones</th><th>Ganadoras</th>"
        "<th>Media</th><th>Mediana</th><th>Media si gana</th><th>Media si pierde</th>"
        "<th>Factor de beneficio</th><th>Sesiones</th><th>Ventaja frente al azar</th></tr>"
        f"</thead><tbody>{body}</tbody></table>"
    )


def _trades_table(result: PatternBacktestResult) -> str:
    trades = result.trades[-MAX_LISTED_TRADES:]
    body = "".join(
        f"<tr><td>{escape(t.symbol)}</td><td>{escape(t.pattern)}</td>"
        f"<td>{'Compra ▲' if t.direction > 0 else 'Venta corta ▼'}</td>"
        f"<td>{t.entry_date:%d/%m/%Y}</td><td class=n>{num(t.entry_price)}</td>"
        f"<td>{t.exit_date:%d/%m/%Y}</td><td class=n>{num(t.exit_price)}</td>"
        f"<td>{REASONS.get(t.exit_reason, t.exit_reason)}</td>{_signed_cell(t.return_pct)}</tr>"
        for t in reversed(trades)
    )
    note = ""
    if len(result.trades) > MAX_LISTED_TRADES:
        note = (f"<p class=warn>Se muestran las {MAX_LISTED_TRADES} más recientes de "
                f"{len(result.trades)}.</p>")  # fmt: skip
    return (
        "<table><thead><tr><th>Ticker</th><th>Patrón</th><th>Operación</th><th>Entrada</th>"
        "<th>Precio</th><th>Salida</th><th>Precio</th><th>Motivo</th><th>Resultado</th></tr>"
        f"</thead><tbody>{body}</tbody></table>{note}"
    )


def _tile(value: str, label: str, detail: str = "") -> str:
    return (f'<div class="tile"><div class="big">{value}</div><div>{label}</div>'
            f'<div class="muted small">{detail}</div></div>')  # fmt: skip


def pattern_report_html(result: PatternBacktestResult, generated: datetime) -> str:
    config = result.config
    overall = result.overall()
    by_pattern = result.by_pattern()
    symbols = ", ".join(escape(s) for s in result.symbols) or "—"
    problems = ""
    if result.problems:
        items = "".join(f"<li>{escape(p)}</li>" for p in result.problems)
        problems = f'<div class="problems"><b>No analizados:</b><ul>{items}</ul></div>'
    if overall is None:
        body = ('<div class="panel">No hubo ninguna operación: ningún patrón confirmado con los '
                "datos disponibles el día de su ruptura.</div>")  # fmt: skip
        tiles = ""
    else:
        edge = overall.edge_pct
        tiles = f"""<div class="tiles">
  {_tile(str(overall.trades), "operaciones simuladas", f"{len(result.symbols)} activos")}
  {
            _tile(
                f"{num(overall.win_rate_pct, 0)} %",
                "acabaron en ganancia",
                f"media si gana {num(overall.avg_win_pct, 1, sign=True)} % · si pierde "
                f"{num(overall.avg_loss_pct, 1, sign=True)} %",
            )
        }
  {
            _tile(
                f"{num(overall.avg_return_pct, 2, sign=True)} %",
                "resultado medio por operación",
                f"mediana {num(overall.median_return_pct, 2, sign=True)} %",
            )
        }
  {
            _tile(
                f"{num(edge, 2, sign=True)} %" if edge is not None else "—",
                "ventaja frente al azar",
                "media de la operación menos la de entrar cualquier día con el mismo plazo",
            )
        }
</div>"""
        body = f"""
<div class="panel"><h3>Resultado medio por operación, según el patrón</h3>
<div class="legend"><span><i style="background:var(--up)"></i>▲ ganancia media</span>
<span><i style="background:var(--down)"></i>▼ pérdida media</span></div>
{_bar_rows(by_pattern)}
<p class="warn">⚠ Con menos de {SMALL_SAMPLE} operaciones el resultado es poco fiable: puede
deberse al azar.</p></div>
<div class="panel"><h3>Cómo terminaron las operaciones (% objetivo / stop / plazo)</h3>
<div class="legend"><span><i class="s-target"></i>alcanzó el objetivo</span>
<span><i class="s-stop"></i>tocó el stop (invalidación)</span>
<span><i class="s-time"></i>se cerró por plazo máximo</span></div>
{_exit_rows(by_pattern)}</div>
<h2 class="section-title">Detalle por patrón</h2>
{_group_table(by_pattern, "Patrón")}
<h2 class="section-title">Detalle por activo</h2>
{_group_table(result.by_symbol(), "Activo")}
<h2 class="section-title newpage">Operaciones</h2>
{_trades_table(result)}"""
    sides = "solo compras" if config.long_only else "compras y ventas cortas"
    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Backtesting de patrones</title>
<style>{STYLE}{EXTRA_STYLE}</style></head>
<body>
<h1>Backtesting de patrones chartistas</h1>
<p class="intro">Activos: {symbols} · generado el {generated.strftime("%d/%m/%Y %H:%M")}.
Responde a una pregunta: <b>si en el pasado se hubiera operado cada patrón al confirmarse,
¿qué habría pasado?</b> Resultados pasados no garantizan resultados futuros.</p>
{tiles}
<div class="howto"><b>Reglas de la simulación</b><ul>
<li>Se entra en la apertura siguiente al cierre que confirma el patrón ({sides}).</li>
<li>Se sale al alcanzar el <b>objetivo</b> clásico del patrón, al tocar su nivel de
<b>invalidación</b> (stop) o tras <b>{config.max_bars} sesiones</b>. Si objetivo y stop se tocan
el mismo día, se supone el stop (lo prudente).</li>
<li>Costes: comisión {num(config.commission_pct)} % por operación de compra o venta y
deslizamiento {num(config.slippage_pct)} %. Resultados en % del importe invertido.</li>
<li>Sin información del futuro: cada patrón se vuelve a detectar con los datos que había el
día de su ruptura. Se descartaron <b>{result.discarded}</b> candidatos que solo se veían a
posteriori{f" y {result.skipped_short} señales de venta (solo compras)" if result.skipped_short else ""}.</li>
</ul></div>
{problems}
{body}
<h2 class="section-title">Glosario</h2>
<dl class="glossary">
<dt>Factor de beneficio</dt><dd>Suma de ganancias dividida entre suma de pérdidas. Por encima
de 1, se ganó más de lo que se perdió.</dd>
<dt>Ventaja frente al azar</dt><dd>Resultado medio de las operaciones menos el de haber entrado
cualquier día en ese activo, en la misma dirección y durante el mismo número de sesiones. Si
es cercana a 0, el patrón no aportó nada.</dd>
<dt>Venta corta</dt><dd>Operación que gana si el precio baja (patrones bajistas).</dd>
</dl>
<footer>Análisis de Acciones · Datos: Yahoo Finance. Simulación con reglas fijas sobre datos
históricos; no incluye impuestos, dividendos ni el coste de mantener ventas cortas. No es
asesoramiento financiero.</footer>
</body></html>"""  # noqa: E501


def pattern_trades_csv(result: PatternBacktestResult) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["ticker", "patron", "direccion", "senal", "entrada", "precio_entrada",
                     "salida", "precio_salida", "motivo", "sesiones", "resultado_pct",
                     "referencia_azar_pct"])  # fmt: skip
    for t in result.trades:
        writer.writerow([safe_cell(v) for v in (
            t.symbol, t.pattern, "compra" if t.direction > 0 else "venta corta",
            t.signal_date.isoformat(), t.entry_date.isoformat(), round(t.entry_price, 4),
            t.exit_date.isoformat(), round(t.exit_price, 4), REASONS.get(t.exit_reason),
            t.bars_held, round(t.return_pct, 4),
            "" if t.baseline_pct is None else round(t.baseline_pct, 4),
        )])  # fmt: skip
    return buffer.getvalue()
