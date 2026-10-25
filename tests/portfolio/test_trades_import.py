from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from analisis_acciones.data.trades_import import parse_trades_text, read_trades_csv
from analisis_acciones.models.errors import UserError
from analisis_acciones.providers.yahoo import YahooFinanceProvider
from analisis_acciones.services.market_data_service import MarketDataService
from analisis_acciones.services.paper_portfolio import PaperPortfolioService
from analisis_acciones.storage.database import open_database
from tests.synthetic import FakeYahooClient, synthetic_daily

SPANISH = """Fecha;Ticker;Operación;Cantidad;Precio;Comisión;Divisa;Nota
15/01/2024;test;Compra;10;100,50;1,00;USD;primera
2024-02-01 15:30;TEST;Venta;4;1.110,25;0,5;;=HYPERLINK("x")
31/02/2024;TEST;Compra;1;100;0;;fecha imposible
01/03/2024;TE ST;Compra;1;100;0;;ticker malo
01/03/2024;TEST;Regalo;1;100;0;;operación rara
01/03/2024;TEST;Compra;0;100;0;;cantidad cero
01/03/2024;TEST;Compra;1;-5;0;;precio negativo
02/03/2024;TEST;Compra;1;100;0;XX1;divisa mala
"""


def test_spanish_file_with_errors_reported_per_line() -> None:
    parsed = parse_trades_text(SPANISH)
    assert [t.line for t in parsed.trades] == [2, 3]
    first, second = parsed.trades
    assert (first.day, first.symbol, first.side, first.quantity) == (date(2024, 1, 15), "TEST",
                                                                    "buy", 10)  # fmt: skip
    assert first.price == 100.5 and first.commission == 1.0 and first.currency == "USD"
    assert second.side == "sell" and second.price == 1110.25 and second.currency is None
    assert second.note == '=HYPERLINK("x")'  # kept as plain text, never evaluated
    assert len(parsed.errors) == 6
    assert parsed.errors[0].startswith("Línea 4: fecha")
    assert not parsed.missing_commission


def test_english_file_sign_of_quantity_and_missing_columns() -> None:
    text = 'Date,Symbol,Quantity,Price\n2024-01-15,AAPL,5,"1,234.50"\n2024-01-20,AAPL,-2,1300\n'
    parsed = parse_trades_text(text)
    found = [(t.side, t.quantity, t.price) for t in parsed.trades]
    assert found == [("buy", 5, 1234.5), ("sell", 2, 1300)]
    assert parsed.missing_commission
    with pytest.raises(UserError):
        parse_trades_text("fecha,ticker\n2024-01-01,AAPL\n")
    with pytest.raises(UserError):
        parse_trades_text("")
    us = parse_trades_text("date,ticker,side,qty,price\n01/31/2024,AAPL,buy,1,10\n")
    assert not us.trades and "fecha" in us.errors[0]  # MM/DD is rejected, not guessed


def test_file_limits(tmp_path: Path) -> None:
    big = tmp_path / "grande.csv"
    big.write_bytes(b"x" * (5 * 1024 * 1024 + 1))
    with pytest.raises(UserError):
        read_trades_csv(big)
    latin = tmp_path / "latin.csv"
    latin.write_bytes("Fecha;Ticker;Operación;Cantidad;Precio\n2024-01-15;TEST;compra;1;10\n"
                      .encode("latin-1"))  # fmt: skip
    assert len(read_trades_csv(latin).trades) == 1


@pytest.fixture
def service() -> Iterator[PaperPortfolioService]:
    client = FakeYahooClient(synthetic_daily(sessions=60))
    client.known = {"TEST", "SPY"}
    now = datetime(2024, 3, 30, 12, tzinfo=UTC)
    market = MarketDataService(YahooFinanceProvider(client), open_database(":memory:"),
                               clock=lambda: now)  # fmt: skip
    yield PaperPortfolioService(open_database(":memory:"), market, clock=lambda: now)
    market.close()


def test_preview_and_import(service: PaperPortfolioService) -> None:
    (p,) = service.portfolios()
    service.add_trade(p.id, "TEST", "buy", 1, price=50.0, trade_date=date(2024, 1, 2))
    parsed = parse_trades_text(SPANISH)
    preview = service.prepare_import(p.id, parsed.trades)
    assert len(preview.trades) == 2 and preview.problems == []
    assert preview.cash_needed == pytest.approx(50 + 10 * 100.5 + 1)
    assert service.import_trades(p.id, preview) == 2
    trades = service.trades(p.id)
    assert [t.note for t in trades] == ["", "primera", '=HYPERLINK("x")']
    report = service.report(p.id)
    assert report.valuation.holdings[0].quantity == pytest.approx(7)

    # A history that sells more than was bought is refused as a whole.
    bad = parse_trades_text("fecha;ticker;operacion;cantidad;precio\n"
                            "2024-03-01;TEST;venta;100;10\n")  # fmt: skip
    refused = service.prepare_import(p.id, bad.trades)
    assert refused.cash_needed is None and "no se pueden vender" in refused.problems[-1]
    with pytest.raises(UserError):
        service.import_trades(p.id, refused)
    assert len(service.trades(p.id)) == 3  # nothing stored


def test_import_needs_enough_cash(service: PaperPortfolioService) -> None:
    small = service.create("Pequeña", 500)
    parsed = parse_trades_text(SPANISH)
    preview = service.prepare_import(small.id, parsed.trades)
    assert preview.cash_needed is not None and preview.cash_needed > 500
    with pytest.raises(UserError):
        service.import_trades(small.id, preview)
    future = parse_trades_text(
        "fecha;ticker;operacion;cantidad;precio\n2030-01-01;TEST;compra;1;1\n"
    )
    assert "fecha futura" in service.prepare_import(small.id, future.trades).problems[0]


BROKER = """Fecha;Operación;Ticker;Cantidad;Precio;Comisión;Importe;Nota
02/01/2024;Ingreso;;;;;5.000,00;transferencia
15/01/2024;Compra;TEST;10;100;1;;
15/02/2024;Dividendo;TEST;;;;12,50;dividendo trimestral
29/02/2024;Intereses;;;;;3,10;
01/03/2024;Comisión de custodia;;;;;2,00;
05/03/2024;Retirada;;;;;100;
06/03/2024;Dividendo;;;;;5;sin ticker
"""


def test_broker_cash_rows_are_read() -> None:
    parsed = parse_trades_text(BROKER)
    assert [t.symbol for t in parsed.trades] == ["TEST"]
    kinds = [(c.kind, c.amount, c.symbol) for c in parsed.cash]
    assert kinds == [("deposit", 5000.0, ""), ("cash_dividend", 12.5, "TEST"),
                     ("interest", 3.1, ""), ("fee", 2.0, ""),
                     ("withdrawal", 100.0, "")]  # fmt: skip
    assert parsed.errors == ["Línea 8: el dividendo no tiene un ticker válido."]
    no_amount = parse_trades_text("fecha;operacion;importe\n2024-01-02;ingreso;\n")
    assert "falta el importe" in no_amount.errors[0]


def test_import_with_cash_rows_turns_off_automatic_dividends(
    service: PaperPortfolioService,
) -> None:
    (p,) = service.portfolios()
    assert p.apply_dividends
    parsed = parse_trades_text(BROKER)
    preview = service.prepare_import(p.id, parsed.trades, parsed.cash)
    assert len(preview.movements) == 5 and preview.disables_auto_dividends
    assert preview.cash_needed_alone == pytest.approx(0)  # the deposit pays for everything
    assert service.import_trades(p.id, preview) == 6
    assert not service.portfolios()[0].apply_dividends
    report = service.report(p.id)
    v = report.valuation
    assert v.contributions == pytest.approx(4900) and v.dividends == pytest.approx(12.5)
    assert v.interest == pytest.approx(3.1) and v.other_fees == pytest.approx(2)
    assert v.cash == pytest.approx(10_000 + 5000 - 1001 + 12.5 + 3.1 - 2 - 100)
