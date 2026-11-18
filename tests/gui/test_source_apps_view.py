"""Tests for the Source Apps view grouping, cards and batch plumbing."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import toga

from twinspace.core.app_version import AppUpdate
from twinspace.core.i18n import t
from twinspace.core.state import CloneRecord
from twinspace.gui import cocoa_events
from twinspace.gui.components.app_tile import AppTile, compute_tile_columns
from twinspace.gui.views.source_apps_view import (
    _SEARCH_DEBOUNCE,
    SourceAppCard,
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


def _service(records: list[CloneRecord]) -> MagicMock:
    service = MagicMock()
    service.state_manager = None
    service.list_clones = AsyncMock(return_value=records)
    service.update_clone = AsyncMock()
    return service


def _view(records: list[CloneRecord], app=None) -> SourceAppsView:
    """Build a mounted view without going through the async refresh."""
    view = SourceAppsView(clone_service=_service(records), app=app)
    view._records = records
    view._rebuild_groups()
    view._sync_cards()
    return view


def _card(view: SourceAppsView, group_index: int = 0) -> SourceAppCard:
    return view._cards[view._groups[group_index].source_path][0]


def test_normalise_path_resolves_symlinks(tmp_path):
    real = tmp_path / "App.app"
    real.mkdir()
    link = tmp_path / "Link.app"
    link.symlink_to(real)
    assert _normalise_path(link) == _normalise_path(real)


def test_rebuild_groups_merges_by_source_path():
    records = [
        _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
        _record("WeChat-work", "WeChat", "/Applications/WeChat.app"),
        _record("Chrome-b2", "Chrome", "/Applications/Chrome.app"),
    ]
    view = _view(records)

    assert len(view._groups) == 2
    names = [group.source_app for group in view._groups]
    assert names == ["Chrome", "WeChat"]  # sorted alphabetically
    wechat = next(g for g in view._groups if g.source_app == "WeChat")
    assert wechat.clone_names() == ["WeChat-b2", "WeChat-work"]
    assert view._group_of["WeChat-work"] == _normalise_path(
        "/Applications/WeChat.app"
    )
    assert view._record_by_name["WeChat-work"].clone_name == "WeChat-work"


def test_rebuild_groups_falls_back_to_app_name():
    view = _view([_record("Tool-a", "Tool", ""), _record("Tool-b", "Tool", "")])

    assert len(view._groups) == 1
    assert view._groups[0].source_path == "name:Tool"


def test_card_uses_tiles_and_running_pill_patches_in_place():
    records = [
        _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
        _record("WeChat-work", "WeChat", "/Applications/WeChat.app"),
    ]
    view = _view(records)
    card = _card(view)

    # One Finder-style tile per clone instead of a wall of buttons.
    assert set(card.tiles) == {"WeChat-b2", "WeChat-work"}
    assert all(isinstance(tile, AppTile) for tile in card.tiles.values())

    view._running = {"WeChat-b2"}
    card.set_running(view._running)
    assert card.tiles["WeChat-b2"].running is True
    assert card.tiles["WeChat-work"].running is False
    assert "1" in card.label_pill.text
    # toga normalises the hex theme color; rgb(52 199 89) == #34C759
    assert str(card.status_dot.style.color) == "rgb(52 199 89 / 1.0)"
    assert card.btn_close.enabled is True
    assert card.btn_open.enabled is True  # one clone still idle


def test_clicking_a_tile_paints_the_selection_pill():
    records = [
        _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
        _record("WeChat-work", "WeChat", "/Applications/WeChat.app"),
    ]
    view = _view(records)
    card = _card(view)
    first = card.tiles["WeChat-b2"]

    view._select_tile(first, cocoa_events.SELECT_REPLACE)
    assert view.selected_clone == "WeChat-b2"
    assert first.selected is True
    assert card.tiles["WeChat-work"].selected is False

    # Selection survives a repaint.
    view._sync_cards()
    assert first.selected is True

    # ⌘-click on the selected tile clears it.
    view._select_tile(first, cocoa_events.SELECT_TOGGLE)
    assert view.selected_clone is None
    assert first.selected is False


def test_compute_sizes_reports_progress_and_restores_button(monkeypatch):
    async def _test():
        records = [
            _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
            _record("WeChat-work", "WeChat", "/Applications/WeChat.app"),
        ]
        view = _view(records)
        card = _card(view)
        seen: list[str] = []

        def fake_size(path: str) -> int:
            seen.append(view.top_bar.btn_secondary.text)
            return 1024 * 1024

        monkeypatch.setattr(
            "twinspace.gui.views.source_apps_view.data_size", fake_size
        )
        await view._compute_sizes()

        assert view._sizes_computed is True
        assert set(view._sizes.values()) == {1024 * 1024}
        # The toolbar reported progress while the loop was running, then went
        # back to its idle label.
        assert seen[1] == t("btn_computing_sizes", current=1, total=2)
        assert view.top_bar.btn_secondary.text == t("btn_compute_sizes")
        assert "2.0 MB" in card.label_stats.text

    asyncio.run(_test())


def test_card_progress_pill_disables_update_and_restores():
    view = _view([_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")])
    card = _card(view)
    card.set_stats(None, 2)
    assert card.btn_update.enabled is True

    progress = t("sources_progress_updating", current=1, total=2, clone="WeChat-b2")
    card.set_progress(progress)
    assert card.label_pill.text == progress
    assert card.btn_update.enabled is False

    card.set_progress(None)
    assert card.label_pill.text == t("environment_not_running")
    assert card.btn_update.enabled is True


def test_update_all_marks_each_tile_as_updating():
    async def _test():
        records = [
            _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
            _record("WeChat-work", "WeChat", "/Applications/WeChat.app"),
        ]
        view = _view(records)
        view._status = {
            name: AppUpdate("1.0", "2.0", needs_update=True)
            for name in ("WeChat-b2", "WeChat-work")
        }
        view._confirm = AsyncMock(return_value=True)
        view._info = AsyncMock()
        view._error = AsyncMock()
        view.refresh_sources = AsyncMock()
        card = _card(view)

        seen: list[tuple[str, bool, str]] = []

        async def _update(name: str) -> None:
            tile = card.tiles[name]
            seen.append((name, tile.updating, card.label_pill.text))

        view.clone_service.update_clone = AsyncMock(side_effect=_update)
        await view._update_all(view._groups[0])

        assert [entry[0] for entry in seen] == ["WeChat-b2", "WeChat-work"]
        # While the rebuild is awaited the tile says 更新中 and the card pill
        # shows the running index; both are cleared once the group finishes.
        assert all(entry[1] for entry in seen)
        assert seen[0][2] == t(
            "sources_progress_updating", current=1, total=2, clone="WeChat-b2"
        )
        assert all(tile.updating is False for tile in card.tiles.values())
        assert card.label_pill.text == t("environment_not_running")
        assert view._updating_groups == set()

    asyncio.run(_test())


def test_update_all_clears_badge_as_soon_as_one_clone_finishes():
    async def _test():
        records = [
            _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
            _record("WeChat-work", "WeChat", "/Applications/WeChat.app"),
        ]
        view = _view(records)
        view._status = {
            name: AppUpdate("1.0", "2.0", needs_update=True)
            for name in ("WeChat-b2", "WeChat-work")
        }
        view._sync_cards()
        view._confirm = AsyncMock(return_value=True)
        view._info = AsyncMock()
        view._error = AsyncMock()
        view.refresh_sources = AsyncMock()
        card = _card(view)
        assert card.tiles["WeChat-b2"].update_label.text == t(
            "env_app_update_badge", version="2.0"
        )

        seen: list[tuple[bool, str]] = []

        async def _update(name: str) -> None:
            # The next clone starts rebuilding: the previous one must already
            # show as up to date, not wait for the whole group to finish.
            seen.append(
                (card.tiles["WeChat-b2"].update_available, card.update_badge.text)
            )

        view.clone_service.update_clone = AsyncMock(side_effect=_update)
        with patch(
            "twinspace.gui.views.source_apps_view.update_status",
            return_value=AppUpdate("2.0", "2.0", needs_update=False),
        ):
            await view._update_all(view._groups[0])

        assert seen[1][0] is False
        assert card.tiles["WeChat-b2"].update_label.text == ""
        assert card.tiles["WeChat-work"].update_label.text == ""
        assert card.update_badge.text == ""
        assert "(" not in card.btn_update.text

    asyncio.run(_test())


def test_search_filters_groups_without_rebuilding_cards():
    records = [
        _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
        _record("Chrome-b2", "Chrome", "/Applications/Chrome.app"),
    ]
    view = _view(records)
    assert len(view._cards) == 2
    chrome_key = _normalise_path("/Applications/Chrome.app")
    chrome_card = view._cards[chrome_key][0]

    view.on_search_changed("wechat")
    assert len(view._cards) == 1
    assert view._mounted == "sources"

    view.on_search_changed("zzz")
    assert view._mounted == "empty"

    view.on_search_changed("")
    assert len(view._cards) == 2
    # The hidden card was pooled, not destroyed: same native widgets return.
    assert view._cards[chrome_key][0] is chrome_card
    assert view._pool == {}


def test_search_keystrokes_are_coalesced():
    async def _test():
        records = [
            _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
            _record("Chrome-b2", "Chrome", "/Applications/Chrome.app"),
        ]
        view = _view(records)

        view.on_search_changed("wechat")
        view.on_search_changed("chrome")
        # Nothing is rendered until typing pauses: only the last query pays.
        assert len(view._cards) == 2

        await asyncio.sleep(_SEARCH_DEBOUNCE + 0.1)
        assert len(view._cards) == 1
        assert view._filtered_groups()[0].source_app == "Chrome"

    asyncio.run(_test())


def test_search_matches_bundle_id():
    records = [_record("App-1", "App", "/Applications/App.app")]
    view = _view(records)

    view.on_search_changed("com.example")
    assert len(view._cards) == 1


def test_set_stats_shows_update_count_on_button():
    records = [_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")]
    view = _view(records)
    card = _card(view)

    card.set_stats(1024 * 1024 * 500, 2)
    assert "(2)" in card.btn_update.text
    assert "500.0 MB" in card.label_stats.text
    assert card.btn_update.enabled is True
    assert "2" in card.update_badge.text

    card.set_stats(1024, 0)
    assert "(" not in card.btn_update.text
    assert card.btn_update.enabled is False
    assert card.update_badge.text == ""


def test_source_missing_warning_and_disabled_update():
    view = _view([_record("Ghost-1", "Ghost", "/Applications/GhostApp.app")])
    view._groups[0].source_exists = False
    view._sync_cards()

    card = _card(view)
    assert card._source_missing is True
    assert card.label_warning is not None

    card.set_stats(None, 3)
    assert card.btn_update.enabled is False  # nothing to rebuild from


def test_cards_are_rounded_cards_without_dividers():
    records = [
        _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
        _record("Chrome-b2", "Chrome", "/Applications/Chrome.app"),
        _record("Qoder-b2", "Qoder", "/Applications/Qoder.app"),
    ]
    view = _view(records)

    children = list(view.list_box.children)
    assert len(children) == 3
    assert all(isinstance(child, SourceAppCard) for child in children)
    # Card spacing replaces the old 1px separator rows.
    assert [child.style.margin_bottom for child in children] == [14, 14, 14]


def test_tiles_flow_into_rows_of_computed_columns():
    records = [
        _record(f"WeChat-{i}", "WeChat", "/Applications/WeChat.app")
        for i in range(6)
    ]
    view = _view(records)
    card = _card(view)

    columns = compute_tile_columns(view._content_width)
    rows = card.grid.children
    assert len(rows) == (6 + columns - 1) // columns
    assert len(rows[0].children) == columns + 1  # tiles + trailing spacer

    # A resize reflows the same tile widgets instead of rebuilding them.
    tiles_before = dict(card.tiles)
    view.on_window_resize(760)
    assert set(card.tiles) == set(tiles_before)
    assert all(card.tiles[name] is tiles_before[name] for name in tiles_before)


def test_sort_by_clone_count_and_filter_by_updates():
    records = [
        _record("WeChat-1", "WeChat", "/Applications/WeChat.app"),
        _record("WeChat-2", "WeChat", "/Applications/WeChat.app"),
        _record("WeChat-3", "WeChat", "/Applications/WeChat.app"),
        _record("Chrome-1", "Chrome", "/Applications/Chrome.app"),
    ]
    view = _view(records)
    view._status = {
        "Chrome-1": AppUpdate("1.0", "2.0", needs_update=True),
        "WeChat-1": AppUpdate("1.0", "1.0", needs_update=False),
    }

    view.on_sort_changed(t("sources_sort_clones"))
    assert view._filtered_groups()[0].source_app == "WeChat"

    view.on_filter_changed(t("sources_filter_updates"))
    assert [group.source_app for group in view._filtered_groups()] == ["Chrome"]
    assert len(view._cards) == 1

    view._clear_filters()
    assert len(view._cards) == 2


def test_close_all_keeps_cards_mounted():
    """Regression: 「全部关闭」used to tear the page down to a full-page spinner,
    forcing every card to remount — it looked like a whole-page refresh and
    reset the scroll position. Cards must survive in place now."""

    async def _test():
        records = [_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")]
        view = _view(records)
        view._running = {"WeChat-b2"}

        card_before = _card(view)
        assert view._mounted == "sources"

        with patch(
            "twinspace.gui.views.source_apps_view.quit_clones",
            return_value={records[0].dest_path: True},
        ):
            await view._close_all(view._groups[0])

        assert _card(view) is card_before  # same widget instance, not remounted
        assert view._mounted == "sources"  # page never torn down
        assert "WeChat-b2" not in view._running  # tile/pill patched in place
        assert card_before.tiles["WeChat-b2"].running is False

    asyncio.run(_test())


def test_batch_actions_show_no_loading_ui():
    """Batch open/close/update must not show any loading UI (environment-page
    convention): the mounted page stays untouched and no status strip exists."""

    async def _test():
        records = [_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")]
        view = _view(records)
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


def test_update_all_skips_running_clones_and_confirms():
    async def _test():
        records = [
            _record("WeChat-b2", "WeChat", "/Applications/WeChat.app"),
            _record("WeChat-work", "WeChat", "/Applications/WeChat.app"),
        ]
        view = _view(records)
        view._status = {
            name: AppUpdate("1.0", "2.0", needs_update=True) for name in
            ("WeChat-b2", "WeChat-work")
        }
        view._running = {"WeChat-work"}
        view._confirm = AsyncMock(return_value=True)
        view._info = AsyncMock()
        view._error = AsyncMock()
        view.refresh_sources = AsyncMock()

        await view._update_all(view._groups[0])

        view._confirm.assert_awaited_once()
        view.clone_service.update_clone.assert_awaited_once_with("WeChat-b2")
        # The skipped clone is named in the confirmation text.
        assert "WeChat-work" in view._confirm.await_args.args[1]
        view._info.assert_awaited_once()

    asyncio.run(_test())


def test_update_all_without_pending_updates_only_informs():
    async def _test():
        records = [_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")]
        view = _view(records)
        view._confirm = AsyncMock(return_value=True)
        view._info = AsyncMock()
        view.refresh_sources = AsyncMock()

        await view._update_all(view._groups[0])

        view._confirm.assert_not_awaited()
        view.clone_service.update_clone.assert_not_awaited()
        assert "WeChat" in view._info.await_args.args[1]

    asyncio.run(_test())


def test_update_all_refuses_without_source_app():
    async def _test():
        records = [_record("Ghost-1", "Ghost", "/Applications/Ghost.app")]
        view = _view(records)
        view._status = {"Ghost-1": AppUpdate("1.0", "2.0", needs_update=True)}
        view._groups[0].source_exists = False
        view._confirm = AsyncMock(return_value=True)
        view._info = AsyncMock()
        view.refresh_sources = AsyncMock()

        await view._update_all(view._groups[0])

        view._confirm.assert_not_awaited()
        view.clone_service.update_clone.assert_not_awaited()
        view._info.assert_awaited_once()

    asyncio.run(_test())


def test_show_loading_only_before_first_mount():
    view = SourceAppsView(clone_service=_service([]))
    view._show_loading()
    assert view._mounted == "loading"
    view._stop_loading()
    assert view._loading_indicator is None


def test_empty_and_no_results_states_have_actions():
    view = _view([])
    assert view._mounted == "empty"

    buttons = [
        child
        for child in view._empty_box.children
        if isinstance(child, toga.Button)
    ]
    assert buttons and buttons[0].text == t("sources_empty_action")

    view.on_search_changed("zzz")
    assert view._mounted == "empty"
    clear_buttons = [
        child
        for child in view._no_results_box.children
        if isinstance(child, toga.Button)
    ]
    assert clear_buttons and clear_buttons[0].text == t("sources_clear_filters")


def test_card_menu_does_not_replace_the_tile_menus():
    """The card's group menu must live on the card view only.

    Toga renders a card's children as sibling native views, so installing the
    group menu on every view would silently replace the per-clone menus of the
    tiles inside the card.
    """
    def _titles(menu) -> list[str]:
        return [menu.itemAtIndex_(index).title for index in range(menu.numberOfItems)]

    view = _view([_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")])
    card = _card(view)
    tile = card.tiles["WeChat-b2"]

    assert _titles(card._impl.native.menu)[0] == t("environment_btn_open_all")
    assert _titles(tile._impl.native.menu)[0] == t("environment_app_open")

    # Rebuilding the group menu (running state changed) keeps the tile menu.
    card.set_running({"WeChat-b2"})
    assert _titles(tile._impl.native.menu)[0] == t("environment_app_open")


def test_tile_menu_offers_detail_only_when_wired():
    async def _test():
        clone_view = MagicMock()
        clone_view.on_detail_clone = AsyncMock()
        app = MagicMock()
        app.clone_view = clone_view
        view = _view(
            [_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")], app=app
        )
        tile = _card(view).tiles["WeChat-b2"]

        assert "detail" in [entry.key for entry in tile._menu_entries()]

        await view._detail(view._records[0])
        clone_view.on_detail_clone.assert_awaited_once()

    asyncio.run(_test())

    # Tiles without a detail callback (the environment page) keep the old menu.
    plain = AppTile(label="ZCode", clone_name="ZCode-phone1")
    assert "detail" not in [entry.key for entry in plain._menu_entries()]


def test_group_helper():
    group = _SourceGroup("/Applications/WeChat.app", "WeChat")
    assert group.clone_names() == []
    assert group.source_exists is True
    assert group.last_opened() == 0.0


def test_last_opened_patch_does_not_rebuild_card():
    records = [_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")]
    view = _view(records)
    card = _card(view)

    view._apply_last_opened("WeChat-b2", "2026-11-15T09:00:00")
    assert _card(view) is card
    assert view._record_by_name["WeChat-b2"].last_opened_at == "2026-11-15T09:00:00"


def test_refresh_reuses_cards_when_nothing_changed():
    async def _test():
        records = [_record("WeChat-b2", "WeChat", "/Applications/WeChat.app")]
        view = _view(records)
        card_before = _card(view)
        # Keep this deterministic: the real probe depends on whether the source
        # app is installed on the build machine, and a changed existence flag
        # legitimately rebuilds the card.
        view._load_status_and_paths = lambda: ({}, {})

        await view.refresh_sources()

        # Same clone set, same cards: a refresh patches instead of remounting.
        assert _card(view) is card_before
        assert view._rendered is True

    asyncio.run(_test())
