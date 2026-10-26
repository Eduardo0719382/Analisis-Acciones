"""Orders of the strategy profiles on Alpaca PAPER.

Run with ``python -m analisis_acciones.app.autotrade_cli``.

Without options it only shows the orders it would send (dry run). ``--send`` sends them to
the paper-trading account (simulated money; there is no option for a real-money account).
``--status`` shows what every profile holds. The Alpaca keys are the ones saved in the
program's Alpaca window (the system's credential store).

Schedule it (for example hourly) with the Windows Task Scheduler; see the README.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

import pandas as pd

from analisis_acciones.app.paths import AppPaths
from analisis_acciones.broker.alpaca import AlpacaPaperClient
from analisis_acciones.models.errors import AppError
from analisis_acciones.models.market import Interval
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.api_keys import KeyringStore
from analisis_acciones.services.autotrade import (
    holdings_report,
    load_ledger,
    render_state_md,
    run,
    valuation,
)
from analisis_acciones.services.forward_test import load_start, save_start


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Órdenes de los 12 perfiles en Alpaca paper")
    parser.add_argument(
        "--send", action="store_true",
        help="enviar las órdenes a la cuenta paper (sin esto, solo muestra)",
    )  # fmt: skip
    parser.add_argument("--status", action="store_true", help="mostrar lo que tiene cada perfil")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # the Windows console defaults to cp1252

    folder = AppPaths.default().root / "forward_test"
    ledger_path = folder / "autotrade.json"
    if args.status:
        print("\n".join(holdings_report(load_ledger(ledger_path))))
        return 0

    now = datetime.now(UTC)
    start = load_start(folder / "state.json")
    if start is None:
        start = now
        save_start(folder / "state.json", start)
    keys = KeyringStore()
    broker = AlpacaPaperClient(lambda: keys.get("alpaca_id"), lambda: keys.get("alpaca_secret"))
    provider = YahooFinanceProvider()

    def fetch(symbol: str, interval: Interval) -> pd.DataFrame:
        return provider.get_historical_data(symbol, interval).bars

    try:
        report = run(broker, fetch, start, ledger_path, send=args.send, now=now)
    except AppError as exc:
        print(f"Error: {exc.user_message}", file=sys.stderr)
        return 1
    mode = "ENVÍO a Alpaca paper (dinero ficticio)" if args.send else "SIMULACRO (no se envía nada)"
    print(f"{mode} · {now:%Y-%m-%d %H:%M} UTC · inicio de la prueba {start:%Y-%m-%d %H:%M} UTC")
    print("\n".join(report.lines))
    print("\n".join(holdings_report(load_ledger(ledger_path))))
    state = render_state_md(valuation(load_ledger(ledger_path), report.positions), now)
    (folder / "autotrade_estado.md").write_text(state, encoding="utf-8")
    with (folder / "autotrade_registro.md").open("a", encoding="utf-8") as log:
        log.write(f"\n\n---\n\n## {mode} · {now:%Y-%m-%d %H:%M} UTC\n\n")
        log.write("\n".join(f"- {line}" for line in report.lines) + f"\n\n{state}\n")
    print(f"\nResultados anotados en {folder / 'autotrade_estado.md'} y autotrade_registro.md")
    if not args.send:
        print("\nPara enviar de verdad (a la cuenta de práctica): añada --send")
    return 0


if __name__ == "__main__":
    sys.exit(main())
