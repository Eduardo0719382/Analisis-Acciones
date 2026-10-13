# Plan — Análisis de Acciones

Working name: **Análisis de Acciones** (repository name; no other name given).

## Discovery answers (2026-10-13)

| Question | Answer |
|---|---|
| Q1 Stack | Python + PySide6, with TradingView Lightweight Charts embedded through QWebEngine |
| Q2 Data | `yfinance` (free, unofficial) plus CSV import; keyed and paid providers come later through the same interface |
| Q3 Users / stage | Personal prototype, single user |
| Q4 Markets | US stocks only |
| Q5 Freshness | End-of-day only for the MVP; intraday later |
| Q6 UI language | Spanish |
| Q7 MVP scope | Search, candlestick chart with volume, 6 indicators, a watchlist, information panel. Analysis, alerts and backtesting come after the MVP. |

---

## SITUATION

- The repository is empty. No code, dependencies or history yet.
- The target is a Windows desktop. It runs on a single user's machine, and nothing is distributed publicly.
- Development and automated tests run in a Linux container, so Qt must be tested headlessly (`QT_QPA_PLATFORM=offscreen`).

## PROBLEM

The goal is a technical-analysis tool that feels professional and runs on real market data without depending on any one source. Its calculations must be deterministic and verifiable, and must never fabricate prices. The architecture must survive several changes:

- the data provider changes, because Yahoo breaks or a paid API is added;
- the UI or the charting engine is replaced;
- intraday data, alerts and backtesting are added later without rewriting the core.

## DECISIONS

These are recorded in `DECISIONS.md` (D-001 to D-009).

| Topic | Choice |
|---|---|
| Language / runtime | Python 3.12 |
| Desktop framework | PySide6 (Qt 6) |
| Charting | TradingView Lightweight Charts v5, with its JS file stored in the repository and run inside `QWebEngineView`, connected to Python through `QWebChannel` |
| Data | `MarketDataProvider` interface. The first adapters are `YahooFinanceProvider` and `CsvProvider`. |
| Prices | Raw OHLCV and corporate actions are both stored. The chart shows split-adjusted prices by default. Dividend adjustment is off in the chart; backtests will offer it later. |
| Storage | SQLite (standard-library `sqlite3`, numbered migrations) for watchlists, recent searches, cached bars and settings |
| Secrets | `keyring` (Windows Credential Manager) with environment variables as a fallback. The MVP has no secrets because Yahoo needs no key. |
| Indicators | Pure functions plus a registry of metadata. No TA-Lib. |
| Backtesting (later) | Event-driven, one bar at a time. A signal at the close of bar *t* fills at the open of bar *t+1*. |
| Concurrency | Network and calculation work runs on `QThreadPool` workers. Results return to the UI through Qt signals. |
| Tooling | `pyproject.toml`, `pytest`, `pytest-qt`, `ruff`, `mypy` |
| UI language | Spanish. Text is kept in one place so it could be translated later, but there is no i18n framework now. |

## ARCHITECTURE

```
src/analisis_acciones/
  app/          entry point, dependency wiring, logging setup
  models/       dataclasses: Symbol, Quote, Bar series (DataFrame schema), CompanyInfo, Interval, errors
  providers/    MarketDataProvider (abstract base class), YahooFinanceProvider, CsvProvider
  data/         MarketDataService: cache-first loading, validation, resampling (1W/1M, later 4h)
  indicators/   pure functions + registry (sma, ema, rsi, macd, bollinger, atr; vwap later)
  analysis/     (phase 6) explainable rule engine
  alerts/       (phase 7) condition engine
  strategies/   (phase 8) strategy definitions
  backtesting/  (phase 8) engine, statistics
  storage/      SQLite connection, migrations, repositories (watchlists, settings, cache)
  services/     application services that coordinate the layers above; no Qt imports
  ui/           PySide6 widgets: main window, search, watchlist, details panel, indicator dialog
  charts/       ChartWidget (QWebEngineView) + bridge (QWebChannel) + web/ (HTML, JS, vendored library)
  utils/
tests/
  unit/ (indicators, providers with recorded fixtures, storage, services)
  ui/   (pytest-qt smoke tests)
```

### Dependency rules

These are enforced by a test that scans imports.

- `models`, `indicators`, `analysis`, `alerts`, `strategies`, `backtesting`, `data`, `storage`, `services` → **never import Qt**.
- `ui` and `charts` depend on `services`, never on `providers` directly.
- Any adapter can be replaced. The rest of the app only sees `MarketDataProvider`.

### Data flow (open a ticker)

1. The UI emits a request with symbol and interval.
2. `MarketDataService` runs in a worker thread:
   1. It checks the SQLite cache.
   2. If needed, it calls the provider.
   3. It validates the result: no NaN in OHLC, high ≥ low, timestamps that only move forward and contain no duplicates.
   4. It stores the result in the cache.
3. The service returns the `BarSeries`.
4. The UI thread hands the bars to the chart bridge, which sends JSON to the chart.
5. Indicators are calculated in a worker. Each indicator line is added or removed on its own, so the whole chart is never reloaded.

### Errors

The base class is `AppError`. Its subclasses are `UserError`, `NetworkError`, `DataError`, `ProviderError` and `InternalError`. The UI shows a short message in Spanish, and the log keeps the full traceback in rotating log files under `%LOCALAPPDATA%`.

## MVP (exactly)

**Included**

1. **Main window**
   - dark theme by default, with a light theme option;
   - resizable panels (splitters) whose layout is saved;
   - status bar showing the provider, the last update time and whether data came from the cache.
2. **Search**
   - by ticker or company name (Yahoo search), with a 300 ms debounce;
   - list of recent searches.
3. **Chart**
   - candlestick and line modes, with a volume histogram;
   - zoom and pan, crosshair, and a legend with OHLCV values under the cursor;
   - timeframes 1D, 1W and 1M.
4. **Indicators**
   - SMA, EMA, Bollinger Bands (drawn over the price);
   - RSI, MACD, ATR (each in its own pane);
   - each can be added, removed and configured. Parameters are validated and saved.
5. **Watchlist**
   - one list that can be edited: add, remove, reorder;
   - shows last price and daily % change;
   - clicking an item opens it on the chart;
   - saved in SQLite, with a schema that already supports several lists.
6. **Details panel**
   - ticker, name, price, change and % change;
   - open, high, low, close and volume;
   - 52-week high and low.
7. **Data**
   - SQLite cache. It refreshes when the latest daily bar is older than the last completed session.
   - Offline mode shows cached data labelled as stale.
   - CSV import (columns: date, open, high, low, close, volume).
8. **Persistence**
   - theme, layout, last opened symbol and interval;
   - active indicators and their parameters.
9. **Disclaimer** on first run: "Herramienta de análisis; no constituye asesoramiento financiero." ("An analysis tool; not financial advice.")

**Explicitly excluded from the MVP**

- intraday intervals and VWAP (VWAP needs intraday data);
- drawing tools;
- analysis, alerts and backtesting;
- comparing assets;
- exporting;
- installer.

## PHASES

Phases 1–5 make up the MVP.

| Phase | What it delivers | Tests that gate the next phase |
|---|---|---|
| 1 Skeleton | Project structure, `pyproject`, logging, configuration, SQLite and migrations, empty main window with the three panels and status bar, theme | App starts offscreen; settings round-trip; migrations apply; test that core layers don't import Qt |
| 2 Market data | Models, provider interface, Yahoo + CSV adapters, data validation, cache, `MarketDataService` running in workers, search | Valid ticker, invalid ticker, no network, empty response, NaN or incomplete bars, cache hit and miss (using recorded responses, never live data in tests) |
| 3 Charts | Lightweight Charts embedded, bridge, candlesticks and line, volume, crosshair legend, timeframe change | Bridge sends the right data; smoke test of timeframe switching; resampling tests |
| 4 Indicators | 6 indicators, registry, add/remove/configure dialog, separate panes, parameters saved | Results match independently calculated reference values; NaN during warm-up; invalid parameters rejected; add and remove |
| 5 Watchlist + details | Watchlist, recent searches, details panel, 52-week range | Watchlist and settings survive a restart |
| — | **MVP review** | Full test run; review against the goal |
| 6 Analysis | Explainable rule engine (trend, overbought/oversold, crossovers, volume, volatility, breakouts) | Each rule is tested on prepared data |
| 7 Alerts | Condition engine, saved alerts, Windows notifications, checks while the app is open | Rule evaluation; ignores the still-forming bar |
| 8 Backtesting | Engine, EMA-crossover strategy, metrics, equity curve | No-trade case, several trades, a test showing there is no look-ahead, metrics checked by hand |
| 9 Polish | Performance, intraday intervals, drawing tools, comparison, export, PyInstaller/Inno Setup installer | Regression suite |

## RISKS

| Risk | Mitigation |
|---|---|
| Yahoo/`yfinance` breaks or rate-limits | Adapter is isolated; cache first; clear `ProviderError` message; CSV fallback; adding another adapter does not touch the core |
| QtWebEngine is hard to test headlessly | Test the bridge logic in pure Python; run Qt tests offscreen with `--no-sandbox`; check the real chart manually on Windows |
| Lightweight Charts has no built-in drawing tools | Deferred to phase 9; they will be built with its plugin API |
| Lightweight Charts licence requires attribution (Apache-2.0 NOTICE) | Keep its default `attributionLogo`; ship the licence file |
| Python ↔ JS data volume | Send bars once and append new bars only; about 5,000 daily bars is small |
| Indicator correctness | Check results against independently calculated reference values and published examples (e.g., Wilder's RSI) |
| Scope creep | Each phase is gated by its tests and needs your sign-off |
| Install size (QtWebEngine about +150 MB) | Accepted for a personal tool (Q3a) |

## SUCCESS CRITERIA (MVP)

- `AAPL` at 1D (about 10 years, roughly 2,500 bars) opens in under 3 s on a cold cache and under 0.5 s from cache. Pan and zoom stay smooth.
- Unknown ticker → clear Spanish message, no crash. No network → cached data shown and labelled stale, or a clear `NetworkError`.
- Each of the 6 indicators matches its reference values to within 1e-8 and can be added, configured and removed without reloading the whole chart.
- Watchlist, active indicators, theme, layout and last symbol survive a restart.
- The UI never freezes during network requests.
- `pytest`, `ruff` and `mypy` pass. Core layers contain no Qt imports.
- No price is ever fabricated. Every value on screen comes from the provider, the cache or the user's CSV.
