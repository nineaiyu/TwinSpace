"""Comprehensive GUI i18n & dynamic translation tests."""

from unittest.mock import patch

from twinspace.core.i18n import set_language
from twinspace.gui.app import TwinSpaceApp
from twinspace.gui.components.sidebar import SidebarNav
from twinspace.gui.components.top_bar import TopHeaderBar
from twinspace.gui.views.clone_list import CloneListView
from twinspace.gui.views.doctor_view import DoctorView
from twinspace.gui.views.logs_view import LogsView
from twinspace.gui.views.probe_view import ProbeView
from twinspace.gui.views.recipe_list import RecipeListView
from twinspace.gui.views.settings_view import SettingsView


def test_sidebar_nav_i18n_multi_language():
    for lang, expected_clones in [
        ("en", "Clones"),
        ("zh", "我的分身"),
    ]:
        set_language(lang)
        sidebar = SidebarNav(on_select=lambda k: None)
        assert expected_clones in sidebar.buttons["clones"].text
        assert len(sidebar.buttons["settings"].text) > 0


def test_top_header_bar_i18n():
    set_language("en")
    top_bar_en = TopHeaderBar(on_action=lambda w: None, on_refresh=lambda w: None)
    assert top_bar_en.btn_action.text == "+ New Clone"
    assert top_bar_en.btn_refresh.text == "🔄 Refresh"

    set_language("zh")
    top_bar_zh = TopHeaderBar(on_action=lambda w: None, on_refresh=lambda w: None)
    assert top_bar_zh.btn_action.text == "+ 新建分身"
    assert top_bar_zh.btn_refresh.text == "🔄 刷新"


def test_views_i18n_multi_language():
    for lang in ("en", "zh"):
        set_language(lang)
        clone_v = CloneListView()
        assert clone_v.top_bar is not None
        assert clone_v.table is not None

        recipe_v = RecipeListView()
        assert recipe_v.top_bar is not None
        assert recipe_v.table is not None

        probe_v = ProbeView()
        assert probe_v.label_app_name is not None

        doctor_v = DoctorView()
        assert doctor_v.label_summary is not None

        logs_v = LogsView()
        assert logs_v.top_bar is not None

        settings_v = SettingsView()
        assert settings_v.select_language is not None
        assert settings_v.btn_release_notes is not None
        assert len(settings_v.btn_release_notes.text) > 0


def test_app_retranslate_ui(tmp_path, monkeypatch):
    from twinspace.core import config
    monkeypatch.setattr(config, "DEFAULT_CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(config, "DEFAULT_TWINSPACE_DIR", tmp_path)

    app = TwinSpaceApp(formal_name="TwinSpaceTest", app_id="com.test.twinspace")
    # Mock window show and cocoa calls
    with patch("twinspace.gui.app.set_macos_dock_icon"), \
         patch("toga.MainWindow.show"):
        app.startup()

        # Default Chinese or system
        set_language("zh")
        app.retranslate_ui()
        assert "我的分身" in app.sidebar.buttons["clones"].text
        assert "更新日志" in app.settings_view.btn_release_notes.text

        # Switch to English
        set_language("en")
        app.retranslate_ui()
        assert "Clones" in app.sidebar.buttons["clones"].text
        assert "Release Notes" in app.settings_view.btn_release_notes.text

