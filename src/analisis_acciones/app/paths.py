"""Filesystem locations used by the application."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "AnalisisAcciones"
HOME_ENV_VAR = "ANALISIS_ACCIONES_HOME"


@dataclass(frozen=True)
class AppPaths:
    root: Path

    @property
    def database(self) -> Path:
        return self.root / "analisis_acciones.sqlite3"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)

    @classmethod
    def default(cls) -> AppPaths:
        override = os.environ.get(HOME_ENV_VAR, "").strip()
        if override:
            return cls(Path(override).expanduser())
        return cls(Path(user_data_dir(APP_NAME, appauthor=False)))
