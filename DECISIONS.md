# Decision log

Format: DECISION / CONTEXT / ALTERNATIVES / CHOICE / RATIONALE / CONSEQUENCES.

---

## D-001 — Desktop framework

- **Context:** A Windows-first desktop app for technical analysis, used by one person. The heavy work is numerical: indicators, rules and backtests.
- **Alternatives:**
  - Python + PySide6;
  - Tauri + TypeScript/Rust;
  - Electron + React.
- **Choice:** Python 3.12 + PySide6 (Qt 6).
- **Rationale:**
  - pandas and numpy are the strongest ecosystem for financial calculations and for checking results against reference values.
  - Qt gives a native look, resizable splitters, and support for Windows, macOS and Linux.
  - With Tauri or Electron, the core calculations would have to be written in TypeScript or Rust, which have a thinner finance ecosystem.
- **Consequences:**
  - The installer is larger and needs PyInstaller or Nuitka.
  - Qt tests must run headlessly.
  - The core packages must stay free of Qt imports so the UI can be replaced.

## D-002 — Charting engine

- **Context:** The chart is the main focus of the app and must feel professional. It needs candlesticks, volume, a crosshair, separate panes for indicators, and drawing tools later.
- **Alternatives:**
  - pyqtgraph with a custom candlestick renderer: native and fast, but the polish would all have to be built by hand;
  - matplotlib: too slow for interactive charts;
  - TradingView Lightweight Charts inside `QWebEngineView`.
- **Choice:** Lightweight Charts v5, stored in the repository (no CDN), running in `QWebEngineView` and connected to Python through `QWebChannel`. This was the user's choice (Q1b).
- **Rationale:** It is built for financial charts and already has candlesticks, a crosshair, panes, time scales, a plugin API and good performance.
- **Consequences:**
  - QtWebEngine adds about 150 MB.
  - There is a bridge between Python and JS, so the app has two languages.
  - The Apache-2.0 attribution must be kept: the default `attributionLogo` stays on and the licence file is shipped.
  - Drawing tools must be built as plugins.
  - All calculations stay in Python; the JS side only draws.

## D-003 — Market-data provider

- **Context:** Free data is required, the app is for personal use, and the MVP needs end-of-day data for US stocks only. The architecture must not depend on one provider.
- **Alternatives:**
  - Yahoo (`yfinance`);
  - Alpha Vantage, Twelve Data or Polygon on free tiers, which need a key and have strict limits;
  - paid plans.
- **Choice:** A `MarketDataProvider` interface. The first adapters are `YahooFinanceProvider` and `CsvProvider`.
- **Rationale:** Yahoo needs no key and offers search, quotes, history and company info. CSV import gives a fallback that doesn't depend on any provider.
- **Consequences:**
  - Yahoo is unofficial and may break or rate-limit.
  - Errors are reported as a `ProviderError` or `NetworkError`, and the app never invents data.
  - Tests use recorded fixtures, never live calls.
  - Supported intervals are reported per provider.

## D-004 — Price adjustment

- **Context:** Stock splits and dividends distort raw price history.
- **Alternatives:**
  - show raw prices only;
  - fully adjust for both splits and dividends;
  - adjust for splits only.
- **Choice:** Store raw OHLCV together with split and dividend events. The chart shows split-adjusted prices by default. Dividend adjustment will be an option in backtests.
- **Rationale:**
  - Split-adjusted prices match what traders expect to see on a chart.
  - Keeping the raw data means any adjustment can be computed again later.
- **Consequences:** The adjustment logic lives in `data/` and has its own tests.

## D-005 — Storage

- **Context:** Watchlists, settings, recent searches, cached bars, and later alerts and strategies.
- **Alternatives:**
  - JSON files;
  - SQLite;
  - an ORM such as SQLAlchemy.
- **Choice:** SQLite through the standard-library `sqlite3`, with numbered SQL migrations and one repository class per aggregate.
- **Rationale:**
  - It handles structured, transactional data.
  - It adds no dependency.
  - The schema is small enough not to need an ORM.
- **Consequences:**
  - SQL is written by hand.
  - Each migration must be tested.
  - Database files live in the user's data directory, never in the repository.

## D-006 — Credential storage

- **Context:** Future providers will need API keys.
- **Choice:** `keyring` (Windows Credential Manager), with environment variables as a fallback. `.env.example` lists variable names only.
- **Consequences:** Keys are never written to SQLite, settings or logs. The MVP needs no key.

## D-007 — Indicator architecture

- **Context:** Indicators must be testable without the UI, configurable, and added or removed one at a time.
- **Alternatives:**
  - TA-Lib, which needs a native build that is painful on Windows;
  - `pandas-ta`;
  - writing our own.
- **Choice:**
  - Each indicator is a pure function: `f(bars: DataFrame, **params) -> Series | DataFrame`.
  - A registry describes each one: parameters with types, defaults and limits; whether it draws over the price or in its own pane; and how many warm-up bars it needs.
- **Rationale:**
  - Results are deterministic and easy to check against reference values.
  - It adds no dependency.
  - The UI builds its configuration forms from the registry metadata.
- **Consequences:**
  - The formulas and their conventions are documented, e.g. RSI uses Wilder smoothing and EMA is seeded with the SMA.
  - Warm-up values are NaN and are never filled with zero.

## D-008 — Backtesting architecture (designed now, built in phase 8)

- **Context:** Backtests must not have look-ahead bias, and the layers must be clearly separated.
- **Choice:**
  - The engine processes bars one at a time.
  - A strategy only sees bars up to *t*.
  - Orders fill at the open of *t+1*, with configurable commission and slippage.
  - Statistics are computed afterwards from the trade list and the equity curve.
  - The packages are separate: data, strategies, backtesting, statistics and UI.
- **Consequences:** It is slower than a vectorised backtest, but it is correct and easy to reason about. A test will check for look-ahead.

## D-009 — UI language

- **Choice:** The interface is in Spanish (Q6a). User-facing strings are kept in one module. Code, logs and documentation are in English.
- **Consequences:** Adding another language later would only need a translation layer, not a rewrite.

## D-010 — Python version, packaging layout and CI

- **Context:** The development container has Python 3.13. The target machine is Windows, and
  the plan says 3.12.
- **Choice:** Support Python ≥ 3.12. Use a `src/` layout with `pyproject.toml` (hatchling).
  GitHub Actions runs ruff, mypy (strict) and pytest on **Windows and Ubuntu** with 3.12 and 3.13.
- **Rationale:**
  - Tests in a Linux container alone cannot prove the app works on Windows; a Windows CI runner
    closes most of that gap.
  - The `src/` layout stops tests from accidentally importing code that hasn't been installed.
- **Consequences:**
  - The Ubuntu job installs Qt system libraries (see PROBLEMS.md P-001).
  - Real rendering and window behaviour still need a manual check on Windows.

## D-011 — UI layout persistence

- **Context:** Window size, panel positions and splitter sizes must survive restarts.
- **Choice:** Store Qt's `saveGeometry()`, `saveState()` and `QSplitter.saveState()` as base64
  strings inside one JSON setting (`ui.layout`). Each part is restored independently and falls
  back to defaults when it is invalid.
- **Rationale:** Qt's own formats handle multi-monitor setups, maximised state and DPI changes
  better than hand-written lists of sizes (see PROBLEMS.md P-002).
- **Consequences:** The stored values are opaque and Qt-specific. That is acceptable because
  only the UI layer reads them.

## D-012 — In-app updates

- **Context:** The user asked for an update option inside the program. The app is installed from
  a `git clone` plus `pip install -e`. There is no installer yet.
- **Alternatives:**
  - instructions only (`git pull`);
  - download a ZIP of the branch and overwrite files;
  - fast-forward the git checkout from inside the app;
  - a real auto-updater on top of an installer (phase 9).
- **Choice:** Help → "Buscar actualizaciones…", backed by a Qt-free `UpdateService`:
  1. `git fetch` the branch's upstream and list the new commit subjects.
  2. `git merge --ff-only @{u}`.
  3. `pip install -e .` only when `pyproject.toml` changed.
  4. Offer to restart.

  The git and pip calls run in a worker thread so the window never freezes.
- **Rationale:**
  - It is the smallest safe mechanism for the current installation method.
  - A fast-forward never discards anything: it refuses when files have local changes, the local
    branch has diverged, there is no upstream, the checkout is detached, or Git is missing.
    Each case gets a clear Spanish message.
- **Consequences:**
  - ZIP installs are not supported; the dialog says to reinstall with `git clone`.
  - Updates follow whichever branch was cloned (currently `claude/bold-knuth-wbixh5`). If
    development moves to `main`, the user must switch branches once.
  - If a dependency upgrade fails while the app holds DLLs open (Windows), the user is told to
    close the app and run `pip install -e .` manually.
  - Commit messages are external data and are shown only as plain text.
  - To be revisited when the installer is built in phase 9.
