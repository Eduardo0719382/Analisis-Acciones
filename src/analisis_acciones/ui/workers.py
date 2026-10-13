"""Run blocking work off the UI thread and deliver the outcome through Qt signals."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

logger = logging.getLogger(__name__)


class WorkerSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(object)  # the exception instance


class Worker(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self._fn = fn
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:
            logger.warning("Background task failed: %s", exc, exc_info=True)
            self.signals.failed.emit(exc)
        else:
            self.signals.succeeded.emit(result)


def start_worker(
    fn: Callable[[], Any],
    on_success: Callable[[Any], None],
    on_failure: Callable[[BaseException], None],
    pool: QThreadPool | None = None,
) -> Worker:
    """Start ``fn`` on a pool thread. Callbacks run on the receiver's (UI) thread."""
    worker = Worker(fn)
    worker.signals.succeeded.connect(on_success)
    worker.signals.failed.connect(on_failure)
    (pool or QThreadPool.globalInstance()).start(worker)
    return worker
