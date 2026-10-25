"""Protection against, and diagnosis of, unexpected exits.

* Native crashes (e.g. inside Qt or Chromium) cannot be caught, but
  ``faulthandler`` writes the Python stack of every thread to ``crash.log``.
* Exceptions in background threads and "unraisable" ones (raised in __del__
  or callbacks) are logged instead of being lost.
* Without a console (``pythonw.exe``, double-click launch) ``sys.stdout`` and
  ``sys.stderr`` are None; a library that writes to them directly would fail,
  so they are pointed at the null device.
* A session marker file tells whether the previous run ended without a clean
  shutdown. After repeated unexpected exits the program switches the web
  views to software rendering, the usual remedy for Chromium GPU-process
  failures on some Windows graphics drivers.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)

CRASH_LOG_NAME = "crash.log"
MARKER_NAME = "session.running"
SOFTWARE_FLAG_NAME = "graphics_software"
AUTO_SOFTWARE_AFTER = 2  # consecutive unexpected exits before switching
SOFTWARE_CHROMIUM_FLAGS = ("--disable-gpu", "--disable-gpu-compositing")
MAX_CRASH_LOG_BYTES = 2_000_000

_crash_file: IO[str] | None = None


def ensure_std_streams() -> None:
    """Give pythonw.exe processes harmless stdout/stderr."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def install_diagnostics(log_dir: Path) -> Path:
    """Enable faulthandler into ``crash.log`` and log thread/unraisable exceptions."""
    global _crash_file
    path = log_dir / CRASH_LOG_NAME
    try:
        if path.exists() and path.stat().st_size > MAX_CRASH_LOG_BYTES:
            path.replace(path.with_suffix(".log.1"))
        _crash_file = open(path, "a", encoding="utf-8")  # noqa: SIM115 (kept open for life)
        faulthandler.enable(file=_crash_file, all_threads=True)
    except OSError as exc:
        logger.warning("Could not enable crash diagnostics in %s: %s", path, exc)

    def thread_hook(args: threading.ExceptHookArgs) -> None:
        if args.exc_type is SystemExit:
            return
        logger.error(
            "Uncaught exception in thread %s",
            args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value or args.exc_type(), args.exc_traceback),
        )

    def unraisable_hook(unraisable: Any) -> None:
        logger.warning(
            "Ignored exception (%s): %s",
            getattr(unraisable, "err_msg", None) or "unraisable",
            getattr(unraisable, "exc_value", None),
        )

    threading.excepthook = thread_hook
    sys.unraisablehook = unraisable_hook
    return path


@dataclass(frozen=True)
class SessionStart:
    previous_unclean: bool
    consecutive_unclean: int
    software_rendering: bool
    switched_to_software: bool  # turned on automatically now


class SessionGuard:
    """Detects unclean exits and owns the software-rendering switch (files in the data dir)."""

    def __init__(self, root: Path) -> None:
        self.marker = root / MARKER_NAME
        self.software_flag = root / SOFTWARE_FLAG_NAME

    def begin(self) -> SessionStart:
        count = 0
        unclean = self.marker.exists()
        if unclean:
            try:
                count = int(self.marker.read_text(encoding="utf-8").strip() or "0") + 1
            except (OSError, ValueError):
                count = 1
        switched = False
        if count >= AUTO_SOFTWARE_AFTER and not self.software_rendering:
            self.set_software_rendering(True)
            switched = True
        try:
            self.marker.write_text(str(count), encoding="utf-8")
        except OSError as exc:
            logger.warning("Could not write session marker: %s", exc)
        return SessionStart(unclean, count, self.software_rendering, switched)

    def end(self) -> None:
        """Clean shutdown."""
        try:
            self.marker.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove session marker: %s", exc)

    @property
    def software_rendering(self) -> bool:
        return self.software_flag.exists()

    def set_software_rendering(self, enabled: bool) -> None:
        try:
            if enabled:
                self.software_flag.write_text("1", encoding="utf-8")
            else:
                self.software_flag.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not change the graphics mode: %s", exc)


def apply_software_rendering() -> None:
    """Must run before the QApplication is created."""
    from PySide6.QtCore import QCoreApplication, Qt

    flags = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "").split()
    flags += [f for f in SOFTWARE_CHROMIUM_FLAGS if f not in flags]
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = " ".join(flags)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL, True)
