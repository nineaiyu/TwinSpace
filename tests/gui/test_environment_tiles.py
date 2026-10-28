"""Tests for the environment app tiles and their action plumbing."""

import asyncio
from datetime import datetime
from unittest.mock import ANY, AsyncMock, MagicMock

import toga

from twinspace.core.app_version import AppUpdate
from twinspace.core.i18n import t
from twinspace.core.state import CloneRecord, StateManager
from twinspace.gui import cocoa_events
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
    # Updating/rebuilding skip the running apps one by one, so they stay enabled.
    assert running_entries["update_all"].enabled is True
    assert running_entries["rebuild_all"].enabled is True
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
    view._confirm = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._on_environment_changed = AsyncMock()

    asyncio.run(view._update_app("phone1", "zcode", "ZCode-phone1"))

    service.update_environment.assert_awaited_once_with(
        "phone1", app_keys=["zcode"], on_progress=ANY
    )
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


def test_tile_click_forwards_the_selection_intent(toga_app):
    seen: list[tuple[str, str]] = []
    tile = _make_tile(on_select=lambda t, intent: seen.append((t.clone_name, intent)))

    tile._handle_click()

    assert seen == [("ZCode-phone1", cocoa_events.selection_intent())]


def test_command_click_toggles_and_shift_click_extends_the_selection(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()
    tiles = {tile.clone_name: tile for tile in _collect_tiles(view.list_box)}

    view._select_tile(tiles["Chrome-phone1"])
    view._select_tile(tiles["ZCode-phone1"], cocoa_events.SELECT_TOGGLE)
    assert view._selected_clones == {"Chrome-phone1", "ZCode-phone1"}
    assert tiles["Chrome-phone1"].selected is True
    assert tiles["ZCode-phone1"].selected is True

    # ⌘-click on a selected tile removes it again.
    view._select_tile(tiles["ZCode-phone1"], cocoa_events.SELECT_TOGGLE)
    assert view._selected_clones == {"Chrome-phone1"}
    assert tiles["ZCode-phone1"].selected is False

    # ⇧-click extends from the last clicked tile to the target.
    view._select_tile(tiles["WorkBuddy-phone1"], cocoa_events.SELECT_EXTEND)
    assert view._selected_clones == {"ZCode-phone1", "WorkBuddy-phone1"}
    assert tiles["Chrome-phone1"].selected is False


def test_tiles_are_selected_without_a_batch_bar(toga_app, tmp_path):
    """The environment page has no top batch bar; actions live in the menu."""
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()
    tiles = _collect_tiles(view.list_box)

    assert not hasattr(view, "selection_bar")

    view._select_tile(tiles[0])
    view._select_tile(tiles[1], cocoa_events.SELECT_TOGGLE)
    assert view._selected_clones == {tiles[0].clone_name, tiles[1].clone_name}

    view.clear_selection()
    assert view._selected_clones == set()
    assert all(tile.selected is False for tile in tiles)


def test_tile_and_environment_show_pending_updates(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._update_status = {
        "ZCode-phone1": AppUpdate(current="1.0", latest="2.0", needs_update=True),
        "Chrome-phone1": AppUpdate(current="9.9", latest="9.9", needs_update=False),
    }
    view._environments = service.list_environments()
    view._render()

    card = view._cards["phone1"]
    assert card.tiles["ZCode-phone1"].update_available is True
    assert "2.0" in card.tiles["ZCode-phone1"].update_label.text
    assert card.tiles["Chrome-phone1"].update_available is False
    assert card.tiles["Chrome-phone1"].update_label.text == ""
    assert card.update_badge.text == t("environment_update_badge", count=1)


def test_batch_open_and_close_only_touch_selected_apps(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    calls: list[tuple[str, str, list[str]]] = []
    service.open_environment = (
        lambda name, keys=None: calls.append(("open", name, list(keys or []))) or []
    )
    service.quit_environment = (
        lambda name, keys=None: calls.append(("quit", name, list(keys or []))) or []
    )
    view._environments = service.list_environments()
    view._running_clones = {"ZCode-phone1"}
    view._render()
    view._record_opened = AsyncMock()
    view._schedule = lambda awaitable: awaitable.close()

    tiles = view._cards["phone1"].tiles
    view._select_tile(tiles["Chrome-phone1"])
    view._select_tile(tiles["ZCode-phone1"], cocoa_events.SELECT_TOGGLE)

    asyncio.run(view._batch_open_selected())
    assert tiles["Chrome-phone1"].running is True

    # Forget the optimistic state so the process table (pre-seeded above) wins.
    view._optimistic.clear()
    asyncio.run(view._batch_close_selected())

    # The running app is skipped when opening, the idle one when closing.
    assert calls == [
        ("open", "phone1", ["chrome"]),
        ("quit", "phone1", ["zcode"]),
    ]
    assert tiles["ZCode-phone1"].running is False


def test_batch_update_rebuilds_selected_apps_only(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view._confirm = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view.app_instance.main_window.error_dialog = AsyncMock()
    view._on_environment_changed = AsyncMock()
    view._environments = service.list_environments()
    view._running_clones = {"WorkBuddy-phone1"}
    view._update_status = {
        "Chrome-phone1": AppUpdate("1.0", "2.0", True),
        "ZCode-phone1": AppUpdate("1.0", "2.0", True),
        "WorkBuddy-phone1": AppUpdate("1.0", "2.0", True),
    }
    view._render()

    tiles = view._cards["phone1"].tiles
    for name in ("Chrome-phone1", "ZCode-phone1", "WorkBuddy-phone1"):
        view._select_tile(tiles[name], cocoa_events.SELECT_TOGGLE)

    asyncio.run(view._batch_update_selected())

    # The running app is skipped, and only outdated apps are updated.
    service.update_environment.assert_awaited_once_with(
        "phone1", app_keys=["chrome", "zcode"], on_progress=ANY
    )
    view._on_environment_changed.assert_awaited_once()


def test_batch_update_skips_apps_that_are_already_current(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view._confirm = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._environments = service.list_environments()
    view._update_status = {
        "Chrome-phone1": AppUpdate("2.0", "2.0", False),
        "ZCode-phone1": AppUpdate("2.0", "2.0", False),
    }
    view._render()

    tiles = view._cards["phone1"].tiles
    for name in ("Chrome-phone1", "ZCode-phone1"):
        view._select_tile(tiles[name], cocoa_events.SELECT_TOGGLE)

    asyncio.run(view._batch_update_selected())

    service.update_environment.assert_not_awaited()
    view.app_instance.main_window.info_dialog.assert_awaited_once_with(
        t("environment_done_title"), t("environment_update_none_selected")
    )


def test_update_all_only_touches_outdated_apps(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view._confirm = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._on_environment_changed = AsyncMock()
    view._environments = service.list_environments()
    view._update_status = {
        "Chrome-phone1": AppUpdate("1.0", "2.0", True),
        "ZCode-phone1": AppUpdate("2.0", "2.0", False),
        "WorkBuddy-phone1": AppUpdate("2.0", "2.0", False),
    }

    asyncio.run(view._update_all("phone1"))

    service.update_environment.assert_awaited_once_with(
        "phone1", app_keys=["chrome"], on_progress=ANY
    )


def test_update_all_reports_when_everything_is_current(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._environments = service.list_environments()
    view._update_status = {
        "Chrome-phone1": AppUpdate("2.0", "2.0", False),
        "ZCode-phone1": AppUpdate("2.0", "2.0", False),
    }

    asyncio.run(view._update_all("phone1"))

    service.update_environment.assert_not_awaited()
    view.app_instance.main_window.info_dialog.assert_awaited_once_with(
        t("environment_done_title"), t("environment_update_all_none", name="phone1")
    )


def test_rebuild_all_rebuilds_every_app_regardless_of_version(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view._confirm = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._on_environment_changed = AsyncMock()
    view._environments = service.list_environments()
    view._update_status = {
        "Chrome-phone1": AppUpdate("2.0", "2.0", False),
        "ZCode-phone1": AppUpdate("2.0", "2.0", False),
    }

    asyncio.run(view._rebuild_all("phone1"))

    # No app_keys: the whole environment is rebuilt.
    service.update_environment.assert_awaited_once_with("phone1", on_progress=ANY)


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


class _FakeMarquee:
    """Stands in for the Cocoa overlay; records the rectangles it was given."""

    instances: list["_FakeMarquee"] = []

    def __init__(self, owner):
        self.rects: list[tuple[float, float, float, float]] = []
        self.closed = False
        _FakeMarquee.instances.append(self)

    def set_rect(self, rect) -> None:
        self.rects.append(rect)

    def close(self) -> None:
        self.closed = True


def _view_with_tile_frames(tmp_path, monkeypatch, frames):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view._environments = service.list_environments()
    view._render()
    tiles = view._ordered_tiles()
    coordinates = {
        tile.clone_name: frames[index] for index, tile in enumerate(tiles)
    }
    monkeypatch.setattr(
        cocoa_events,
        "window_frame",
        lambda widget: coordinates.get(
            getattr(widget, "clone_name", ""), (0.0, 0.0, 2000.0, 2000.0)
        ),
    )
    monkeypatch.setattr(cocoa_events, "Marquee", _FakeMarquee)
    return view, tiles


def test_marquee_selects_every_tile_inside_the_box(toga_app, tmp_path, monkeypatch):
    _FakeMarquee.instances = []
    frames = [(0.0, 100.0, 100.0, 100.0), (120.0, 100.0, 100.0, 100.0), (240.0, 100.0, 100.0, 100.0)]
    view, tiles = _view_with_tile_frames(tmp_path, monkeypatch, frames)

    view._handle_tile_drag(cocoa_events.GESTURE_BEGAN, (90.0, 150.0))
    view._handle_tile_drag(cocoa_events.GESTURE_CHANGED, (230.0, 250.0))
    view._handle_tile_drag(cocoa_events.GESTURE_ENDED, (230.0, 250.0))

    assert view._selected_clones == {tiles[0].clone_name, tiles[1].clone_name}
    assert tiles[0].selected is True
    assert tiles[2].selected is False
    # The rubber band is drawn while dragging and removed on mouse-up.
    assert _FakeMarquee.instances and _FakeMarquee.instances[0].closed is True
    assert view._click_suppressed is True


def test_marquee_ignores_a_plain_click(toga_app, tmp_path, monkeypatch):
    _FakeMarquee.instances = []
    frames = [(0.0, 100.0, 100.0, 100.0), (120.0, 100.0, 100.0, 100.0), (240.0, 100.0, 100.0, 100.0)]
    view, _tiles = _view_with_tile_frames(tmp_path, monkeypatch, frames)

    view._handle_tile_drag(cocoa_events.GESTURE_BEGAN, (90.0, 150.0))
    view._handle_tile_drag(cocoa_events.GESTURE_ENDED, (90.0, 150.0))

    # A click keeps the click recognizer in charge: nothing selected, no suppression.
    assert view._selected_clones == set()
    assert view._click_suppressed is False


def test_marquee_does_not_start_on_a_button(toga_app, tmp_path, monkeypatch):
    _FakeMarquee.instances = []
    frames = [(0.0, 100.0, 100.0, 100.0), (120.0, 100.0, 100.0, 100.0), (240.0, 100.0, 100.0, 100.0)]
    view, _tiles = _view_with_tile_frames(tmp_path, monkeypatch, frames)
    monkeypatch.setattr(cocoa_events, "hit_test_view", lambda owner, location: object())
    monkeypatch.setattr(cocoa_events, "is_control_view", lambda view: True)

    view._handle_tile_drag(cocoa_events.GESTURE_BEGAN, (90.0, 150.0))
    view._handle_tile_drag(cocoa_events.GESTURE_CHANGED, (300.0, 250.0))

    assert view._selected_clones == set()
    assert _FakeMarquee.instances == []


def test_marquee_can_start_on_empty_space(toga_app, tmp_path, monkeypatch):
    """Pressing in the blank area of the page must still start a rubber band."""
    _FakeMarquee.instances = []
    frames = [(0.0, 100.0, 100.0, 100.0), (120.0, 100.0, 100.0, 100.0), (240.0, 100.0, 100.0, 100.0)]
    view, tiles = _view_with_tile_frames(tmp_path, monkeypatch, frames)

    # Start well below/right of the tiles, then sweep back over all three.
    view._handle_tile_drag(cocoa_events.GESTURE_BEGAN, (500.0, 20.0))
    view._handle_tile_drag(cocoa_events.GESTURE_CHANGED, (20.0, 260.0))

    assert view._selected_clones == {tile.clone_name for tile in tiles}


def test_multi_selection_swaps_the_tile_menu_for_batch_actions(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._update_status = {"Chrome-phone1": AppUpdate("1.0", "2.0", True)}
    view._render()
    tiles = view._cards["phone1"].tiles

    view._select_tile(tiles["Chrome-phone1"], cocoa_events.SELECT_TOGGLE)
    assert tiles["Chrome-phone1"]._menu_entries()[0].key == "open"

    view._select_tile(tiles["ZCode-phone1"], cocoa_events.SELECT_TOGGLE)
    keys = [entry.key for entry in tiles["Chrome-phone1"]._menu_entries()]
    assert keys == [
        "batch_open",
        "batch_close",
        "batch_update",
        "batch_rebuild",
        "batch_clear",
    ]
    # A tile outside the selection keeps its regular menu.
    assert tiles["WorkBuddy-phone1"]._menu_entries()[0].key == "open"

    view.clear_selection()
    assert tiles["Chrome-phone1"]._menu_entries()[0].key == "open"


def test_clicking_empty_space_clears_the_selection(toga_app, tmp_path, monkeypatch):
    _FakeMarquee.instances = []
    frames = [(0.0, 100.0, 100.0, 100.0), (120.0, 100.0, 100.0, 100.0), (240.0, 100.0, 100.0, 100.0)]
    view, tiles = _view_with_tile_frames(tmp_path, monkeypatch, frames)

    view._select_tile(tiles[0])
    view._select_tile(tiles[1], cocoa_events.SELECT_TOGGLE)
    assert view._selected_clones == {tiles[0].clone_name, tiles[1].clone_name}

    # Press (and release) on empty space below the tiles.
    view._handle_tile_drag(cocoa_events.GESTURE_BEGAN, (600.0, 20.0))
    view._handle_tile_drag(cocoa_events.GESTURE_ENDED, (600.0, 20.0))

    assert view._selected_clones == set()
    assert all(tile.selected is False for tile in tiles)


def test_shift_click_on_empty_space_keeps_the_selection(toga_app, tmp_path, monkeypatch):
    _FakeMarquee.instances = []
    frames = [(0.0, 100.0, 100.0, 100.0), (120.0, 100.0, 100.0, 100.0), (240.0, 100.0, 100.0, 100.0)]
    view, tiles = _view_with_tile_frames(tmp_path, monkeypatch, frames)

    view._select_tile(tiles[0])
    monkeypatch.setattr(
        cocoa_events, "selection_intent", lambda: cocoa_events.SELECT_EXTEND
    )

    view._handle_tile_drag(cocoa_events.GESTURE_BEGAN, (600.0, 20.0))
    view._handle_tile_drag(cocoa_events.GESTURE_ENDED, (600.0, 20.0))

    assert view._selected_clones == {tiles[0].clone_name}


def test_update_all_lists_targets_and_skips_running_apps(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view._confirm = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._on_environment_changed = AsyncMock()
    view._environments = service.list_environments()
    view._running_clones = {"WorkBuddy-phone1"}
    view._update_status = {
        "Chrome-phone1": AppUpdate("1.0", "2.0", True),
        "ZCode-phone1": AppUpdate("1.0", "2.0", True),
        "WorkBuddy-phone1": AppUpdate("1.0", "2.0", True),
    }

    asyncio.run(view._update_all("phone1"))

    service.update_environment.assert_awaited_once_with(
        "phone1", app_keys=["chrome", "zcode"], on_progress=ANY
    )
    message = view._confirm.await_args.args[1]
    assert "Chrome" in message and "ZCode" in message
    # The running app is reported as skipped instead of aborting the update.
    assert "WorkBuddy" in message


def test_update_all_reports_when_everything_runs(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view._confirm = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._environments = service.list_environments()
    view._running_clones = {"Chrome-phone1", "ZCode-phone1", "WorkBuddy-phone1"}
    view._update_status = {"Chrome-phone1": AppUpdate("1.0", "2.0", True)}

    asyncio.run(view._update_all("phone1"))

    service.update_environment.assert_not_awaited()
    view.app_instance.main_window.info_dialog.assert_awaited_once_with(
        t("environment_done_title"), t("environment_update_all_running", name="phone1")
    )


def test_rebuild_all_skips_running_apps(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view._confirm = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._on_environment_changed = AsyncMock()
    view._environments = service.list_environments()
    view._running_clones = {"ZCode-phone1"}

    asyncio.run(view._rebuild_all("phone1"))

    # ZCode is running and skipped; WorkBuddy has no app key, so only Chrome.
    service.update_environment.assert_awaited_once_with(
        "phone1", app_keys=["chrome"], on_progress=ANY
    )
    message = view._confirm.await_args.args[1]
    assert "Chrome" in message
    assert "ZCode" in message  # listed as skipped


def test_batch_rebuild_rebuilds_selected_apps_and_skips_running(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view._confirm = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._on_environment_changed = AsyncMock()
    view._environments = service.list_environments()
    view._running_clones = {"WorkBuddy-phone1"}
    # No update status at all: a rebuild must not care about versions.
    view._render()

    tiles = view._cards["phone1"].tiles
    for name in ("Chrome-phone1", "ZCode-phone1", "WorkBuddy-phone1"):
        view._select_tile(tiles[name], cocoa_events.SELECT_TOGGLE)

    asyncio.run(view._batch_rebuild_selected())

    service.update_environment.assert_awaited_once_with(
        "phone1", app_keys=["chrome", "zcode"], on_progress=ANY
    )
    message = view._confirm.await_args.args[1]
    assert "WorkBuddy" in message  # skipped section
    view.app_instance.main_window.info_dialog.assert_awaited_once_with(
        t("environment_done_title"), t("environment_batch_rebuild_done", count=2)
    )


def test_batch_rebuild_reports_when_every_selected_app_runs(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view._confirm = AsyncMock(return_value=True)
    view.app_instance.main_window.info_dialog = AsyncMock()
    view._environments = service.list_environments()
    view._running_clones = {"Chrome-phone1", "ZCode-phone1"}
    view._render()

    tiles = view._cards["phone1"].tiles
    for name in ("Chrome-phone1", "ZCode-phone1"):
        view._select_tile(tiles[name], cocoa_events.SELECT_TOGGLE)

    asyncio.run(view._batch_rebuild_selected())

    service.update_environment.assert_not_awaited()
    view.app_instance.main_window.info_dialog.assert_awaited_once_with(
        t("environment_done_title"), t("environment_batch_update_all_running")
    )


def test_command_a_selects_every_tile(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()
    tiles = view._ordered_tiles()

    assert view._handle_key("a", cocoa_events.COMMAND_MODIFIER) is True
    assert view._selected_clones == {tile.clone_name for tile in tiles}
    assert all(tile.selected for tile in tiles)


def test_escape_clears_the_selection(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()
    tiles = view._ordered_tiles()

    view._select_tile(tiles[0])
    assert view._handle_key("\x1b", 0) is True
    assert view._selected_clones == set()


def test_escape_cancels_a_running_marquee_and_restores_the_selection(
    toga_app, tmp_path, monkeypatch
):
    _FakeMarquee.instances = []
    frames = [(0.0, 100.0, 100.0, 100.0), (120.0, 100.0, 100.0, 100.0), (240.0, 100.0, 100.0, 100.0)]
    view, tiles = _view_with_tile_frames(tmp_path, monkeypatch, frames)
    view._select_tile(tiles[0])
    monkeypatch.setattr(
        cocoa_events, "selection_intent", lambda: cocoa_events.SELECT_EXTEND
    )

    view._handle_tile_drag(cocoa_events.GESTURE_BEGAN, (90.0, 150.0))
    view._handle_tile_drag(cocoa_events.GESTURE_CHANGED, (300.0, 250.0))
    assert len(view._selected_clones) > 1

    assert view._handle_key("\x1b", 0) is True
    assert view._selected_clones == {tiles[0].clone_name}
    assert view._drag_active is False
    assert _FakeMarquee.instances[0].closed is True


def test_plain_keys_are_left_to_the_app(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()

    assert view._handle_key("a", 0) is False
    assert view._handle_key("\x1b", 0) is False


def test_a_second_update_is_ignored_while_one_runs(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    service.update_environment = AsyncMock(return_value=[])
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()
    view.app_instance.main_window.confirm_dialog = AsyncMock(return_value=True)
    view._confirm = AsyncMock(return_value=True)
    view._environments = service.list_environments()
    view._update_status = {"Chrome-phone1": AppUpdate("1.0", "2.0", True)}
    view._busy_operation = "update"

    asyncio.run(view._update_all("phone1"))

    service.update_environment.assert_not_awaited()
    view.app_instance.main_window.confirm_dialog.assert_not_awaited()


def test_progress_callback_paints_the_card_and_gets_restored(toga_app, tmp_path):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()
    card = view._cards["phone1"]
    app = service.app_for_key("zcode")

    view._progress_reporter("phone1", "environment_progress_updating")(
        2, 3, app, "updating"
    )

    assert card.status_text.text == t(
        "environment_progress_updating", current=2, total=3, app=app.label
    )

    # The next repaint restores the running / idle label.
    view._update_card(card, view._environments[0])
    assert card.status_text.text in (
        t("environment_running"),
        t("environment_not_running"),
    )


def test_autoscroll_scrolls_while_the_pointer_sits_near_an_edge(
    toga_app, tmp_path, monkeypatch
):
    _FakeMarquee.instances = []
    frames = [(0.0, 100.0, 100.0, 100.0), (120.0, 100.0, 100.0, 100.0), (240.0, 100.0, 100.0, 100.0)]
    view, _tiles = _view_with_tile_frames(tmp_path, monkeypatch, frames)
    viewport = (0.0, 0.0, 800.0, 400.0)
    monkeypatch.setattr(cocoa_events, "window_frame", lambda widget: viewport)
    scrolled: list[float] = []
    monkeypatch.setattr(
        cocoa_events,
        "scroll_content",
        lambda widget, amount: scrolled.append(amount) or True,
    )

    view._drag_active = True
    view._marquee_origin = (10.0, 10.0)
    view._marquee_location = (10.0, 395.0)  # 5pt from the top edge
    view._autoscroll_tick()
    assert scrolled and scrolled[0] > 0

    view._marquee_location = (10.0, 5.0)  # 5pt from the bottom edge
    view._autoscroll_tick()
    assert scrolled[-1] < 0

    view._marquee_location = (10.0, 200.0)  # middle: no scrolling
    before = len(scrolled)
    view._autoscroll_tick()
    assert len(scrolled) == before


def test_blank_area_menu_offers_select_all_and_clear(toga_app, tmp_path, monkeypatch):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()
    monkeypatch.setattr(cocoa_events, "window_frame", lambda widget: (0.0, 0.0, 900.0, 700.0))
    monkeypatch.setattr(cocoa_events, "hit_test_view", lambda owner, location: None)
    monkeypatch.setattr(view, "_tile_at_location", lambda location: None)

    entries = view._blank_menu_entries_at((10.0, 10.0))
    assert [entry.key for entry in entries] == ["select_all", "clear_selection"]
    assert entries[1].enabled is False

    view._select_tile(view._ordered_tiles()[0])
    entries = view._blank_menu_entries_at((10.0, 10.0))
    assert entries[1].enabled is True

    view._handle_blank_menu("select_all")
    assert len(view._selected_clones) == 3
    view._handle_blank_menu("clear_selection")
    assert view._selected_clones == set()


def test_blank_menu_is_empty_over_a_tile(toga_app, tmp_path, monkeypatch):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()
    monkeypatch.setattr(cocoa_events, "window_frame", lambda widget: (0.0, 0.0, 900.0, 700.0))

    # Over a tile the tile's own NSMenu must be used.
    assert view._blank_menu_entries_at((10.0, 10.0)) == ()


def test_refresh_update_status_repaints_the_badges(toga_app, tmp_path, monkeypatch):
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()
    monkeypatch.setattr(
        "twinspace.gui.views.environment_list.update_statuses",
        lambda records: {
            record.clone_name: AppUpdate("1.0", "2.0", True) for record in records
        },
    )

    asyncio.run(view.refresh_update_status())

    tile = view._cards["phone1"].tiles["Chrome-phone1"]
    assert tile.update_available is True
    assert view._cards["phone1"].update_badge.text == t(
        "environment_update_badge", count=3
    )
    assert view._cards["phone1"].update_button.enabled is True


def test_confirm_uses_the_action_label(toga_app, tmp_path, monkeypatch):
    captured: dict[str, str] = {}

    async def fake_confirm(window, title, message, ok_label, cancel_label):
        captured.update(ok=ok_label, cancel=cancel_label)
        return True

    monkeypatch.setattr(cocoa_events, "confirm_with_labels", fake_confirm)
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view.app_instance = MagicMock()

    assert asyncio.run(view._confirm("t", "m", t("btn_update"))) is True
    assert captured == {"ok": t("btn_update"), "cancel": t("btn_cancel")}
