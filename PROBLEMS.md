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
