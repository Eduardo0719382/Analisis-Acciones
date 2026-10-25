"""Global handling of uncaught exceptions: log details, show a short message.

The message box is only shown from the GUI thread (creating widgets from another
thread makes Qt abort the whole program) and never stacked: while one is open,
or shortly after it, further errors are only logged. A repeating error (e.g. in
a timer) would otherwise open box after box, each with its own nested event
loop, until the program runs out of stack.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from types import TracebackType

from analisis_acciones.models.errors import user_message_for

logger = logging.getLogger(__name__)

QUIET_SECONDS = 10.0

_state = {"showing": False, "last": 0.0}


def install_excepthook() -> None:
    def hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        try:
            logger.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
            _show_error(user_message_for(exc))
        except Exception:  # the hook itself must never raise
            logger.exception("Error while reporting an uncaught exception")

    sys.excepthook = hook


def _show_error(message: str) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from analisis_acciones.ui import strings

    if QApplication.instance() is None or threading.current_thread() is not threading.main_thread():
        return
    now = time.monotonic()
    if _state["showing"] or now - _state["last"] < QUIET_SECONDS:
        return
    _state["showing"] = True
    try:
        QMessageBox.critical(None, strings.ERROR_TITLE, message)
    finally:
        _state["showing"] = False
        _state["last"] = time.monotonic()
