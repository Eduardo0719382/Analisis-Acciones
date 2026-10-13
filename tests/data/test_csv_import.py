from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from analisis_acciones.data.csv_import import parse_csv_text, read_csv_bars
from analisis_acciones.models.errors import DataError, UserError

ENGLISH = """Date,Open,High,Low,Close,Adj Close,Volume
2024-01-02,10.0,11.0,9.5,10.5,10.4,1000
2024-01-03,10.5,12.0,10.0,11.5,11.4,2000
"""

SPANISH = """fecha;apertura;máximo;mínimo;cierre;volumen
02/01/2024;1.010,5;1.020,0;1.000,0;1.015,25;1500
03/01/2024;1.015,0;1.030,0;1.010,0;1.025,75;2500
"""


def test_english_csv() -> None:
    bars, warnings = parse_csv_text(ENGLISH, "CSV:X")
    assert warnings == []
    assert list(bars.index) == [pd.Timestamp("2024-01-02"), pd.Timestamp("2024-01-03")]
    assert bars.loc["2024-01-03", "close"] == 11.5
    assert bars.loc["2024-01-02", "adj_close"] == 10.4
    assert bars.loc["2024-01-03", "volume"] == 2000


def test_spanish_csv_with_decimal_comma_and_day_first_dates() -> None:
    bars, _ = parse_csv_text(SPANISH, "CSV:X")
    assert bars.index[0] == pd.Timestamp("2024-01-02")  # 02/01 is 2 January
    assert bars.iloc[0]["open"] == 1010.5
    assert bars.iloc[1]["close"] == 1025.75
    assert bars["adj_close"].isna().all()


def test_semicolon_with_decimal_point_is_not_misread() -> None:
    text = "date;open;high;low;close\n2024-01-02;123.45;125.00;120.00;124.50\n"
    bars, _ = parse_csv_text(text, "CSV:X")
    assert bars.iloc[0]["open"] == 123.45


def test_quoted_thousands_with_comma_delimiter() -> None:
    text = 'date,open,high,low,close,volume\n2024-01-02,10,11,9,10.5,"1,234,567"\n'
    bars, _ = parse_csv_text(text, "CSV:X")
    assert bars.iloc[0]["volume"] == 1_234_567


def test_missing_columns() -> None:
    with pytest.raises(UserError) as info:
        parse_csv_text("date,open,close\n2024-01-02,1,2\n", "CSV:X")
    assert "Faltan columnas" in info.value.user_message


def test_ambiguous_date_format_rejected() -> None:
    with pytest.raises(UserError) as info:
        parse_csv_text("date,open,high,low,close\n01-02-2024,1,2,0.5,1.5\n", "CSV:X")
    assert "Formato de fecha" in info.value.user_message


def test_invalid_dates_rejected() -> None:
    with pytest.raises(UserError):
        parse_csv_text("date,open,high,low,close\n2024-13-45,1,2,0.5,1.5\n", "CSV:X")


def test_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(UserError, match="empty"):
        read_csv_bars(path, "CSV:X")


def test_text_cells_are_data_not_code() -> None:
    rows = "".join(f"2024-01-{d:02d},1,2,1,1.5\n" for d in range(2, 31))
    text = "date,open,high,low,close\n2024-01-01,=cmd|' /C calc'!A0,2,1,1.5\n" + rows
    bars, warnings = parse_csv_text(text, "CSV:X")
    assert len(bars) == 29  # the formula-like cell is just an invalid number
    assert warnings


def test_mostly_invalid_file_is_rejected() -> None:
    text = "date,open,high,low,close\n2024-01-02,abc,2,1,1.5\n2024-01-03,1,2,1,1.5\n"
    with pytest.raises(DataError):
        parse_csv_text(text, "CSV:X")


def test_latin1_file(tmp_path: Path) -> None:
    path = tmp_path / "latin.csv"
    path.write_bytes(SPANISH.encode("latin-1"))
    bars, _ = read_csv_bars(path, "CSV:X")
    assert len(bars) == 2
