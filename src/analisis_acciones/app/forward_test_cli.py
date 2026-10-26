"""Command line of the forward test: ``python -m analisis_acciones.app.forward_test_cli``.

Without arguments: continues the test (it starts on the first run), prints the report and
saves it next to the state. ``--since YYYY-MM-DD`` prints a historical replay instead and
changes nothing. ``--reset`` restarts the test now.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

import pandas as pd

from analisis_acciones.app.paths import AppPaths
from analisis_acciones.models.market import Interval
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.forward_test import (
    load_start,
    render_report,
    run_all,
    save_start,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prueba hacia adelante de los 12 perfiles")
    parser.add_argument("--since", help="reproducción histórica desde AAAA-MM-DD (no guarda)")
    parser.add_argument("--reset", action="store_true", help="reiniciar la prueba ahora")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the Windows console defaults to cp1252

    folder = AppPaths.default().root / "forward_test"
    state = folder / "state.json"
    now = datetime.now(UTC)
    provider = YahooFinanceProvider()

    def fetch(symbol: str, interval: Interval) -> pd.DataFrame:
        return provider.get_historical_data(symbol, interval).bars

    start: datetime | None
    if args.since:
        start = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        hypothetical = True
    else:
        start = None if args.reset else load_start(state)
        hypothetical = False
    if start is None:
        start = now
        save_start(state, start)
    report = render_report(run_all(fetch, start, now), start, now, hypothetical)
    print(report)
    if not hypothetical:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "informe.md").write_text(report, encoding="utf-8")
        with (folder / "historial.md").open("a", encoding="utf-8") as history:
            history.write(f"\n\n---\n\n{report}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
