"""Tests for SidebarNav check update UI integration and SettingsView decoupling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import toga
from toga.style.pack import HIDDEN

from twinspace import __version__
from twinspace.core.i18n import set_language, t
from twinspace.gui.components.sidebar import SidebarNav
from twinspace.gui.services.update_service import UpdateInfo
from twinspace.gui.views.settings_view import SettingsView


def test_settings_view_no_longer_has_update_widgets(toga_app):
    """SettingsView should no longer host check update button or status label."""
    view = SettingsView()
    assert not hasattr(view, "btn_check_update")
    assert not hasattr(view, "lbl_update_status")
    assert not hasattr(view, "update_service")


def test_sidebar_update_widgets_exist(toga_app):
    """SidebarNav must contain update button, progress bar, and status label."""
    set_language("zh")
    sidebar = SidebarNav(on_select=lambda k: None)
    assert hasattr(sidebar, "btn_check_update")
    assert hasattr(sidebar, "progress_bar")
    assert hasattr(sidebar, "lbl_update_status")

    assert sidebar.btn_check_update.text == t("settings_btn_check_update")
    assert isinstance(sidebar.lbl_update_status, toga.Label)
    assert sidebar.lbl_update_status.text == ""
    assert str(sidebar.progress_bar.style.visibility) == str(HIDDEN)
    set_language(None)


def test_sidebar_on_check_update_already_latest(toga_app):
    async def _test():
        set_language("zh")
        sidebar = SidebarNav(on_select=lambda k: None)
        sidebar.update_service = AsyncMock()
        sidebar.update_service.check_for_updates.return_value = None

        await sidebar.on_check_update(sidebar.btn_check_update)

        assert t("update_already_latest", ver=__version__) in sidebar.lbl_update_status.text
        assert sidebar.btn_check_update.enabled is True
        assert str(sidebar.progress_bar.style.visibility) == str(HIDDEN)
        set_language(None)

    asyncio.run(_test())


def test_sidebar_on_check_update_failure(toga_app):
    async def _test():
        sidebar = SidebarNav(on_select=lambda k: None)
        sidebar.update_service = AsyncMock()
        sidebar.update_service.check_for_updates.side_effect = Exception("Network offline")

        await sidebar.on_check_update(sidebar.btn_check_update)

        assert "❌" in sidebar.lbl_update_status.text
        assert sidebar.btn_check_update.enabled is True
        assert str(sidebar.progress_bar.style.visibility) == str(HIDDEN)

    asyncio.run(_test())


def test_sidebar_retranslate_updates_check_update_btn():
    set_language("en")
    sidebar = SidebarNav(on_select=lambda k: None)
    assert sidebar.btn_check_update.text == "🔄 Check for Updates"

    set_language("zh")
    sidebar.retranslate()
    assert sidebar.btn_check_update.text == "🔄 检查更新"
    set_language(None)


def test_sidebar_on_check_update_download_progress(toga_app, monkeypatch):
    async def _test():
        set_language("zh")
        mock_app = MagicMock()
        mock_app.main_window = MagicMock()
        mock_app.main_window.info_dialog = AsyncMock()

        exit_called = []
        monkeypatch.setattr("os._exit", lambda code: exit_called.append(code))

        sidebar = SidebarNav(on_select=lambda k: None, app=mock_app)
        sidebar.update_service = AsyncMock()
        update_info = UpdateInfo(
            version="1.2.0",
            notes="Bugfixes and improvements",
            pub_date="2026-09-17",
            checksum="abc123def456",
            download_url="https://example.com/TwinSpace.dmg",
        )
        sidebar.update_service.check_for_updates.return_value = update_info

        async def _mock_download_and_install(info, on_progress, on_status):
            on_status("downloading")
            on_progress(500, 1000)
            on_status("installing")

        sidebar.update_service.download_and_install.side_effect = _mock_download_and_install

        await sidebar.on_check_update(sidebar.btn_check_update)

        # Allow any loop.call_soon_threadsafe tasks to run
        await asyncio.sleep(0.05)

        assert exit_called == [0]
        assert mock_app.main_window.info_dialog.called
        set_language(None)

    asyncio.run(_test())
