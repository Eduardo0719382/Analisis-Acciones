"""Core layers must stay independent from the UI toolkit."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "analisis_acciones"
# Layers that must remain reusable if the UI is replaced (see PLAN.md).
CORE_LAYERS = [
    "models",
    "data",
    "providers",
    "indicators",
    "analysis",
    "alerts",
    "strategies",
    "backtesting",
    "forecast",
    "portfolio",
    "patterns",
    "storage",
    "services",
    "utils",
    "mobile",  # phone logic: no Qt and no Flet (the Flet screens live in mobile/ at the root)
]
FORBIDDEN = (
    "PySide6",
    "flet",
    "shiboken6",
    "analisis_acciones.ui",
    "analisis_acciones.charts",
    "analisis_acciones.app",
)


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def _core_files() -> list[Path]:
    files: list[Path] = []
    for layer in CORE_LAYERS:
        files.extend(sorted((PACKAGE_ROOT / layer).rglob("*.py")))
    return files


def test_core_files_found() -> None:
    assert _core_files(), "no core modules found; is PACKAGE_ROOT correct?"


@pytest.mark.parametrize("path", _core_files(), ids=lambda p: str(p.relative_to(PACKAGE_ROOT)))
def test_core_layer_does_not_import_ui(path: Path) -> None:
    bad = [name for name in _imports(path) if name.startswith(FORBIDDEN)]
    assert not bad, f"{path.name} imports UI/app modules: {bad}"
