"""API keys of optional data sources, kept out of the repository and of the database.

* PC: the operating system's credential store (Windows Credential Manager, macOS Keychain…)
  through ``keyring``. An environment variable ``ANALISIS_ACCIONES_<SERVICE>_KEY`` takes
  precedence (handy for scripts); nothing is written to files by the program.
* Phone: a file in the app's private storage, which other apps cannot read.

Keys are never logged and never shown back in full (``masked``).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Protocol

from analisis_acciones.models.errors import UserError

logger = logging.getLogger(__name__)

SERVICES = {"alphavantage": "Alpha Vantage", "finnhub": "Finnhub", "twelvedata": "Twelve Data"}
SIGNUP_URLS = {
    "alphavantage": "https://www.alphavantage.co/support/#api-key",
    "finnhub": "https://finnhub.io/register",
    "twelvedata": "https://twelvedata.com/register",
}
KEYRING_SERVICE = "AnalisisAcciones"
_KEY = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")


def env_name(service: str) -> str:
    return f"ANALISIS_ACCIONES_{service.upper()}_KEY"


def clean_key(service: str, raw: str) -> str:
    if service not in SERVICES:
        raise UserError(f"unknown service {service!r}", user_message="Servicio desconocido.")
    key = raw.strip()
    if not _KEY.match(key):
        raise UserError(
            "malformed api key",
            user_message=f"La clave de {SERVICES[service]} no tiene un formato válido "
            "(solo letras, números, guiones; de 8 a 128 caracteres).",
        )
    return key


def masked(key: str | None) -> str:
    return "" if not key else f"{key[:3]}…{key[-3:]}" if len(key) > 8 else "…"


class KeyStore(Protocol):
    def get(self, service: str) -> str | None: ...
    def set(self, service: str, key: str) -> None: ...
    def delete(self, service: str) -> None: ...


class MemoryKeyStore:
    def __init__(self) -> None:
        self._keys: dict[str, str] = {}

    def get(self, service: str) -> str | None:
        return self._keys.get(service)

    def set(self, service: str, key: str) -> None:
        self._keys[service] = clean_key(service, key)

    def delete(self, service: str) -> None:
        self._keys.pop(service, None)


class KeyringStore:
    """OS credential store; the environment variable wins when set."""

    def get(self, service: str) -> str | None:
        env = os.environ.get(env_name(service), "").strip()
        if env:
            return env
        try:
            import keyring

            value = keyring.get_password(KEYRING_SERVICE, service)
        except Exception as exc:  # no backend available (some Linux setups)
            logger.info("No credential store for %s: %s", service, type(exc).__name__)
            return None
        return value or None

    def set(self, service: str, key: str) -> None:
        key = clean_key(service, key)
        try:
            import keyring

            keyring.set_password(KEYRING_SERVICE, service, key)
        except Exception as exc:
            raise UserError(
                f"keyring unavailable: {type(exc).__name__}",
                user_message="No se pudo guardar la clave en el almacén de credenciales del "
                f"sistema. Alternativa: variable de entorno {env_name(service)}.",
            ) from exc

    def delete(self, service: str) -> None:
        try:
            import keyring

            keyring.delete_password(KEYRING_SERVICE, service)
        except Exception as exc:
            logger.info("Could not delete %s key: %s", service, type(exc).__name__)


class FileKeyStore:
    """JSON file readable only by its owner (the app's private storage on Android)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _read(self) -> dict[str, str]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {k: v for k, v in data.items() if isinstance(v, str)} if isinstance(data, dict) \
            else {}  # fmt: skip

    def _write(self, data: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(tmp, 0o600)
        tmp.replace(self._path)

    def get(self, service: str) -> str | None:
        return self._read().get(service) or None

    def set(self, service: str, key: str) -> None:
        data = self._read()
        data[service] = clean_key(service, key)
        self._write(data)

    def delete(self, service: str) -> None:
        data = self._read()
        if data.pop(service, None) is not None:
            self._write(data)
