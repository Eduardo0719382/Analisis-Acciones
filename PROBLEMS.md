# Problems found and how they were solved

## P-001 — Qt fails to start in the Linux development container (Phase 1)

- **Symptom:** `ImportError: libEGL.so.1: cannot open shared object file` when importing
  `PySide6.QtWidgets`.
- **Cause:** the container lacks the system OpenGL/EGL and X keyboard libraries that Qt
  links against, even when running with `QT_QPA_PLATFORM=offscreen`.
- **Solution:** install `libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3` (plus the
  NSS/X libraries QtWebEngine needs for Phase 3). The CI workflow installs the same set on
  Linux. Windows does not need this.

## P-002 — Splitter sizes not restored after restart (Phase 1)

- **Symptom:** after reopening the window, the centre splitter region was narrower than
  when it was saved.
- **Cause:** `QSplitter.setSizes()` called before the window's first layout pass is
  redistributed proportionally once the window gets its real size.
- **Solution:** persist splitters with Qt's own `saveState()`/`restoreState()` (base64 in
  the settings table) instead of raw size lists. Each restored part is validated separately;
  anything invalid falls back to the defaults.

## P-003 — Window geometry clamped to 800×600 in headless tests (Phase 1, test-only)

- **Symptom:** `restoreGeometry()` restores a 1400×860 window as 800×774 under the
  `offscreen` platform, even with `-platform offscreen:size=1920x1080`.
- **Cause:** the offscreen platform reports an 800×600 available screen to
  `restoreGeometry()`, which clamps windows to the available screen.
- **Solution:** the layout round-trip test uses a window that fits in 800×600. Real-size
  restoration must be confirmed manually on Windows (checklist item at the end of Phase 1).

## P-004 — Yahoo Finance unreachable from the development container (Phase 2)

- **Symptom:** every request returns `CONNECT tunnel failed, response 403`.
- **Cause:** the container's egress policy blocks Yahoo hosts (`fc.yahoo.com`, `query*.finance.yahoo.com`).
- **Solution:**
  - Tests that run by default use a fake client serving **synthetic** data (`tests/synthetic.py`),
    clearly marked as not real prices.
  - Real calls live in `tests/live/` (marker `live`, excluded by default) and run in the
    `live-yahoo` GitHub Actions job on Windows, which has open Internet.

## P-005 — Offline reported as "ticker not found" (Phase 2)

- **Symptom:** with no connection, loading `TSLA` raised `YFTzMissingError: possibly delisted;
  no timezone found`, which the adapter mapped to "Ticker not found".
- **Cause:** yfinance swallows the network error while looking up the ticker's time zone and
  reports a missing ticker instead.
- **Solution:** before reporting "not found", the adapter makes a cheap search request. If that
  fails with a network or provider error, that error is reported instead. A regression test covers
  it, and the blocked container confirmed every live case now yields a `NetworkError`.

## P-006 — Test run hung after `main()` returned (Phase 2)

- **Symptom:** `tests/ui/test_startup.py` hung forever.
- **Cause:** two problems combined:
  1. After `main()` closed the database connections, the main window still existed. A later focus
     event made the search box read recent symbols from a closed connection.
  2. The global exception hook installed by `main()` stayed active for later tests, so it opened a
     modal error dialog that nobody could dismiss.
- **Solution:**
  - `main()` now destroys the window before closing the connections.
  - Reading recent symbols is guarded, because it is a convenience that must never break typing.
  - The startup tests restore `sys.excepthook` after each test.

## P-007 — Unknown ticker reported as a provider error after the yfinance config change (Phase 2)

- **Symptom:** the live CI test `test_invalid_ticker` failed with `ProviderError: HTTP Error 404`.
- **Cause:** setting `yf.config.debug.hide_exceptions = False` (which replaces the deprecated
  `raise_errors`) makes yfinance surface the raw HTTP 404 from its time-zone lookup. Previously
  that was converted into `YFTzMissingError`.
- **Solution:** the error mapper reads the HTTP status. 404 means "ticker not found" (still
  double-checked for connectivity, see P-005); 429 means "rate limited". Unit tests cover both
  the message-only and the `response.status_code` forms. The live CI job is what caught this,
  which is why it exists.

## P-008 — Chart crashed with an unusable system locale (Phase 3)

- **Symptom:** the chart page threw `RangeError: Invalid language tag: C`, and the series never
  appeared.
- **Cause:** the locale tag came from Qt (`C`, then `en-POSIX`), and the browser's `Intl` API does
  not accept it.
- **Solution:**
  - `chart_locale()` rejects empty, `C` and `POSIX` tags and anything that is not a clean BCP-47 tag,
    falling back to `es-ES`.
  - `chart.js` also checks `Intl.NumberFormat.supportedLocalesOf` before using the tag.

## P-009 — Volume axis showed decimals; library styles blocked (Phase 3)

- **Symptom:**
  - the volume scale read "6,000,000.00";
  - the console reported Content Security Policy violations for inline styles.
- **Cause:**
  - a chart-wide `priceFormatter` also applied to the volume scale;
  - the library sets inline styles, which the strict `style-src 'self'` policy blocked.
- **Solution:**
  - the price and volume series each have their own formatter (volume uses compact notation,
    e.g. "6 M");
  - `style-src` allows `'unsafe-inline'`, while scripts remain restricted to the bundled files.

## P-010 — Flaky details test (Phase 3, test-only)

- **Symptom:** a UI test sometimes read the details of an earlier request.
- **Cause:**
  - the test waited for "any" `details_finished` signal, and the first load's reply could arrive late;
  - after that was fixed, the provider's 60-second quote cache (correct behaviour) still served
    the earlier quote.
- **Solution:** the test now waits for the specific reply it triggers and does not rely on a quote
  being refetched. Three consecutive full runs passed.

## P-011 — Crash at process exit with the chart (Phases 3–5)

- **Symptom:** the test process sometimes ended with a segmentation fault after all tests had
  passed, and printed "Release of profile requested but WebEnginePage still not deleted".
- **Cause:** `QWebEnginePage` objects were still alive when the `QApplication` and the Chromium
  profile were torn down. `processEvents()` does not run deferred deletions, so `deleteLater()`
  had not taken effect.
- **Solution:**
  - `main()` calls `QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)` after
    scheduling the window's deletion.
  - A session fixture in the tests deletes every top-level widget before exit.
  - A real start-to-exit run of `main()` now ends with exit code 0.
- **How it surfaced:** it appeared in Phase 3 but was not caught because CI happened to exit
  cleanly. It was found while bisecting P-012.

## P-012 — SQLite connection closed while a worker used it (Phase 5)

- **Symptom:** a segmentation fault inside `sqlite3` during watchlist tests.
- **Cause:** the test fixture closed the market-data connection while snapshot workers were still
  running queries on it. The same could happen in the real app if a slow network request outlived
  the 5-second shutdown wait.
- **Solution:**
  - `MarketDataService.close()` takes the query lock; every query checks that the service is still
    open and raises a clean error otherwise.
  - Test fixtures wait for the thread pool before closing.
  - The watchlist's reply handler no longer reads settings from the database.

## P-013 — "Signal source has been deleted" after closing a window (Phase 5)

- **Symptom:** an intermittent error after a test, roughly 1 run in 10.
- **Cause:** a background reply arrived after its window (and controller) had been destroyed.
- **Solution:** the controller and chart callbacks return early when `shiboken6.isValid(self)` is
  false. After the fix: 12 consecutive runs of the file and 3 full runs with no failures.

## P-014 — Flat market reported as a bearish trend (Phase 6)

- **Symptom:** a deliberately flat test series produced "Tendencia bajista detectada".
- **Cause:** the rule compared EMA 20 and EMA 50 with no tolerance, so 99.98 against 99.99 counted
  as "EMA 20 < EMA 50".
- **Solution:** a trend is reported only when the EMAs differ by at least 0.5 % and the close is on
  the same side. Otherwise the market is reported as sideways, and the actual separation appears
  in the evidence.

## P-015 — Rare crash in a Chromium thread during test teardown (Phase 9)

- **Symptom:** about 1 in 8 full test runs ended with a segmentation fault in a non-Python thread
  while pytest-qt processed events after `test_main_window_notifies`. It never reproduced with
  the UI tests alone (10 runs), in a stress test that created and destroyed 40 charts, or in
  real start-to-exit runs of the app.
- **Probable cause:** dozens of `QWebEngineView` pages from earlier tests stayed alive until the end
  of the session, and Chromium tore some of them down in the wrong order.
- **Mitigation:** an autouse fixture in `tests/ui/conftest.py` now destroys each test's windows and
  pages, and flushes deferred deletions, before the next test starts. After the change: 8 full
  runs with no crash.
- **Status:** monitored. Because the root cause was not proven, this is recorded as a mitigation
  rather than a fix.
- **Update:** the crash happened again (2 of about 27 full runs), always while tearing down
  `test_main_window_notifies`. That test triggers `QApplication.alert()` on a window that was never
  shown, so no native window exists to flash. The call is now made only for visible windows. The
  real app always shows its window, so this case does not occur in normal use.

## P-016 — Initial visible range depended on layout timing (Phase 9, test)

- **Symptom:** a chart test sometimes saw the visible range start at bar 45 instead of about 120.
- **Cause:** the initial range was applied before the widget's final size was known; Lightweight
  Charts then keeps the bar spacing when it resizes, which changes how many bars fit.
- **Solution:**
  - The page re-applies the initial range on the next animation frame.
  - The test now checks what is actually intended: the right edge sits at the last bar and the
    full history is not shown.
