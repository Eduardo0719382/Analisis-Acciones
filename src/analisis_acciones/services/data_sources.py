"""The data sources the user can choose, and the router built from the settings.

Yahoo Finance is the default for everything. CoinGecko needs no key; Alpha Vantage,
Finnhub and Twelve Data need the user's own free key (see ``api_keys``).
"""

from __future__ import annotations

from dataclasses import dataclass

from analisis_acciones.providers.alphavantage import AlphaVantageProvider
from analisis_acciones.providers.base import MarketDataProvider
from analisis_acciones.providers.coingecko import CoinGeckoProvider
from analisis_acciones.providers.finnhub import FinnhubProvider
from analisis_acciones.providers.routing import SourceRouter
from analisis_acciones.providers.twelvedata import TwelveDataProvider
from analisis_acciones.services.api_keys import KeyStore
from analisis_acciones.services.settings_service import SettingsService


@dataclass(frozen=True)
class SourceInfo:
    key: str
    name: str
    stocks: bool
    crypto: bool
    needs_key: bool
    summary: str


SOURCES = (
    SourceInfo("yahoo", "Yahoo Finance", True, True, False,
               "Recomendada: velas completas, historia larga, intradía, fundamentales. Sin "
               "clave."),
    SourceInfo("twelvedata", "Twelve Data", True, True, True,
               "Velas diarias completas de acciones, ETF y cripto. Gratis con clave: unas 800 "
               "consultas al día."),
    SourceInfo("alphavantage", "Alpha Vantage", True, True, True,
               "Velas diarias de acciones (sin ajustar por splits) y cripto. Gratis con clave: "
               "solo unas 25 consultas al día."),
    SourceInfo("coingecko", "CoinGecko", False, True, False,
               "Solo cripto: un precio por día y 365 días (gráfico en línea). Sin clave."),
    SourceInfo("finnhub", "Finnhub", True, True, True,
               "Cotización actual; el historial (velas) suele ser de pago y entonces avisa. "
               "Gratis con clave: 60 consultas por minuto."),
)  # fmt: skip
SOURCE_BY_KEY = {s.key: s for s in SOURCES}


def build_router(yahoo: MarketDataProvider, settings: SettingsService,
                 keys: KeyStore) -> SourceRouter:  # fmt: skip
    sources: dict[str, MarketDataProvider] = {
        "coingecko": CoinGeckoProvider(),
        "alphavantage": AlphaVantageProvider(lambda: keys.get("alphavantage")),
        "finnhub": FinnhubProvider(lambda: keys.get("finnhub")),
        "twelvedata": TwelveDataProvider(lambda: keys.get("twelvedata")),
    }
    return SourceRouter(yahoo, sources, settings.stock_source, settings.crypto_source)
