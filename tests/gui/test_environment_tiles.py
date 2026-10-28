"""Tests for the environment app tiles and their action plumbing."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import toga

from twinspace.core.i18n import t
from twinspace.core.state import CloneRecord, StateManager
from twinspace.gui.components.app_tile import (
    TILE_COLUMNS_MAX,
    TILE_COLUMNS_MIN,
    AppTile,
    compute_tile_columns,
)
from twinspace.gui.services.environment_service import EnvironmentService
from twinspace.gui.views.environment_list import EnvironmentListView


def _make_tile(**kwargs) -> AppTile:
    defaults = {
        "label": "ZCode",
        "clone_name": "ZCode-phone1",
        "running": False,
        "tooltip": "ZCode · ZCode-phone1",
    }
    defaults.update(kwargs)
    return AppTile(**defaults)


def _collect_tiles(widget) -> list[AppTile]:
    tiles = [widget] if isinstance(widget, AppTile) else []
    for child in getattr(widget, "children", []):
        tiles.extend(_collect_tiles(child))
    return tiles


def _environment_state(tmp_path, count: int = 3) -> StateManager:
    state = StateManager(state_file=tmp_path / "clones.yaml")
    apps = (
        ("Chrome-phone1", "Google Chrome", "com.google.Chrome", "soft_clone"),
        ("ZCode-phone1", "ZCode", "dev.zcode.app", "hard_clone"),
        ("WorkBuddy-phone1", "WorkBuddy", "com.workbuddy.app", "hard_clone"),
    )
    for name, source, bundle, strategy in apps[:count]:
        state.add(
            CloneRecord(
                clone_name=name,
                source_app=source,
                source_path=f"/Applications/{source}.app",
                bundle_id=bundle,
                strategy=strategy,
                dest_path=str(tmp_path / f"{name}.app"),
                data_dir=str(tmp_path / "env" / name),
                created_at="2026-10-26T00:00:00Z",
                env_group="phone1",
                env_dir=str(tmp_path / "env"),
            )
        )
    return state


def test_compute_tile_columns_clamps_to_supported_range():
    assert compute_tile_columns(200) == TILE_COLUMNS_MIN
    assert compute_tile_columns(1600) == TILE_COLUMNS_MAX

    widths = [compute_tile_columns(width) for width in (320, 500, 700, 900, 1100, 1400)]
    assert widths == sorted(widths)
    assert all(TILE_COLUMNS_MIN <= value <= TILE_COLUMNS_MAX for value in widths)


def test_double_click_opens_only_when_app_is_not_running(toga_app):
    calls: list[str] = []
    idle = _make_tile(
        on_open=lambda: calls.append("open"),
        on_close=lambda: calls.append("close"),
    )
    idle._handle_double_click()
    assert calls == ["open"]

    running = _make_tile(running=True, on_open=lambda: calls.append("open"))
    running._handle_double_click()
    assert calls == ["open"]


def test_tile_menu_dispatches_actions_and_respects_running_state(toga_app):
    calls: list[str] = []
    callbacks = {
        "on_open": lambda: calls.append("open"),
        "on_close": lambda: calls.append("close"),
        "on_edit": lambda: calls.append("edit"),
        "on_reveal": lambda: calls.append("reveal"),
        "on_update": lambda: calls.append("update"),
    }
    idle = _make_tile(**callbacks)

    idle._handle_menu("close")
    assert calls == []
    for key in ("open", "update", "edit", "reveal"):
        idle._handle_menu(key)
    assert calls == ["open", "update", "edit", "reveal"]

    calls.clear()
    running = _make_tile(running=True, **callbacks)
    running._handle_menu("open")
    assert calls == []
    running._handle_menu("close")
    assert calls == ["close"]


def test_tile_menu_entries_toggle_open_close_and_update(toga_app):
    idle_entries = {entry.key: entry for entry in _make_tile()._menu_entries()}
    assert idle_entries["open"].enabled is True
    assert idle_entries["close"].enabled is False
    assert idle_entries["update"].enabled is True

    running_entries = {entry.key: entry for entry in _make_tile(running=True)._menu_entries()}
    assert running_entries["open"].enabled is False
    assert running_entries["close"].enabled is True
    assert running_entries["update"].enabled is False


def test_environment_view_renders_one_tile_per_app(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._running_clones = {"ZCode-phone1"}
    view._render()

    tiles = {tile.clone_name: tile for tile in _collect_tiles(view.list_box)}
    assert set(tiles) == {"Chrome-phone1", "ZCode-phone1", "WorkBuddy-phone1"}
    assert tiles["ZCode-phone1"].running is True
    assert tiles["Chrome-phone1"].running is False
    assert tiles["Chrome-phone1"].label_text == "Google Chrome"


def test_environment_menu_disables_mutating_actions_while_running(toga_app, tmp_path):
    view = EnvironmentListView(
        environment_service=EnvironmentService(
            state_manager=StateManager(state_file=tmp_path / "clones.yaml")
        )
    )
    running_entries = {entry.key: entry for entry in view._env_menu_entries(True)}
    assert running_entries["open_all"].enabled is True
    assert running_entries["update_all"].enabled is False
    assert running_entries["backup"].enabled is False
    assert running_entries["remove"].enabled is False

    idle_entries = {entry.key: entry for entry in view._env_menu_entries(False)}
    assert idle_entries["update_all"].enabled is True
    assert idle_entries["remove"].enabled is True


def test_window_resize_reflows_tiles(toga_app, tmp_path):
    view = EnvironmentListView(
        environment_service=EnvironmentService(state_manager=_environment_state(tmp_path))
    )
    view._environments = view.environment_service.list_environments()
    view._render()
    assert len(_collect_tiles(view.list_box)) == 3

    view._content_width = 500.0
    view.on_window_resize(1300)
    assert view._content_width == 1012
    assert len(_collect_tiles(view.list_box)) == 3


def test_update_app_rebuilds_only_the_selected_app(toga_app, tmp_path):
    service = EnvironmentService(state_manager=StateManager(state_file=tmp_path / "clones.yaml"))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._on_environment_changed = AsyncMock()

    asyncio.run(view._update_app("phone1", "zcode", "ZCode-phone1"))

    service.update_environment.assert_awaited_once_with("phone1", app_keys=["zcode"])
    view._on_environment_changed.assert_awaited_once()


def test_update_app_is_skipped_while_running(toga_app, tmp_path):
    service = EnvironmentService(state_manager=StateManager(state_file=tmp_path / "clones.yaml"))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view._running_clones = {"ZCode-phone1"}

    asyncio.run(view._update_app("phone1", "zcode", "ZCode-phone1"))

    service.update_environment.assert_not_awaited()


def test_environment_card_shows_device_identity(toga_app, tmp_path):
    from twinspace.core.device_identity import identity_for_environment

    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()

    texts = []
    stack = [view.list_box]
    while stack:
        widget = stack.pop()
        if hasattr(widget, "text"):
            texts.append(str(widget.text))
        stack.extend(getattr(widget, "children", []))

    identity = identity_for_environment("phone1")
    assert any(identity.platform_uuid[:8] in text for text in texts)
    assert any(identity.hostname in text for text in texts)


def _has_activity_indicator(widget) -> bool:
    if isinstance(widget, toga.ActivityIndicator):
        return True
    return any(
        _has_activity_indicator(child)
        for child in getattr(widget, "children", [])
    )


def test_refresh_reuses_cards_when_nothing_changed(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.running_clones = lambda name=None: set()
    view = EnvironmentListView(environment_service=service)

    asyncio.run(view.refresh_environments())
    cards = dict(view._cards)

    asyncio.run(view.refresh_environments())

    assert view._cards["phone1"] is cards["phone1"]
    assert view._cards["phone1"].card.parent is view.list_box
    assert len(view.list_box.children) == 1


def test_refresh_never_blanks_the_page_after_first_paint(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.running_clones = lambda name=None: set()
    view = EnvironmentListView(environment_service=service)

    asyncio.run(view.refresh_environments())
    tiles = dict(view._cards["phone1"].tiles)

    asyncio.run(view.refresh_environments())

    assert not _has_activity_indicator(view.list_box)
    assert view._cards["phone1"].tiles == tiles


def test_opening_an_app_updates_the_tile_in_place(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.running_clones = lambda name=None: set()
    view = EnvironmentListView(environment_service=service)
    asyncio.run(view.refresh_environments())

    card = view._cards["phone1"]
    tile = card.tiles["ZCode-phone1"]
    assert tile.running is False

    view._mark_running("phone1", "zcode", True)

    assert card.tiles["ZCode-phone1"] is tile
    assert tile.running is True
    assert tile.status_label.text != ""
    assert card.status_text.text == t("environment_running")
    assert card.update_button.enabled is False


def test_running_state_uses_the_workspace_snapshot(toga_app, tmp_path):
    state = _environment_state(tmp_path)
    service = EnvironmentService(state_manager=state)
    view = EnvironmentListView(environment_service=service)
    record = state.load()[0]
    ps_calls = []

    class _SnapshotMonitor:
        available = True

        def running_paths(self):
            return {str(record.dest_path)}

    view._monitor = _SnapshotMonitor()
    service.running_clones = lambda name=None: ps_calls.append(name) or set()

    asyncio.run(view.refresh_environments())

    assert ps_calls == []
    assert record.clone_name in view._running_clones
    assert view._cards["phone1"].tiles[record.clone_name].running is True


class _IdleMonitor:
    """Monitor double that reports no running bundles."""

    available = True

    def running_paths(self):
        return set()


def test_launch_event_repaints_only_the_affected_tile(toga_app, tmp_path):
    state = _environment_state(tmp_path)
    service = EnvironmentService(state_manager=state)
    view = EnvironmentListView(environment_service=service)
    view._monitor = _IdleMonitor()
    service.running_clones = lambda name=None: set()
    asyncio.run(view.refresh_environments())

    records = {record.clone_name: record for record in state.load()}
    card = view._cards["phone1"]
    target = card.tiles["ZCode-phone1"]
    untouched = card.tiles["Chrome-phone1"]
    assert target.running is False

    view.handle_app_state_change(str(records["ZCode-phone1"].dest_path), True)

    assert target.running is True
    assert untouched.running is False
    assert card.running is True
    assert "ZCode-phone1" in view._running_clones

    view.handle_app_state_change(str(records["ZCode-phone1"].dest_path), False)

    assert target.running is False
    assert card.running is False
    assert "ZCode-phone1" not in view._running_clones


def test_unknown_bundle_events_are_ignored(toga_app, tmp_path):
    state = _environment_state(tmp_path)
    service = EnvironmentService(state_manager=state)
    view = EnvironmentListView(environment_service=service)
    view._monitor = _IdleMonitor()
    service.running_clones = lambda name=None: set()
    asyncio.run(view.refresh_environments())

    view.handle_app_state_change("/Applications/Some Other.app", True)

    assert view._running_clones == set()


def test_tile_selection_is_exclusive(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()

    tiles = _collect_tiles(view.list_box)
    view._select_tile(tiles[0])
    assert tiles[0].selected is True
    assert all(tile.selected is False for tile in tiles[1:])

    view._select_tile(tiles[1])
    assert tiles[0].selected is False
    assert tiles[1].selected is True
    assert view._selected_clone == tiles[1].clone_name


def test_tile_selection_survives_a_re_render(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()

    tiles = _collect_tiles(view.list_box)
    view._select_tile(tiles[2])
    selected_name = tiles[2].clone_name

    view._render()

    redrawn = {tile.clone_name: tile for tile in _collect_tiles(view.list_box)}
    assert redrawn[selected_name].selected is True
    assert sum(1 for tile in redrawn.values() if tile.selected) == 1


def test_environment_refresh_shows_and_clears_loading_state(toga_app, tmp_path):
    service = EnvironmentService(
        state_manager=StateManager(state_file=tmp_path / "clones.yaml")
    )
    view = EnvironmentListView(environment_service=service)
    view._show_loading()

    assert _has_activity_indicator(view.list_box)

    asyncio.run(view.refresh_environments())

    assert view._loading is False
    assert not _has_activity_indicator(view.list_box)


def test_tile_renders_last_opened_under_the_app_name(toga_app):
    from twinspace.gui.components import app_tile as module

    tile = _make_tile()
    assert tile.last_opened_label.text == ""
    assert tile.last_opened_label.style.margin_left == (
        module.TILE_WIDTH - module.PILL_WIDTH
    ) // 2

    stamp = datetime.now().astimezone().replace(hour=5, minute=30).isoformat()
    tile.set_last_opened(stamp)

    assert "5:30" in tile.last_opened_label.text
    # The caption sits between the name pill and the running status row.
    assert tile.children.index(tile.pill) < tile.children.index(tile.last_opened_label)
    assert tile.children.index(tile.last_opened_label) < tile.children.index(tile.status_label)


def test_opening_an_app_records_and_paints_last_opened(toga_app, tmp_path):
    state = _environment_state(tmp_path)
    service = EnvironmentService(state_manager=state)
    service.running_clones = lambda name=None: set()
    view = EnvironmentListView(environment_service=service)
    asyncio.run(view.refresh_environments())

    asyncio.run(view._record_opened(["ZCode-phone1"]))

    stored = {record.clone_name: record for record in state.load()}
    assert stored["ZCode-phone1"].last_opened_at
    tile = view._cards["phone1"].tiles["ZCode-phone1"]
    assert tile.last_opened_label.text


def test_launch_event_repaints_last_opened_on_the_tile(toga_app, tmp_path):
    state = _environment_state(tmp_path)
    service = EnvironmentService(state_manager=state)
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()

    stamp = datetime.now().astimezone().replace(hour=8, minute=30).isoformat()
    view.handle_clone_opened("Chrome-phone1", stamp)

    assert view._cards["phone1"].tiles["Chrome-phone1"].last_opened_label.text
    records = {record.clone_name: record for record in view._environments[0].records}
    assert records["Chrome-phone1"].last_opened_at == stamp
