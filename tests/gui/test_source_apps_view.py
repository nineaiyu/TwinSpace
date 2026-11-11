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
        # Running marker is a standalone green dot label beside the chip
        # (environment-page app-tile pattern), not part of the button title.
        assert card.chip_buttons["WeChat-b2"].text == "WeChat-b2"
        assert card.chip_dots["WeChat-b2"].style.visibility == "visible"
        # toga normalises the hex theme color; rgb(52 199 89) == #34C759
        assert str(card.chip_dots["WeChat-b2"].style.color) == "rgb(52 199 89 / 1.0)"
        assert card.chip_dots["WeChat-work"].style.visibility == "hidden"
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


def test_chips_wrap_into_rows_of_four():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock

        service = MagicMock()
        records = [
            _record(f"WeChat-{i}", "WeChat", "/Applications/WeChat.app")
            for i in range(6)
        ]
        service.list_clones = AsyncMock(return_value=records)
        view = SourceAppsView(clone_service=service)
        view._records = records
        view._rebuild_groups()
        view._sync_cards()

        card = view._cards[view._groups[0].source_path][0]
        rows = card.chips_box.children
        assert len(rows) == 2
        assert len(rows[0].children) == 4
        assert len(rows[1].children) == 2

    asyncio.run(_test())


def test_set_stats_shows_update_count_on_button():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock

        service = MagicMock()
        records = [_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")]
        service.list_clones = AsyncMock(return_value=records)
        view = SourceAppsView(clone_service=service)
        view._records = records
        view._rebuild_groups()
        view._sync_cards()

        card = view._cards[view._groups[0].source_path][0]
        card.set_stats(1024 * 1024 * 500, 2)
        assert "(2)" in card.btn_update.text
        assert "500.0 MB" in card.label_stats.text
        card.set_stats(1024, 0)
        assert "(" not in card.btn_update.text

    asyncio.run(_test())


def test_source_missing_warning_shown():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock

        service = MagicMock()
        records = [
            _record("Ghost-1", "Ghost", "/Applications/GhostApp.app")  # 不存在
        ]
        service.list_clones = AsyncMock(return_value=records)
        view = SourceAppsView(clone_service=service)
        view._records = records
        view._rebuild_groups()
        view._sync_cards()

        card = view._cards[view._groups[0].source_path][0]
        assert card._source_missing is True
        assert card.label_warning is not None

    asyncio.run(_test())


def test_divider_lines_between_cards():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock

        service = MagicMock()
        service.list_clones = AsyncMock(
            return_value=[
                _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
                _record("Chrome-b2", "Chrome", "/Applications/Chrome.app"),
                _record("Qoder-b2", "Qoder", "/Applications/Qoder.app"),
            ]
        )
        view = SourceAppsView(clone_service=service)
        view._records = await service.list_clones()
        view._rebuild_groups()
        view._sync_cards()

        # 3 张卡片 + 2 条分隔线
        assert len(view.list_box.children) == 5
        dividers = [
            child
            for child in view.list_box.children
            if child.style.height == 1
        ]
        assert len(dividers) == 2

    asyncio.run(_test())


def test_source_group_helper():
    group = _SourceGroup("/Applications/WeChat.app", "WeChat")
    assert group.clone_names() == []


def test_close_all_keeps_cards_mounted():
    """Regression: 「全部关闭」used to tear the page down to a full-page spinner,
    forcing every card to remount — it looked like a whole-page refresh and
    reset the scroll position. Cards must survive in place now."""

    async def _test():
        from unittest.mock import AsyncMock, MagicMock, patch

        service = MagicMock()
        records = [_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")]
        service.list_clones = AsyncMock(return_value=records)
        view = SourceAppsView(clone_service=service)
        view._records = records
        view._rebuild_groups()
        view._sync_cards()
        view._running = {"WeChat-b2"}

        card_before = view._cards[view._groups[0].source_path][0]
        assert view._mounted == "sources"

        with patch(
            "twinspace.gui.views.source_apps_view.quit_clones",
            return_value={records[0].dest_path: True},
        ):
            await view._close_all(view._groups[0])

        card_after = view._cards[view._groups[0].source_path][0]
        assert card_after is card_before  # same widget instance, not remounted
        assert view._mounted == "sources"  # page never torn down
        assert "WeChat-b2" not in view._running  # chip state patched in place

    asyncio.run(_test())


def test_batch_actions_show_no_loading_ui():
    """Batch open/close/update must not show any loading UI (environment-page
    convention): the mounted page stays untouched and no status strip exists."""

    async def _test():
        from unittest.mock import AsyncMock, MagicMock, patch

        service = MagicMock()
        records = [_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")]
        service.list_clones = AsyncMock(return_value=records)
        view = SourceAppsView(clone_service=service)
        view._records = records
        view._rebuild_groups()
        view._sync_cards()
        assert view.scroll in view.content_container.children
        children_before = list(view.content_container.children)

        with patch(
            "twinspace.gui.views.source_apps_view.quit_clones",
            return_value={records[0].dest_path: True},
        ):
            await view._close_all(view._groups[0])

        assert not hasattr(view, "_busy_strip")
        assert view.content_container.children == children_before
        assert view._mounted == "sources"

    asyncio.run(_test())


def test_show_loading_full_page_only_before_first_mount():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock

        service = MagicMock()
        service.list_clones = AsyncMock(return_value=[])
        view = SourceAppsView(clone_service=service)
        view._show_loading()
        assert view._mounted == "loading"
        view._hide_loading()

    asyncio.run(_test())
