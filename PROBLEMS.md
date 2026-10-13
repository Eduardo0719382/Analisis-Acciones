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
