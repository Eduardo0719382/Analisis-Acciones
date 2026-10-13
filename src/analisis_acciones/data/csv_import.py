"""Parse user-supplied CSV files of daily OHLCV bars.

Accepted layout (header names are case-insensitive, Spanish or English):

    date,open,high,low,close,volume[,adj close]
    fecha;apertura;maximo;minimo;cierre;volumen

* separator: comma or semicolon (with semicolons, a decimal comma is accepted);
* dates: ``YYYY-MM-DD`` or ``DD/MM/YYYY``; anything else is rejected rather
  than guessed, because day/month confusion would silently corrupt the series.

File contents are treated purely as data.
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from pathlib import Path

import pandas as pd

from analisis_acciones.data.validation import validate_bars
from analisis_acciones.models.errors import UserError

MAX_FILE_BYTES = 50 * 1024 * 1024

_ALIASES = {
    "date": "date", "fecha": "date", "datetime": "date", "time": "date",
    "open": "open", "apertura": "open", "abrir": "open",
    "high": "high", "maximo": "high", "max": "high", "alto": "high",
    "low": "low", "minimo": "low", "min": "low", "bajo": "low",
    "close": "close", "cierre": "close", "ultimo": "close", "last": "close",
    "adj close": "adj_close", "adj_close": "adj_close", "adjclose": "adj_close",
    "cierre ajustado": "adj_close",
    "volume": "volume", "volumen": "volume", "vol": "volume",
}  # fmt: skip
_REQUIRED = ("date", "open", "high", "low", "close")
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}")
_DMY = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")


def _canonical(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    text = text.strip().strip('"').lower()
    return _ALIASES.get(text, text)


def _invalid(detail: str, message: str) -> UserError:
    return UserError(f"CSV import: {detail}", user_message=message)


def read_csv_bars(path: Path, symbol: str) -> tuple[pd.DataFrame, list[str]]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise _invalid(str(exc), "No se pudo leer el archivo.") from exc
    if size > MAX_FILE_BYTES:
        raise _invalid(
            f"file too large ({size} bytes)", "El archivo es demasiado grande (máx. 50 MB)."
        )
    try:
        raw = path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError:
        raw = path.read_bytes().decode("latin-1")
    except OSError as exc:
        raise _invalid(str(exc), "No se pudo leer el archivo.") from exc
    return parse_csv_text(raw, symbol)


def parse_csv_text(text: str, symbol: str) -> tuple[pd.DataFrame, list[str]]:
    sample = text[:4096]
    if not sample.strip():
        raise _invalid("empty file", "El archivo está vacío.")
    first_line = sample.splitlines()[0]
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","

    try:
        frame = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            dtype=str,
            quoting=csv.QUOTE_MINIMAL,
            skipinitialspace=True,
        )
    except (pd.errors.ParserError, ValueError) as exc:
        raise _invalid(str(exc), "El archivo no tiene un formato CSV válido.") from exc

    frame.columns = [_canonical(str(c)) for c in frame.columns]
    missing = [c for c in _REQUIRED if c not in frame.columns]
    if missing:
        raise _invalid(
            f"missing columns {missing}",
            "Faltan columnas obligatorias: fecha, apertura, máximo, mínimo y cierre "
            "(o date, open, high, low, close).",
        )

    dates = frame.pop("date").astype(str).str.strip()
    if dates.map(lambda d: bool(_ISO.match(d))).all():
        parsed = pd.to_datetime(dates.str[:10], format="%Y-%m-%d", errors="coerce")
    elif dates.map(lambda d: bool(_DMY.match(d))).all():
        parsed = pd.to_datetime(dates, format="%d/%m/%Y", errors="coerce")
    else:
        raise _invalid(
            "unsupported date format",
            "Formato de fecha no reconocido. Use AAAA-MM-DD o DD/MM/AAAA en todas las filas.",
        )
    if parsed.isna().any():
        raise _invalid("invalid dates", "El archivo contiene fechas inválidas.")

    # With ";" files the decimal mark may be a comma ("1.234,56"); decide per file
    # instead of per cell so "123.45" is never misread as 12345.
    cells = frame.astype(str)
    decimal_comma = delimiter == ";" and cells.apply(lambda c: c.str.contains(",")).any().any()

    numeric = {}
    for column in frame.columns:
        values = frame[column].astype(str).str.strip()
        if decimal_comma:
            values = values.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        elif delimiter == ",":
            values = values.str.replace(",", "", regex=False)  # quoted thousands separators
        values = values.where(~values.isin(["", "nan", "NaN"]))
        numeric[column] = pd.to_numeric(values, errors="coerce")
    bars = pd.DataFrame(numeric)
    bars.index = pd.DatetimeIndex(parsed.to_numpy(), name="date").normalize()
    return validate_bars(bars, symbol)
