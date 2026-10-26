"""Is there a newer phone build? Read from the project's GitHub release ``movil``.

Every push builds the APK in GitHub Actions and replaces the asset of the release
tagged ``movil``; its name carries the build number
(``AnalisisAcciones-<version>-build<N>.apk``). The app compares that number with its
own (written into ``build_info.json`` when it is built). Android does not let an app
replace itself silently, so the user is offered the download and installs it.

The release data comes from the network and is treated as data: only the asset name,
size and download URL are read, and the URL must point to GitHub.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from importlib import resources
from typing import Any

from analisis_acciones.providers.yahoo_http import Fetcher, http_get

REPOSITORY = "Eduardo0719382/Analisis-Acciones"
RELEASE_TAG = "movil"
RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{RELEASE_TAG}"
RELEASE_PAGE = f"https://github.com/{REPOSITORY}/releases/tag/{RELEASE_TAG}"
_ASSET = re.compile(
    r"^AnalisisAcciones-(?P<version>[0-9][0-9A-Za-z.\-]{0,20})-build(?P<build>\d{1,9})\.apk$"
)
_ALLOWED_URL = f"https://github.com/{REPOSITORY}/releases/download/"


@dataclass(frozen=True)
class BuildInfo:
    version: str
    build: int  # 0 = development copy (not built by GitHub Actions)
    commit: str = ""


@dataclass(frozen=True)
class AvailableBuild:
    version: str
    build: int
    url: str
    size_mb: float


def current_build() -> BuildInfo:
    """The build number written next to this module when the APK was built."""
    from analisis_acciones import __version__

    try:
        text = (
            resources.files("analisis_acciones.mobile")
            .joinpath("build_info.json")
            .read_text(encoding="utf-8")
        )
        data = json.loads(text)
    except (FileNotFoundError, OSError, ValueError):
        return BuildInfo(__version__, 0)
    build = data.get("build") if isinstance(data, dict) else None
    commit = data.get("commit") if isinstance(data, dict) else None
    return BuildInfo(
        __version__,
        build if isinstance(build, int) and build >= 0 else 0,
        commit[:12] if isinstance(commit, str) else "",
    )


def latest_build(fetch: Fetcher = http_get) -> AvailableBuild | None:
    """The APK currently published, or None if there is none."""
    data: Any = json.loads(fetch(RELEASE_API).decode("utf-8"))
    assets = data.get("assets") if isinstance(data, dict) else None
    best: AvailableBuild | None = None
    for asset in assets if isinstance(assets, list) else []:
        if not isinstance(asset, dict):
            continue
        name, url = asset.get("name"), asset.get("browser_download_url")
        match = _ASSET.match(name) if isinstance(name, str) else None
        if match is None or not isinstance(url, str) or not url.startswith(_ALLOWED_URL):
            continue
        size = asset.get("size")
        mb = round(size / 1_048_576, 1) if isinstance(size, int) else 0.0
        found = AvailableBuild(match["version"], int(match["build"]), url, mb)
        if best is None or found.build > best.build:
            best = found
    return best


def newer_than(current: BuildInfo, available: AvailableBuild | None) -> bool:
    return available is not None and available.build > current.build
