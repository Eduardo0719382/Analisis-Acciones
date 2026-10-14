from __future__ import annotations

import csv
import io
from datetime import date, datetime

from analisis_acciones.services.scan_report import num, scan_csv, scan_report_html, verdict
from analisis_acciones.services.scanner import (
    BREAKOUT_NOTE,
    FORMING_NOTE,
    PatternNote,
    ScanResult,
    ScanRow,
)


def make_row(symbol: str = "AAA", bullish: tuple[str, ...] = ("Tendencia alcista detectada",),
             bearish: tuple[str, ...] = (), **extra: object) -> ScanRow:  # fmt: skip
    values: dict[str, object] = dict(
        symbol=symbol, close=101.5, change_pct=1.25, rsi14=72.0, bullish=bullish,
        bearish=bearish,
        pattern_notes=(PatternNote("Doble suelo", BREAKOUT_NOTE, 1),
                       PatternNote("Triángulo simétrico", FORMING_NOTE, 0)),
        elliott="impulso alcista 1-2-3", support_pct=1.5, resistance_pct=2.0, support=100.0,
        resistance=103.53, elliott_direction=1, as_of=date(2025, 3, 7),
        history=tuple(100 + i * 0.1 for i in range(60)), history_start=date(2024, 12, 12),
    )  # fmt: skip
    values.update(extra)
    return ScanRow(**values)  # type: ignore[arg-type]


def test_spanish_number_format() -> None:
    assert num(1234.5) == "1.234,50"
    assert num(-0.456, 1) == "−0,5"
    assert num(2.0, 2, sign=True) == "+2,00"
    assert num(-0.0001, 2) == "0,00"  # no "−0,00"
    assert num(None) == "—"


def test_verdict_sentences() -> None:
    assert verdict(make_row())[:2] == ("up", "▲")
    assert verdict(make_row(bullish=(), bearish=("x",)))[0] == "down"
    assert verdict(make_row(bullish=("a",), bearish=("b",)))[2].startswith("Señales mixtas")
    assert verdict(make_row(bullish=()))[2] == "Sin señales destacadas"


def test_report_contents_and_escaping() -> None:
    evil = make_row(symbol="<script>alert(1)</script>", bullish=("<b>x</b>",))
    html = scan_report_html(ScanResult([make_row(), evil], ["ZZZ: <no> encontrado"]),
                            datetime(2025, 3, 8, 9, 30), note="Filtro aplicado: X.")  # fmt: skip
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html and "&lt;no&gt;" in html
    assert "<svg" in html and "Soporte 100,00" in html and "Resistencia 103,53" in html
    assert "RSI 72,0" in html and "sobrecompra" in html
    assert "Doble suelo · ruptura reciente" in html
    assert "Elliott: posible impulso alcista 1-2-3" in html
    assert "Filtro aplicado: X." in html
    assert "08/03/2025 09:30" in html and "hasta el 07/03/2025" in html
    assert "ni es una recomendación de inversión" in " ".join(html.split())
    assert "http" not in html.split("<body>")[1].split("Yahoo")[0]  # no external resources


def test_report_without_levels_or_history() -> None:
    row = make_row(support=None, resistance=None, support_pct=None, resistance_pct=None,
                   history=(), pattern_notes=(), elliott="", rsi14=None)  # fmt: skip
    html = scan_report_html(ScanResult([row]), datetime(2025, 3, 8))
    assert "No hay soportes ni resistencias claros" in html
    assert "Sin historial suficiente" in html and "RSI sin datos" in html


def test_csv_is_formula_safe() -> None:
    text = scan_csv(ScanResult([make_row(symbol="=HYPERLINK(1)")]))
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0][0] == "ticker" and rows[1][0] == "'=HYPERLINK(1)"
    assert rows[1][7] == "Predominan las señales alcistas"
    assert rows[1][10] == "Doble suelo (ruptura reciente); Triángulo simétrico (en formación)"
