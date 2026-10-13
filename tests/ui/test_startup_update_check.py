from __future__ import annotations

from pytestqt.qtbot import QtBot

from analisis_acciones.models.errors import NetworkError
from analisis_acciones.services.settings_service import SettingsService
from analisis_acciones.services.update_service import UpdateCheck
from analisis_acciones.ui.main_window import MainWindow


class FakeService:
    def __init__(self, behind: int = 0, fail: bool = False) -> None:
        self.behind = behind
        self.fail = fail
        self.calls = 0

    def check(self) -> UpdateCheck:
        self.calls += 1
        if self.fail:
            raise NetworkError("offline")
        return UpdateCheck("main", "a", "b", self.behind, ["x"] * self.behind)


def make_window(qtbot: QtBot, settings: SettingsService, service: FakeService) -> MainWindow:
    win = MainWindow(settings, update_service=service)  # type: ignore[arg-type]
    qtbot.addWidget(win)
    win.show()
    return win


def test_notice_shown_when_update_available(qtbot: QtBot, settings: SettingsService) -> None:
    win = make_window(qtbot, settings, FakeService(behind=3))
    assert win.update_notice.isHidden()
    win.schedule_startup_update_check(delay_ms=0)
    qtbot.waitUntil(lambda: not win.update_notice.isHidden(), timeout=5000)
    assert "3 cambio" in win.update_notice.toolTip()


def test_no_notice_when_up_to_date(qtbot: QtBot, settings: SettingsService) -> None:
    service = FakeService(behind=0)
    win = make_window(qtbot, settings, service)
    win.schedule_startup_update_check(delay_ms=0)
    qtbot.waitUntil(lambda: service.calls == 1, timeout=5000)
    qtbot.wait(50)
    assert win.update_notice.isHidden()


def test_failure_is_silent(qtbot: QtBot, settings: SettingsService) -> None:
    service = FakeService(fail=True)
    win = make_window(qtbot, settings, service)
    win.schedule_startup_update_check(delay_ms=0)
    qtbot.waitUntil(lambda: service.calls == 1, timeout=5000)
    qtbot.wait(50)
    assert win.update_notice.isHidden()


def test_disabled_setting_skips_check(qtbot: QtBot, settings: SettingsService) -> None:
    settings.set_check_updates_on_startup(False)
    service = FakeService(behind=1)
    win = make_window(qtbot, settings, service)
    assert not win.check_on_startup_action.isChecked()
    win.schedule_startup_update_check(delay_ms=0)
    qtbot.wait(100)
    assert service.calls == 0


def test_menu_toggle_persists(qtbot: QtBot, settings: SettingsService) -> None:
    win = make_window(qtbot, settings, FakeService())
    win.check_on_startup_action.setChecked(False)
    assert settings.check_updates_on_startup() is False
