from __future__ import annotations

from pytestqt.qtbot import QtBot

from analisis_acciones.models.errors import NetworkError
from analisis_acciones.services.update_service import UpdateCheck, UpdateResult
from analisis_acciones.ui import strings
from analisis_acciones.ui.update_dialog import UpdateDialog


class FakeUpdateService:
    def __init__(self, behind: int = 0, fail_check: bool = False, deps: bool = False) -> None:
        self.behind = behind
        self.fail_check = fail_check
        self.deps = deps
        self.applied = False

    def check(self) -> UpdateCheck:
        if self.fail_check:
            raise NetworkError("offline")
        changes = [f"<b>cambio {i}</b>" for i in range(self.behind)]
        return UpdateCheck("main", "aaa", "bbb", self.behind, changes)

    def apply(self) -> UpdateResult:
        self.applied = True
        return UpdateResult("aaa", "bbb", self.deps)


def make_dialog(qtbot: QtBot, service: FakeUpdateService) -> UpdateDialog:
    dialog = UpdateDialog(service)  # type: ignore[arg-type]
    qtbot.addWidget(dialog)
    dialog.start()
    qtbot.waitUntil(lambda: dialog.message.text() != strings.UPDATE_CHECKING, timeout=5000)
    return dialog


def test_up_to_date(qtbot: QtBot) -> None:
    dialog = make_dialog(qtbot, FakeUpdateService(behind=0))
    assert dialog.message.text() == strings.UPDATE_UP_TO_DATE
    assert dialog.update_button.isHidden()
    assert dialog.close_button.isEnabled()


def test_available_apply_and_restart(qtbot: QtBot) -> None:
    service = FakeUpdateService(behind=2, deps=True)
    dialog = make_dialog(qtbot, service)
    assert "2 cambio" in dialog.message.text()
    assert not dialog.update_button.isHidden()
    # Commit messages are shown verbatim as plain text, never rendered as markup.
    assert "<b>cambio 0</b>" in dialog.changes.toPlainText()

    dialog.update_button.click()
    qtbot.waitUntil(lambda: not dialog.restart_button.isHidden(), timeout=5000)
    assert service.applied
    assert strings.UPDATE_DEPS_REINSTALLED in dialog.message.text()

    dialog.restart_button.click()
    assert dialog.restart_requested


def test_failure_shows_user_message(qtbot: QtBot) -> None:
    dialog = make_dialog(qtbot, FakeUpdateService(fail_check=True))
    assert dialog.message.text() == NetworkError.default_user_message
    assert dialog.update_button.isHidden()
    assert dialog.close_button.isEnabled()
