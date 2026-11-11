"""Tests for the Source Apps view grouping and batch plumbing."""

import asyncio

from twinspace.core.state import CloneRecord
from twinspace.gui.views.source_apps_view import (
    SourceAppsView,
    _normalise_path,
    _SourceGroup,
)


def _record(name: str, source_app: str, source_path: str) -> CloneRecord:
    return CloneRecord(
        clone_name=name,
        source_app=source_app,
        source_path=source_path,
        bundle_id="com.example.app",
        strategy="hard_clone",
        dest_path=f"/Apps/{name}.app",
        data_dir=f"/Data/{name}",
        created_at="2026-08-20T10:00:00",
    )


def test_normalise_path_resolves_symlinks(tmp_path):
    real = tmp_path / "App.app"
    real.mkdir()
    link = tmp_path / "Link.app"
    link.symlink_to(real)
    assert _normalise_path(link) == _normalise_path(real)


def test_rebuild_groups_merges_by_source_path():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock

        service = MagicMock()
        service.list_clones = AsyncMock(
            return_value=[
                _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
                _record("WeChat-work", "WeChat", "/Applications/WeChat.app"),
                _record("Chrome-b2", "Chrome", "/Applications/Chrome.app"),
            ]
        )
        view = SourceAppsView(clone_service=service)
        view._records = await service.list_clones()
        view._rebuild_groups()

        assert len(view._groups) == 2
        names = [group.source_app for group in view._groups]
        assert names == ["Chrome", "WeChat"]  # sorted alphabetically
        wechat = next(g for g in view._groups if g.source_app == "WeChat")
        assert wechat.clone_names() == ["WeChat-b2", "WeChat-work"]
        assert view._group_of["WeChat-work"] == _normalise_path(
            "/Applications/WeChat.app"
        )

    asyncio.run(_test())


def test_rebuild_groups_falls_back_to_app_name():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock

        service = MagicMock()
        service.list_clones = AsyncMock(
            return_value=[
                _record("Tool-a", "Tool", ""),
                _record("Tool-b", "Tool", ""),
            ]
        )
        view = SourceAppsView(clone_service=service)
        view._records = await service.list_clones()
        view._rebuild_groups()

        assert len(view._groups) == 1
        assert view._groups[0].source_path == "name:Tool"

    asyncio.run(_test())


def test_running_pill_patch_counts():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock

        service = MagicMock()
        records = [
            _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
            _record("WeChat-work", "WeChat", "/Applications/WeChat.app"),
        ]
        service.list_clones = AsyncMock(return_value=records)
        view = SourceAppsView(clone_service=service)
        view._records = records
        view._rebuild_groups()
        view._sync_cards()

        card = view._cards[view._groups[0].source_path][0]
        view._running = {"WeChat-b2"}
        card.set_running(view._running)
        assert "● " in card.chip_buttons["WeChat-b2"].text
        assert "● " not in card.chip_buttons["WeChat-work"].text
        assert "1" in card.label_pill.text

    asyncio.run(_test())


def test_search_filters_groups():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock

        service = MagicMock()
        service.list_clones = AsyncMock(
            return_value=[
                _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
                _record("Chrome-b2", "Chrome", "/Applications/Chrome.app"),
            ]
        )
        view = SourceAppsView(clone_service=service)
        view._records = await service.list_clones()
        view._rebuild_groups()
        view._sync_cards()
        assert len(view._cards) == 2

        view.on_search_changed("wechat")
        assert len(view._cards) == 1
        assert view._mounted == "sources"

        view.on_search_changed("zzz")
        assert view._mounted == "empty"

        view.on_search_changed("")
        assert len(view._cards) == 2

    asyncio.run(_test())


def test_source_group_helper():
    group = _SourceGroup("/Applications/WeChat.app", "WeChat")
    assert group.clone_names() == []
