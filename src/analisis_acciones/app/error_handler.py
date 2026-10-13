"""Global handling of uncaught exceptions: log details, show a short message."""

from __future__ import annotations

import logging
import sys
from types import TracebackType

from analisis_acciones.models.errors import user_message_for

logger = logging.getLogger(__name__)


def install_excepthook() -> None:
    def hook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical("Uncaught exception", exc_info=(exc_type, exc, tb))
        _show_error(user_message_for(exc))

    sys.excepthook = hook


def _show_error(message: str) -> None:
    from PySide6.QtWidgets import QApplication, QMessageBox

    from analisis_acciones.ui import strings

    if QApplication.instance() is not None:
        QMessageBox.critical(None, strings.ERROR_TITLE, message)
