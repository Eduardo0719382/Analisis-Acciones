from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _destroy_windows_after_test(qapp: object) -> Iterator[None]:
    """Destroy each test's windows (and their web pages) before the next test starts.

    Letting dozens of QWebEngine pages accumulate until session end occasionally
    crashed Chromium during teardown (PROBLEMS.md P-015).
    """
    yield
    from PySide6.QtCore import QCoreApplication, QEvent, QThreadPool
    from PySide6.QtWidgets import QApplication

    QThreadPool.globalInstance().waitForDone(10_000)
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()
