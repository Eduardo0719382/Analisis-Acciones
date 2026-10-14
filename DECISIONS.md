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

### D-012 addendum — startup check and double-click launcher

- **Startup check:** three seconds after the window opens, a background check runs. When an update
  exists, a clickable "Actualización disponible" notice appears in the status bar. Failures are
  logged but never interrupt the user; offline use and ZIP installs are normal situations. The
  check can be turned off in Help (setting `updates.check_on_startup`, on by default).
- **`Abrir.bat`:**
  - On the first run it creates `.venv` and runs `pip install -e .`; after that it starts the app
    with `pythonw.exe`, so no console window appears.
  - Because `pythonw` has no `sys.stderr`, logging adds the console handler only when a console
    exists.
  - `.gitattributes` keeps `.bat` files with CRLF line endings.

### D-004 update — what Yahoo actually provides (Phase 2)

- Yahoo's daily `Open/High/Low/Close` are **already split-adjusted**. `Adj Close` is also adjusted
  for dividends. Truly raw (unadjusted) prices are not available from this source, so the
  original "store raw" plan cannot be met with Yahoo.
- **New choice:** store exactly what the source returns (split-adjusted OHLC, `adj_close`, split
  and dividend events). Each series records its source.
- **Consequence:** a new split or dividend re-adjusts past values at the source. The cache detects
  it in two ways:
  - new rows contain a split or dividend;
  - the overlapping closes differ by more than 0.01%.

  In either case the cache refetches the full history instead of merging (see D-013).

## D-013 — Market-data cache and refresh policy

- **Context:** Avoid repeated downloads, work offline, and never show silently outdated or mixed
  data.
- **Choice:**
  - SQLite tables: `daily_bars` (one row per symbol and session), `series_meta` (source, fetch
    time, date range) and `recent_symbols`.
  - Only daily bars are stored. Weekly and monthly bars are derived on load, labelled with the
    first trading day of the period.
  - **Freshness:** cached data counts as current when it was fetched after the latest weekday
    16:30 New York close. Holidays are not modelled: at worst there is one extra request per day.
  - **Refresh:** download the last 30 days and compare the overlap. If it matches, merge;
    otherwise (split or dividend) download the full history again.
  - **Network or provider failure with a cache:** serve the cache marked *stale*, with the reason.
    Without a cache, report the error.
  - **Daily bar during market hours:** flagged as `session_in_progress`. It is overwritten on the
    next refresh after the close.
  - CSV imports are stored under a `CSV:` prefix and never refreshed from the network.
  - The service owns its own SQLite connection, guarded by a lock, because it is used from worker
    threads.
- **Alternatives rejected:**
  - always downloading the full history: slow, and more likely to hit rate limits;
  - append-only merging: would mix differently adjusted prices after a split.

## D-014 — Chart integration and centre layout (Phase 3)

- **Context:** The Phase 1 layout put a separate "Indicadores / Volumen" panel under the chart.
  Lightweight Charts v5 supports several panes inside one chart that share the time axis and the
  crosshair.
- **Choice:**
  - The centre region is a single `ChartWidget`. Volume (and, in Phase 4, the RSI, MACD and ATR
    indicators) are panes inside the chart. The separate lower panel and its splitter were removed.
    Old saved layouts fall back to the defaults for the parts that no longer exist.
  - The chart page is bundled locally (`charts/web/`, Lightweight Charts 5.2.1 checked against
    npm's sha512 hash) and loaded from `file://`.
  - The page's Content Security Policy blocks every network request. Scripts may come only from the
    bundled files; inline styles are allowed because the library needs them.
  - Navigation away from the page is blocked and JavaScript console errors go to the log.
  - Data flows one way, Python → JS, as strict JSON (`allow_nan=False`) through `runJavaScript`.
    The page draws and formats only; it calculates nothing. The legend's OHLC values, change and
    volume under the cursor are rendered in the page from the data it was sent.
  - Number and date formatting use the system locale. If the locale is unusable (`C` or `POSIX`),
    the chart falls back to `es-ES` (see PROBLEMS.md P-008).
  - The TradingView attribution logo stays enabled, as the licence's NOTICE requires.
- **Rationale:**
  - Synchronised panes are a core expectation of technical-analysis software.
  - Keeping the JS side free of logic keeps all calculations testable in Python.
- **Consequences:**
  - Tests query the real page through `chartApp.state()`.
  - Headless Chromium needs `--no-sandbox --disable-gpu` in containers (set in `tests/conftest.py`
    only).
  - The Linux CI needs the NSS and X libraries.

## D-015 — Indicator conventions, UI and threading (Phase 4)

- **Conventions** (published implementations differ, so they are fixed and documented in
  `indicators/functions.py`):
  - EMA is seeded with the SMA of its first N values;
  - RSI and ATR use Wilder smoothing, seeded with a simple average;
  - Bollinger Bands use the population standard deviation;
  - the MACD signal line is an EMA of the MACD line, seeded the same way as the EMA.

  Warm-up values are NaN and are drawn as gaps.
- **Verification:** every indicator is compared against independent plain-Python reference
  implementations to within 1e-8, plus hand-computed examples and a no-look-ahead test (values at
  bar t do not change when later bars are added).
- **Registry-driven UI:** the indicator dialog builds its parameter forms from `ParamSpec`, and
  validation lives in the core (`validate_params`), not the UI. The configuration
  (id, parameters, visibility) is saved in settings; invalid stored entries are skipped.
- **Threading:** computing all six indicators and serialising about 12k bars took about 190 ms on
  the UI thread. Building the chart payload now runs in a worker thread, and only the latest
  request is applied. Changing indicators keeps the visible range.

## D-016 — Watchlists (Phase 5)

- **Storage:** SQLite tables `watchlists` (unique, case-insensitive names) and `watchlist_items`
  (ordered by position; `ON DELETE CASCADE`). A "Favoritos" list is created when none exist, and
  the last remaining list cannot be deleted.
- **Values:** each row shows the last daily close and its change from the previous close, taken
  from `MarketDataService.snapshot()` (cache-first, only stale symbols are refreshed). A failing
  symbol shows "—" with the reason in its tooltip and never hides the other rows. Snapshots run in
  a worker thread, and stale replies are dropped.
- **Reordering:** up/down buttons rather than drag-and-drop. They are simpler, accessible from the
  keyboard and easy to test. Drag-and-drop can be added later.

## D-017 — Shutdown and worker lifetime

Three crashes or teardown errors (PROBLEMS.md P-011 to P-013) shaped these rules:

- `MarketDataService.close()` closes its connection under the same lock that guards every query,
  so a worker thread can never use a connection while it is being closed.
- Worker results are delivered only if the receiving Qt object still exists (`shiboken6.isValid`).
- On exit, deferred deletions are flushed explicitly, so the chart's `QWebEnginePage` is destroyed
  before the `QApplication`.

## D-018 — Explainable analysis engine (Phase 6)

- **Design:**
  - `analysis/` contains rules: pure functions over bars that return `Signal` objects (category,
    direction, title, evidence lines with the actual values, and the date of the bar evaluated).
  - The engine skips rules that lack enough history and says why; it never guesses.
  - It drops an in-progress session bar so signals cannot change while the session is open.
  - Number formatting is injected, so the core stays free of Qt and of locale assumptions.
- **Thresholds** are fixed and visible in the evidence text: trend EMA 20/50 with a minimum
  separation of 0.5 %, RSI 70/30, crossovers within the last 5 bars, volume above 2× its 20-bar
  mean, ATR change of ±30 % over 20 bars, and 20-bar breakouts.
- **Problem found by the tests:** without a minimum EMA separation, a flat market with averages of
  99.98 and 99.99 was labelled a bearish trend. The 0.5 % gap was added (PROBLEMS.md P-014).
- **Wording:** a test checks that signal texts contain no advice or prediction words
  ("compra", "vende", "subirá", "garantía", …). The panel shows a standing disclaimer.

## D-019 — Alert engine (Phase 7)

- **Separation:** `alerts/rules.py` defines the alert kinds, parameter validation and evaluation.
  `alerts/service.py` handles persistence (migration 0004: `alerts` and `alert_events`) and
  `check_all()`. The UI only displays results and schedules checks. Alerts use their own SQLite
  connection, guarded by a lock and closed safely (as in D-017).
- **Semantics:**
  - Only completed daily bars are evaluated; an in-progress session bar is dropped, so nothing
    fires on a value that can still change.
  - *Level* conditions (price, daily change, RSI) use hysteresis: they fire when the condition
    becomes true and re-arm once it is false again. Re-enabling a paused alert re-arms it.
  - *Event* conditions (EMA or MACD crossovers, N-bar breakouts) fire on the bar where the event
    happens, at most once per bar.
- **Scheduling:** checks run 20 seconds after start-up, then every 15 minutes, or on demand. They
  run only while the app is open; background or tray-only operation is deferred.
- **Notifications:** status bar message, taskbar flash (`QApplication.alert`), a Windows toast via
  `QSystemTrayIcon` when available, and a persistent event history.
- **Problems:** missing data, offline use and unknown symbols are collected per symbol or alert
  and shown as a tooltip; they never stop the other alerts from being checked.

## D-020 — Backtesting (Phase 8)

- **Separation (as in D-008):**
  - data: the `BarSeries` on the chart, at the current interval;
  - strategies (`strategies/registry.py`): signals only, entry/exit booleans computed from data
    up to each bar;
  - engine (`backtesting/engine.py`): execution, costs and the equity curve;
  - statistics (`backtesting/statistics.py`): derived only from the engine result;
  - visualisation (`ui/backtest_dialog.py`, `ui/equity_chart.py`).
- **Execution model:**
  - a signal at the close of bar t is filled at the open of bar t+1;
  - a signal on the final bar is reported as pending, never filled at a made-up price;
  - long-only, all available cash, whole shares;
  - percentage and fixed commission per order, and slippage against the trader;
  - an open position at the end is marked to the last close and kept out of the closed-trade
    statistics (and said so).
- **Statistics:**
  - the profit factor is undefined (shown as "—" with a note) when there are no losing trades;
  - maximum drawdown is computed peak to trough on the equity curve;
  - buy-and-hold (first open to last close, no costs) is shown for comparison.
- **Verification:**
  - fills, commissions, P&L and equity are checked by hand on small series;
  - a no-look-ahead test changes every bar after t and asserts that trades and equity before t
    are identical;
  - the UI test checks that the dialog shows exactly the engine's numbers.
- **Equity chart:** a small native `QPainter` widget rather than a second web engine page, which
  is cheaper and enough for one or two lines.

## D-021 — Export (Phase 9)

- **CSV generation:** pure functions in `data/export.py` with no file I/O and no Qt, so they are
  unit-tested.
  - Values are numbers rounded to 6 decimals; missing values are empty, never 0.
  - Text cells starting with `= + - @` (or tab/CR) are prefixed with `'` to prevent CSV or formula
    injection in spreadsheets.
- **Image:** a PNG grab of the chart view.
- **PDF:** HTML rendered with `QTextDocument` and `QPdfWriter` (A4). Every piece of external text
  is HTML-escaped. It contains the chart image, details, analysis evidence and the disclaimer.
- **Backtest export:** three CSV files (trades, summary with run context, equity curve).

## D-022 — Drawing tools (Phase 9)

- **Scope:** horizontal lines, trend lines, Fibonacci retracements and notes. Channels and
  rectangles are deferred: Lightweight Charts has no built-in drawing primitives, and these
  four cover the support/resistance use case with library features (price lines, a 2-point line
  series, series markers).
- **Data flow:**
  - A click in the page is converted to (date, price) and sent through `QWebChannel` as a JSON
    string.
  - Python treats it as untrusted: there is a size limit, then `DrawingService` validates the kind,
    the number of points, ISO dates, finite positive prices and the text length before storing it
    (migration 0005).
  - The page only redraws from the validated list Python sends back.
  - Fibonacci levels are computed in Python and unit-tested.
- **Display:** points snap to the bars on screen, so drawings also appear on weekly and monthly
  charts.
- **Known limitation:** drawings are stored in the series' price units. After a split, Yahoo
  re-adjusts history (D-004), so old drawings can be offset. This is documented in the README.

## D-023 — Asset comparison (Phase 9)

- `services/comparison.py` (no Qt) intersects the session dates of all assets, cuts the requested
  period and normalises closes to 0 % at the first common session.
- Metrics: total return, annualised volatility (sample std of daily log returns × √252), maximum
  drawdown of the close, average volume over the period, and RSI 14 at the last common date.
  Formulas are documented in the module and checked by hand in the tests.
- Symbols that cannot be loaded are listed and the rest are still compared.
- The dialog reuses the native `EquityChart`, with a percentage axis formatter.

## D-024 — Windows installer (Phase 9)

- **Build:** PyInstaller in one-folder mode with a windowed exe (`packaging/analisis_acciones.spec`).
  - The bundle includes the chart web assets and the SQL migrations.
  - Qt modules the app never loads (3D, Quick3D, Charts, Multimedia, Pdf, QML, extra
    translations, …) are filtered out. The libraries QtWebEngine depends on were confirmed with
    `ldd` and are kept.
  - One-folder rather than one-file because QtWebEngine needs its helper process and resources
    on disk, and start-up is faster.
- **Installer:** Inno Setup (`packaging/installer.iss`), installed per user under
  `%LOCALAPPDATA%\Programs` with no administrator rights. It creates Start-menu entries and an
  optional desktop icon, uses a Spanish wizard and shows the disclaimer as the licence page.
  User data in `%LOCALAPPDATA%\AnalisisAcciones` is kept when upgrading or uninstalling.
- **CI (`.github/workflows/installer.yml`, Windows runner):**
  1. Build the app.
  2. Run `AnalisisAcciones.exe --smoke-test`: the packaged app starts, waits for the chart page
     to load and exits 0, or 3 if it never loads.
  3. Build the installer.
  4. Upload it as an artifact, and attach it to a GitHub Release on `v*` tags.
- **Updates:** the git-based updater (D-012) does not apply to installed builds. In a frozen build
  it explains that the new installer should be installed on top and links to Releases.
- **Not done:** code signing (SmartScreen will warn; documented in the README) and a release-based
  auto-updater.

## D-025 — Additional indicators (Phase 10)

- **Added:** Ichimoku, slow Stochastic, Stochastic RSI, ADX/DMI (Wilder), OBV and Supertrend.
  Each is verified against an independent plain-Python reference.
- **Display shifts** are metadata on the output (`OutputSpec.shift_param`). The functions compute
  every value at its own bar; the chart payload draws Senkou A/B `displacement` bars ahead (on
  generated future dates: business days for daily data, weekly or monthly steps otherwise;
  holidays not modelled) and Chikou `displacement` bars behind. This keeps the calculations free
  of any look-ahead.
- **Conventions:**
  - stochastics return 50 when the high-low range is flat;
  - OBV becomes unknown (NaN) from the first missing volume onwards, never 0-filled;
  - Supertrend is one line coloured per point by direction. Splitting it into two series with
    gaps drew false diagonal connections (PROBLEMS.md P-017).

## D-026 — Price projection as calibrated statistical ranges

- **Request:** "something to predict the price". The application must not present predictions
  as certainties, so it shows **ranges with explicit assumptions**, never a single target price.
- **Methods** (`forecast/projection.py`, Qt-free, deterministic):
  - *Volatility cone:* log returns over the window give σ; bands at the normal quantiles
    (5/25/50/75/95 %) of `close · exp(z·σ·√h)`. Zero drift by default: extrapolating the
    historical mean return would imply a trend nobody can know.
  - *Regression channel:* least-squares line on log prices over the window, bands at ±1 and ±2
    residual standard deviations, drawn over the fitted window and extended forward. It only
    extends the recent trend; the panel says so and shows R².
- **Calibration is always shown.** Walk-forward: every 5 bars (at most 400 origins), the same
  method is applied using only data up to that bar and the outcome `h` bars later is compared
  with the bands. The panel reports how often the price ended inside the 90 % and 50 % ranges
  and the median error of the median line. A regression channel is often badly calibrated
  (ignoring parameter uncertainty and trend changes); showing that number is the point.
- **Not done:** models with fitted parameters that would invite over-trust (ARIMA, ML).

## D-027 — Elliott wave detection

- **Pivots:** ZigZag on highs/lows (`patterns/zigzag.py`). A swing is confirmed once price moves
  the threshold away from it; the extreme of the leg in progress is kept as a provisional last
  pivot. Default threshold: 3 × the median ATR(14)/close of the last 100 bars, clamped to
  2–30 %. The threshold sets the wave degree; the user can change it.
- **Counts only when the hard rules hold** (`patterns/elliott.py`): wave 2 does not retrace past
  the start of wave 1; wave 3 ends beyond wave 1; wave 4 does not overlap wave 1; wave 3 is not
  the shortest. A-B-C corrections are searched only right after a detected impulse (the 5-3
  structure). Without that restriction, any lower high/lower low sequence would qualify.
  Corrections must be zigzags: B stays inside A's start, and C goes beyond A's end.
- **Guidelines only score.** These are wave-2/4 retracements, the wave-3 and wave-5 ratios,
  alternation, no truncation and wave 3 being the longest. Every check is shown with its
  measured value.
- **Past impulses** come from all 6-pivot windows that pass the rules. Higher scores are picked
  first and impulses do not overlap.
- **Counts in progress** fit the last 3–6 pivots, ending at the provisional pivot. They include
  Fibonacci reference levels and the invalidation price. For these counts, the guidelines of
  the last (unfinished) wave are not judged.
- **Display:** only the selected count in progress is drawn, because alternative counts share
  pivots and their labels would stack. Past counts are always drawn.
- **Not done:** nested degrees (sub-waves), triangles, diagonals and complex corrections
  (W-X-Y). Labelling them automatically would be far more subjective.

## D-028 — Support/resistance and chart patterns

- **Pivots:** the ZigZag from D-027 with a finer default threshold (2 × the median ATR%,
  minimum 2 %). Tolerances scale with volatility: `tolerance` = median ATR/close, clamped to
  0.5–5 %.
- **Support/resistance:** swing highs and lows from about the last 500 bars are grouped into
  zones no wider than 2 × tolerance. A zone needs at least 2 touches. Highs and lows share
  zones because levels change role once they are broken. The 4 nearest zones on each side of
  the price are shown.
- **Patterns** (`patterns/chart_patterns.py`): double top/bottom, head and shoulders (and
  inverse), ascending/descending/symmetric triangles, and bull/bear flags. Every condition is a
  requirement and is listed with its measured value. A pattern is confirmed only by a close
  beyond its breakout line, within a bounded number of bars. An unconfirmed pattern is shown
  only while it is the latest structure and has not been invalidated. Overlap is resolved
  only within the same pattern type.
- **Track record instead of promises.** After a breakout, each pattern is followed until it
  reaches its classic measured target or its invalidation level. If both happen on the same
  daily bar, it counts as invalidated (the conservative choice). The panel reports the counts
  for the asset. On random-walk test data most patterns fail, as they should.
- **Display:** levels are price lines; patterns in formation are always drawn. A past pattern
  is drawn with its target and invalidation when it is selected.

## D-029 — Alerts from Elliott counts, chart patterns and levels

- No new alert engine: the levels of a selection become ordinary close-above/below alerts.
  The direction is chosen from the last close: a level above it becomes "Cierre >", and a
  level below it becomes "Cierre <". This reuses the existing hysteresis and the completed-bar
  rules.
- Migration 0006 adds a `note` column: one line of at most 120 characters, written by the
  application and shown in the description, so the user knows which count or pattern created
  the alert.
- Alerts are not created for finished patterns (target reached or invalidated), because
  nothing is left to watch.
