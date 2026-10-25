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

## D-030 — Watchlist scanner

- `services/scanner.py` (Qt-free) runs the chart's own deterministic tools on each symbol:
  analysis rules, chart patterns, Elliott counts in progress, S/R distances and RSI. It uses
  completed daily bars only (the same rule as alerts) and loads cache-first. Each symbol fails
  on its own, with a message, without stopping the scan. There are at most 50 symbols per run.
- **No ranking score.** The table shows the counts of bullish and bearish signals and what
  they are. Combining them into one "buy score" would present a judgement the rules do not
  support. The user can sort and filter instead.
- A pattern counts toward the bullish/bearish columns only if its breakout happened in the
  last 10 bars. Patterns still in formation are listed, but are not counted as signals.

## D-031 — Visual scanner report

- **Format:** one self-contained HTML page (inline CSS and SVG, no scripts and no external
  resources), so it opens in any browser and cannot run code. The PDF is the same HTML printed
  by Chromium (`QWebEnginePage.printToPdf`, with JavaScript disabled), so on paper it looks as
  on screen. QTextDocument, used for the chart report, cannot lay out these graphics.
- **For non-specialists:** every card opens with a sentence describing the balance of signals,
  not a recommendation. There are four visual parts: a mini price chart with the nearest
  support and resistance, a two-sided signal bar, an RSI gauge with named zones, and the
  price's position between support and resistance. The report also has a "how to read" box,
  a glossary, a summary table (the table view of the same data) and the disclaimer.
- **Colour:** bullish is blue ▲ and bearish is red ▼ (the documented diverging pair; it passes
  the colour-blindness separation checks, which green and red fail). An icon and a word
  always go with the colour. Text uses text colours only.
- **Print:** cards are stacked in a single column (Chromium splits grid rows badly across
  pages), two per A4 page, and the summary table starts on a new page.
- Every text that comes from data is HTML-escaped, and CSV cells are formula-safe.

## D-032 — Daily automatic scan

- It runs inside the app, with no OS scheduler or background service. A check every 30
  minutes, plus one 20 s after start-up, runs the scan when a US session has closed (with the
  30-minute settle time) after the last stored scan. If no symbol could be analysed
  (offline), the session is not marked as done, so the scan is retried later.
- **Only new items are reported.** The stored snapshot keeps, per symbol, the signals and
  patterns found (a pattern's state is part of the item, so "forming" → "breakout" is new).
  A symbol seen for the first time only sets a baseline. Symbols that fail keep their previous
  items, so a temporary error does not cause false "new" items later.
- Novelties are written to the alert history (`alert_events` with no rule) and use the same
  notification path as alerts, so the user has one place to look.

## D-033 — Backtesting chart patterns across assets

- **No look-ahead, by re-detection.** Pivots and volatility thresholds depend on later data,
  so a pattern found on the full history may not have been visible at the time. Candidates come
  from the full history and from growing prefixes (every 40 bars). Each one is accepted only if
  detection on `bars[:breakout + 1]` finds the same pattern (same name and pivots) breaking out
  on that same bar. Rejected candidates are counted and reported. On random-walk test data the
  resulting edge is about 0, as it should be.
- **Trades:** a signal at the close is filled at the next open. The exit is the measured target
  (limit), the invalidation level (stop) or the close after N sessions. If both are touched on
  the same bar, the stop counts first; an open that gaps beyond a level fills at the open. Costs
  are commission per side plus slippage against each fill. Returns are per trade, as a
  percentage of the entry value (no compounding and no position sizing), so patterns and
  assets compare directly. Bearish patterns are short trades unless "solo compras" is chosen;
  short borrowing costs are not modelled (stated in the report).
- **"Edge versus chance":** the average trade return minus the average return of entering the
  same asset on any day, in the same direction and for the same number of sessions. Groups with
  fewer than 20 trades are flagged as small samples.
- The report reuses the scanner report's visual language and export path (HTML/PDF/CSV).

## D-034 — Intraday data (1 hour, 15 minutes)

- **Source:** Yahoo through yfinance (`interval="1h"/"15m"`, `prepost=False`). Yahoo serves
  about 730 days of hourly bars and 60 days of 15-minute bars, so requests are clamped to those
  windows.
- **Time:** bars keep the exchange's wall-clock time (New York for US stocks), stored without a
  time zone. The chart receives these times encoded as UTC seconds, so it shows 9:30, 10:30
  and so on, whatever the user's PC time zone. Daily and longer bars still use "YYYY-MM-DD".
  `chart_times()` picks the form from the data (intraday bars have a time of day), so overlays
  and indicators share one code path.
- **Cache:** new tables `intraday_bars` and `intraday_meta` (migration 0007). A cached series
  is current for 10 min (1 h) or 3 min (15 m). After that, the last 3 days are requested again
  and merged. Stored bars are kept beyond Yahoo's window, so history grows with use. If
  overlapping closes differ (a split re-adjustment), the stored series is replaced. When
  offline, the cache is served and marked stale.
- **Bar in progress:** a bar is incomplete until its start plus the interval, or until the
  16:00 close if that comes first (the last hourly bar starts at 15:30).
- **Scope:** CSV imports, alerts, the daily scan and the watchlist stay on daily sessions.
  Drawings are keyed by session date, so they are disabled on intraday charts.
  Future times (Ichimoku cloud, projection) step through weekday sessions; holidays are not
  modelled.

## D-035 — VWAP, automatic Fibonacci and volume profile

- **VWAP** uses the typical price (H+L+C)/3. On intraday bars it accumulates from each
  session's first bar, which is the standard definition. On daily and longer bars a session
  VWAP makes no sense, so it is rolling over N bars. Missing volume makes the value unknown;
  it is never treated as zero.
- **Automatic Fibonacci** gives the retracements of the last ZigZag swing, from the
  second-to-last pivot (100 %) to the last one (0 %, which may still extend). It is computed
  from the whole series, so it is a display aid and is not used by any rule or backtest.
- **Volume profile:** each bar's volume is spread uniformly over its high-low range (more
  faithful than assigning it all to the close) across 24 price bands of the last 250 bars. The
  value area grows from the point of control (POC) towards the larger neighbouring band until
  it holds 70 % of the volume. It is drawn by a series primitive at the right of the price
  pane, with POC/VAH/VAL as price lines, and switched on from the View menu.

## D-036 — Intraday alerts

- An alert has an interval: `1D` (default), `1h` or `15m` (migration 0008). The same rule
  set applies, evaluated on **completed** bars of that interval. The bar still forming is
  dropped, using the same in-progress test as the chart.
- Event alerts (crossovers, breakouts) fire at most once per bar. The stored "last bar" key is
  an ISO date for daily bars and an ISO date-time for intraday bars, so two crossovers on the
  same day are both reported. Existing daily rows keep their date keys unchanged.
- Checks run every 15 minutes, or every 2 minutes while any intraday alert is enabled. The
  intraday cache (D-034) keeps most checks off the network.

## D-037 — Candlestick chart in the scanner report

- Each card shows the last 90 sessions as candles, with volume, SMA 20, SMA 50 and the nearest
  support and resistance, drawn as inline SVG (no scripts), so it prints the same in the PDF.
- **Colours:** candles reuse the report's blue/red, and SMA 20 is green. This set passes the
  palette validator on the light surface (red/green CVD separation is in the warning band, so
  every line also has a direct label and a legend). SMA 50 is the neutral ink colour. Labels are
  moved apart so they never overlap. Every candle has a native tooltip with open, close, high
  and low.

## D-038 — Day summary

- One self-contained HTML page shown in a QWebEngineView with JavaScript disabled. It
  reuses the reports' visual language: tiles for list size, rising, falling and recent
  notices; one card per watchlist symbol with the change bar and a mini chart; and the
  notices of the last 3 days.
- Tickers are links to `http://abrir.local/<TICKER>`. The page intercepts them in
  `acceptNavigationRequest` (they never reach the network), opens the symbol on the chart and
  blocks every other navigation.
- It opens at start-up only when the watchlist has symbols; this can be turned off from the
  window. Data is loaded cache-first in a worker. The market-open badge uses regular US hours
  on weekdays (holidays are not modelled).

## D-039 — Benchmark in the chart

- The benchmark (SPY by default) is drawn as one line in the price pane, rebased to the
  asset's close at the first common bar of the last 250 bars. Same scale, no second axis
  (dual axes mislead); the line shows relative performance from that date. The status bar
  states both returns and the difference in percentage points.
- It is loaded cache-first in a worker with the chart's interval, and stale replies are
  dropped. Days missing from either series are gaps, never filled.

## D-040 — Paper portfolio

- **Storage:** migration 0009 adds `paper_portfolios` and `paper_trades`. A default "Mi
  cartera" with 10 000 of fictitious cash is created on first use.
- **Accounting** (`portfolio/engine.py`, Qt-free): trades are replayed in date order using
  average cost. Commissions add to the cost basis of purchases and reduce the proceeds of
  sales. Long positions only, and no borrowing. Every new or deleted trade is validated by
  replaying the whole history, so a back-dated trade can never make a later one impossible.
- **Prices:** a missing price uses the close of that session (or the previous one). The
  valuation uses the last close on or before today, which is the same day the value curve
  ends.
- **Value curve:** one point per business day from the first trade. A day is left out when a
  held symbol has no close yet, never estimated. The benchmark is invested with the same
  initial capital on the first day.
- Amounts are added without currency conversion; the report says so. Taxes are not
  modelled (dividends, splits and commissions: see D-042).

## D-041 — Fundamentals

- **Source:** the Yahoo quote payload (ratios) and yfinance's annual income statement
  (`get_income_stmt(pretty=False)`: TotalRevenue, NetIncome, OperatingIncome, DilutedEPS).
  Each cell is checked as external data, and a missing value stays `None` and is shown as
  "—".
- **Units:** Yahoo's dividend-yield field has changed units between versions, so the yield is
  computed as dividend rate / price. Fraction fields (margins, ROE, growth, payout) beyond
  ±5000 % are dropped as unit errors rather than shown wrong.
- **Dividends per year** come from the dividends column of the cached daily bars (real
  payments), not from the provider's ratios.
- **Cache:** migration 0010 adds `fundamentals_cache`, refreshed once a day. If the source
  fails, the stored copy is served and marked with its date. An income-statement network
  failure raises (so the stored copy is kept) instead of overwriting it with empty years.
- The data is fetched only when the "Fundamentales" tab is shown, to keep symbol switching
  fast. A live CI test checks AAPL's values for plausible ranges.

## D-042 — Paper portfolio: fractions, dollar amounts, commissions, corporate events, journal

- **Fractions / dollars:** a trade gives either a quantity (decimals allowed) or an amount in
  dollars, converted at the trade price and rounded to 6 decimals. A sale left with a rounding
  remainder below 1e-6 closes the position.
- **Commissions:** per portfolio (migration 0011): fixed $ + % of value, with a minimum,
  rounded to cents. Applied when the trade is recorded; a manual commission overrides it.
  Changing the schedule never rewrites existing trades.
- **Corporate events:** Yahoo daily prices are split-adjusted but not dividend-adjusted
  (`auto_adjust=False`). Trades keep the price and quantity the user entered (real units of
  that day); for replay and valuation they are converted to today's units
  (`adjust_for_splits`). Dividends (per current share) are credited in cash on the ex-date to
  the shares held *before* that day (events go before same-day trades). Only events after a
  symbol's first trade are used. Dividends can be switched off per portfolio; splits cannot
  (they are needed for consistent quantities). "Cierre del día" returns the real quoted close
  (adjusted close × later splits). The report shows events in the units of their day; error
  messages show quantities in the units of the trade's day.
- **Journal:** the existing note is the reason for the trade; a `review` column stores what
  was learnt, editable afterwards, shown in the report and CSV.

## D-043 — Fundamental filter in the scanner

(Extended by D-048.)

- Optional ("Incluir fundamentales"), because it adds one provider request per symbol (cached
  for a day by D-041). Rows keep `fundamentals_checked` so the dialog can tell "no data" from
  "not requested".
- A missing value never passes an active limit, and a P/E ≤ 0 (losses) fails a P/E maximum:
  the filter must not include a company because data is missing. Limits only apply to scans
  that included fundamentals; otherwise the dialog explains that a re-scan is needed.
- The daily automatic scan does not fetch fundamentals (it only reports technical changes).

## D-044 — Earnings and dividend calendar

- **Source:** Yahoo quote payload: `earningsTimestampStart/End` (window) or
  `earningsTimestamp`, `isEarningsDateEstimate`, `exDividendDate`, `dividendDate`. Values
  outside 1990–2100 or non-numeric are dropped.
- **Time zones:** earnings timestamps carry the real release time and are read as New York
  dates (a release at 01:00 UTC is the previous US evening). Dividend dates come as midnight
  UTC and are read in UTC; reading them in New York time would move them a day early.
- Dates are stored with the fundamentals (ISO strings in the JSON cache; old cache entries
  without them still load).
- The day summary uses only stored fundamentals (`cached_fundamentals`), so opening it never
  triggers one request per watchlist symbol. Dates are shown as published, with "estimada"
  and "pasada" labels; no date is inferred.

## D-045 — In-app guide

- Static Spanish HTML generated by `services/user_guide.py`, shown in a web view with
  JavaScript off (same as the reports); section links are plain `#anchors`. No external
  resources. A test checks every link has a target and that the menu names it cites exist.
- It mirrors the README "Uso" section in shorter, task-oriented form; keep both in step.

## D-046 — Portfolio taxes, closed trades and per-position values

- **Dividend withholding** (migration 0012) is deducted when each dividend is credited, so it
  affects cash and therefore which later trades are possible; changing it re-validates the
  whole history.
- **Capital gains tax** is only an estimate: rate × each calendar year's net realised result
  (losses offset gains within the year; no carry-forward, no country rules). It is shown, not
  deducted, because real rules vary too much to simulate cash flows honestly.
- **Closed trades:** each sale against the average cost of the shares sold (purchase
  commissions included) minus its own commission; shown in the units of the trade's day.
- **Per-position values** come from the same daily replay as the equity curve
  (`daily_values`), so the per-symbol values plus cash add up to the curve.

## D-047 — Earnings / ex-dividend notices

- Run with the daily automatic scan (once per completed session) so there is a single
  background job and one place to switch notices off. The job refreshes each watchlist
  symbol's fundamentals, which are cached for a day (D-041), so this is at most one extra
  request per symbol per day.
- Earnings and ex-dividend dates within N days (default 3, 0 = off, max 30) are announced
  once. The remembered key includes the date, so a moved date is announced again; keys for
  past dates are pruned. Payment dates are not announced (nothing to decide on them).
- Notices go to the alert history as "<ticker> · calendario", with a neutral marker: they
  describe a published date, not a signal.

## D-048 — More fundamental limits in the scanner

- Added minimum market cap (thousands of millions, in the listing currency, no conversion),
  minimum revenue growth and minimum net margin. All limits live in one
  `FundamentalLimits` value used by the table, the export note and the tests.
- Growth and margin limits may be negative ("shrinking less than 5 %"), so "no limit" is the
  spin box minimum (shown as "sin límite"), not 0.
- Same rule as D-043: missing data never passes an active limit.

## D-049 — Crash resilience

- Native crashes cannot be caught in Python, so the strategy is: avoid known triggers,
  recover what can be recovered, and leave evidence (see P-018).
- Software rendering is not the default: GPU compositing is smoother on most PCs. It switches on
  automatically only after two consecutive unexpected exits, and can be toggled in *Ver*. It is
  stored as a flag file in the data directory because it must be known before the
  `QApplication` (and Chromium) start, before the database is opened.
- The renderer recovery replays the last data, overlay and drawing scripts instead of asking
  every panel to redraw. The chart widget is the single place that knows what the page shows.

## D-050 — Backup and restore

- A backup is the whole SQLite database copied with SQLite's online backup API, which gives a
  consistent snapshot while other connections (workers) are open. One file is easier to move
  between PCs than an export format, and nothing (imported CSV series, drawings, journal) is
  left out.
- A file to restore is untrusted data. It is opened read-only, must start with the SQLite header
  and pass `PRAGMA quick_check`, must contain this program's tables, and must not be from a
  newer schema version. Then it is staged in the data directory.
- The swap happens at the next start, before any connection exists, so no open connection
  sees the file change. The staged file is validated again. The current database (with its WAL
  files) is kept as `*.antes-de-restaurar`, and migrations then bring the restored copy up to
  date.

## D-051 — Journal statistics

- Computed from the sales only, each against the average cost (the same numbers as "Resultado
  de las ventas"), so the statistics and the sale table always agree.
- Holding time is counted from the purchase that opened the position (from zero shares) to the
  sale. With average-cost accounting there are no individual lots, so this is a "position age",
  not a per-lot holding period.
- Fewer than 10 sales shows an explicit warning: such figures can come from chance.

## D-052 — Rebalancing

- Targets are a percentage of the total value (migration 0013, `paper_targets`); the
  remainder is the cash target. A held symbol without a target is treated as 0 % and sold.
  This keeps the rule simple, and the plan table makes it visible before anything is recorded.
- The plan is pure (`portfolio/rebalance.py`). It uses the valuation prices (last close),
  sells first, and scales all purchases by the same factor when their cost plus commissions
  does not fit, keeping 1 cent of margin for rounding. Differences under 0.5 weight points or
  1 $ are ignored.
- Nothing is recorded until the user confirms. The orders are then normal paper trades dated
  today with a fixed note, so the history validation and commissions are applied as usual.
