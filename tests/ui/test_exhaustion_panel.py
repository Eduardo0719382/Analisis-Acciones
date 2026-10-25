from __future__ import annotations

from dataclasses import replace

from pytestqt.qtbot import QtBot

from analisis_acciones.analysis.exhaustion import Assessment, Outcome, assess
from analisis_acciones.models.market import BarSeries, Interval
from analisis_acciones.services.scanner import ScanResult
from analisis_acciones.ui import strings
from analisis_acciones.ui.exhaustion_panel import ExhaustionPanel, assessment_html, reading
from analisis_acciones.ui.scanner_dialog import ScannerDialog
from tests.ui.test_scanner_dialog import row
from tests.unit.test_exhaustion import bars_from, rally


def test_panel_shows_conditions_and_record(qtbot: QtBot) -> None:
    panel = ExhaustionPanel()
    qtbot.addWidget(panel)
    bars = bars_from(rally())
    panel.set_series(BarSeries("RUN", Interval.D1, bars, "test"))
    text = panel.view.toPlainText()
    assert "La subida muestra señales de agotamiento" in text
    assert "RSI en sobrecompra" in text and "A 20 sesiones" in text
    assert "no una predicción" in text
    assert "RUN" in panel.title.text()
    # The bar of a session still in progress is not used.
    panel.set_series(BarSeries("RUN", Interval.D1, bars, "test"), session_in_progress=True)
    assert panel.assessment is not None
    assert panel.assessment.as_of == bars.index[-2]


def test_reading_compares_with_baseline() -> None:
    a = assess(bars_from(rally()))

    def with_outcome(against: int, events: int, base: float) -> Assessment:
        return replace(a, outcomes=[Outcome(20, events, against, 1.0, 500, base)])

    assert reading(with_outcome(15, 20, 45.0)) == strings.EXH_READ_USEFUL_UP
    assert reading(with_outcome(3, 20, 45.0)) == strings.EXH_READ_CONTINUE_UP
    assert reading(with_outcome(5, 20, 45.0)) == strings.EXH_READ_NO_EDGE  # p ≈ 0.06: luck
    mixed = replace(a, outcomes=[Outcome(10, 20, 15, 1.0, 500, 45.0),
                                 Outcome(20, 20, 3, 1.0, 500, 45.0)])  # fmt: skip
    assert reading(mixed) == strings.EXH_READ_MIXED
    assert reading(with_outcome(9, 20, 45.0)) == strings.EXH_READ_NO_EDGE
    assert reading(with_outcome(3, 5, 45.0)) == strings.EXH_READ_FEW
    assert "<script" not in assessment_html(a)


def test_scanner_column_and_filter(qtbot: QtBot) -> None:
    dialog = ScannerDialog(None, [])  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    tired = replace(row("TIRED", 1, 0), exhaustion=4, exhaustion_total=6)
    fresh = row("FRESH", 1, 0)
    dialog.show_result(ScanResult([tired, fresh]))
    dialog.filter.setCurrentIndex(dialog.filter.findData("exhaustion"))
    assert dialog.table.rowCount() == 1 and dialog.table.item(0, 0).text() == "TIRED"
    col = strings.SCAN_COLUMNS.index("Agotamiento")
    assert dialog.table.item(0, col).text() == "subida 4/6"
