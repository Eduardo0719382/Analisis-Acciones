"""Lab profiles: who each agent is and the hard limits the executor enforces on it.

They live in ``laboratorio/perfiles.json`` at the repository root, so the weekly review
(Opus) changes them with a normal commit and the history shows what changed when. The
agent reads its personality and limits from here; the executor enforces the limits again,
whatever the agent decides.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from analisis_acciones.broker.alpaca import to_alpaca_symbol
from analisis_acciones.models.errors import UserError

CONFIG_ENV_VAR = "ANALISIS_LAB_CONFIG"
DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "laboratorio" / "perfiles.json"

FREQUENCIES = ("1h", "2h", "4h", "diaria", "semanal", "mensual")
#: Analysis bars for each frequency.
TIMEFRAME = {"1h": "1h", "2h": "1h", "4h": "4h", "diaria": "1d", "semanal": "1w",
             "mensual": "1mo"}  # fmt: skip
#: Minimum hours between two decisions of a profile (intraday frequencies).
MIN_GAP_H = {"1h": 0.9, "2h": 1.9, "4h": 3.8}
TOOLS = ("reglas", "agotamiento", "elliott", "patrones", "proyeccion", "fundamentales", "noticias")
STATES = ("activo", "pausado", "eliminado")
_ID = re.compile(r"^P\d{2}$")


@dataclass(frozen=True)
class Limits:
    max_pct_activo: float  # largest share of the profile's value in one asset, %
    stop_posicion_pct: float  # a position losing this much is sold by the executor, %
    stop_perfil_pct: float  # a profile that lost this much from its capital stops buying, %
    max_operaciones_dia: int  # orders the agent may send per UTC day (forced stops excluded)
    min_orden_usd: float = 2.0


@dataclass(frozen=True)
class LabProfile:
    id: str
    nombre: str
    hipotesis: str
    frecuencia: str
    estilo: str
    universo: tuple[str, ...]
    herramientas: tuple[str, ...]
    limites: Limits
    fallo: str
    instrucciones: str
    estado: str = "activo"
    capital: float = 100.0

    @property
    def has_stocks(self) -> bool:
        return any(not to_alpaca_symbol(s)[1] for s in self.universo)

    @property
    def only_stocks(self) -> bool:
        return all(not to_alpaca_symbol(s)[1] for s in self.universo)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "nombre": self.nombre, "hipotesis": self.hipotesis,
            "frecuencia": self.frecuencia, "estilo": self.estilo, "universo": list(self.universo),
            "herramientas": list(self.herramientas), "limites": vars(self.limites),
            "fallo": self.fallo, "instrucciones": self.instrucciones, "estado": self.estado,
            "capital": self.capital,
        }  # fmt: skip


def _bad(msg: str) -> UserError:
    return UserError(f"lab config: {msg}", user_message=f"perfiles.json no es válido: {msg}")


def parse_profile(d: dict[str, Any]) -> LabProfile:
    pid = str(d.get("id", ""))
    if not _ID.match(pid):
        raise _bad(f"id {pid!r} (debe ser P01, P02…)")
    freq = str(d.get("frecuencia", ""))
    if freq not in FREQUENCIES:
        raise _bad(f"{pid}: frecuencia {freq!r}; use una de {', '.join(FREQUENCIES)}")
    universe = tuple(dict.fromkeys(str(s).strip().upper() for s in d.get("universo", [])))
    if not universe:
        raise _bad(f"{pid}: universo vacío")
    for s in universe:
        to_alpaca_symbol(s)  # raises for anything that is not AAPL or BTC-USD
    tools = tuple(str(t) for t in d.get("herramientas", []))
    unknown = [t for t in tools if t not in TOOLS]
    if unknown:
        raise _bad(f"{pid}: herramientas desconocidas {unknown}")
    lim = d.get("limites") or {}
    try:
        limits = Limits(
            max_pct_activo=float(lim["max_pct_activo"]),
            stop_posicion_pct=float(lim["stop_posicion_pct"]),
            stop_perfil_pct=float(lim["stop_perfil_pct"]),
            max_operaciones_dia=int(lim["max_operaciones_dia"]),
            min_orden_usd=float(lim.get("min_orden_usd", 2.0)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise _bad(f"{pid}: límites incompletos ({exc})") from None
    if not (0 < limits.max_pct_activo <= 100 and 0 < limits.stop_posicion_pct <= 100
            and 0 < limits.stop_perfil_pct <= 100 and limits.max_operaciones_dia >= 0
            and limits.min_orden_usd >= 1):  # fmt: skip
        raise _bad(f"{pid}: límites fuera de rango")
    state = str(d.get("estado", "activo"))
    if state not in STATES:
        raise _bad(f"{pid}: estado {state!r}")
    capital = float(d.get("capital", 100.0))
    if not 1 <= capital <= 1000:
        raise _bad(f"{pid}: capital fuera de rango")
    return LabProfile(
        id=pid, nombre=str(d.get("nombre", pid)), hipotesis=str(d.get("hipotesis", "")),
        frecuencia=freq, estilo=str(d.get("estilo", "")), universo=universe,
        herramientas=tools, limites=limits, fallo=str(d.get("fallo", "")),
        instrucciones=str(d.get("instrucciones", "")), estado=state, capital=capital,
    )  # fmt: skip


def config_path() -> Path:
    override = os.environ.get(CONFIG_ENV_VAR, "").strip()
    return Path(override) if override else DEFAULT_CONFIG


def load_profiles(path: Path | None = None) -> dict[str, LabProfile]:
    path = path or config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _bad(f"no se pudo leer {path} ({exc})") from None
    profiles = [parse_profile(d) for d in raw.get("perfiles", [])]
    ids = [p.id for p in profiles]
    if len(ids) != len(set(ids)):
        raise _bad("ids repetidos")
    return {p.id: p for p in profiles}
