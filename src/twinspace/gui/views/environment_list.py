"""Environment list view: one card per multi-app isolated environment."""

from __future__ import annotations

import asyncio
import functools
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW, START

from twinspace.core.app_version import AppUpdate, update_statuses
from twinspace.core.device_identity import identity_for_environment
from twinspace.core.environments import EnvironmentSpec
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.state import CloneRecord
from twinspace.gui import cocoa_events
from twinspace.gui.components.app_tile import AppTile, compute_tile_columns
from twinspace.gui.components.top_bar import TopHeaderBar
from twinspace.gui.components.wrapping_label import WrappingLabel
from twinspace.gui.patch_cocoa import configure_cocoa_card
from twinspace.gui.services.app_monitor import AppLifecycleMonitor
from twinspace.gui.services.environment_service import EnvironmentInfo, EnvironmentService
from twinspace.gui.services.launch_history import launch_history_for
from twinspace.gui.theme import Theme
from twinspace.gui.windows.clone_edit import CloneEditWindow
from twinspace.gui.windows.device_identity import DeviceIdentityWindow
from twinspace.gui.windows.environment_create import EnvironmentCreateWindow

logger = get_logger("gui.environment_list")

# An open/quit action updates the tile first; the process table is only used to
# confirm it. This keeps the optimistic state trusted while `ps` catches up.
_OPTIMISTIC_TTL = 4.0
# Grace period before the launch/quit is verified against the process table.
_VERIFY_DELAY = 0.6
# A rubber band smaller than this on both axes counts as a plain click.
_MARQUEE_THRESHOLD = 4.0
# Dragging within this distance of the scroll edges scrolls the page.
_AUTOSCROLL_EDGE = 42.0
_AUTOSCROLL_STEP = 16.0
_AUTOSCROLL_INTERVAL = 0.05
# Minimum gap between two "app became active" badge refreshes.
_STATUS_REFRESH_INTERVAL = 3.0


def _normalise_bundle_path(raw: Any) -> str:
    """Resolve a bundle path so NSWorkspace and the state file can be compared."""
    text = str(raw or "")
    if not text:
        return ""
    try:
        return os.path.realpath(text)
    except OSError:  # pragma: no cover - realpath is tolerant in practice
        return text


class _EnvironmentCard:
    """Native widgets of one environment card, kept for in-place updates."""

    __slots__ = (
        "card",
        "grid",
        "tiles",
        "status_dot",
        "status_text",
        "update_badge",
        "update_button",
        "rebuild_button",
        "backup_button",
        "signature",
        "columns",
        "running",
    )

    def __init__(
        self,
        *,
        card: toga.Box,
        grid: toga.Box,
        tiles: dict[str, AppTile],
        status_dot: toga.Label,
        status_text: toga.Label,
        update_badge: toga.Label,
        update_button: toga.Button,
        rebuild_button: toga.Button,
        backup_button: toga.Button,
        columns: int,
        running: bool,
    ):
        self.card = card
        self.grid = grid
        self.tiles = tiles
        self.status_dot = status_dot
        self.status_text = status_text
        self.update_badge = update_badge
        self.update_button = update_button
        self.rebuild_button = rebuild_button
        self.backup_button = backup_button
        self.signature: tuple[Any, ...] = ()
        self.columns = columns
        self.running = running


def _exclusive(operation: str):
    """Run one environment mutation at a time (guards double clicks)."""

    def decorator(method):
        @functools.wraps(method)
        async def wrapper(self, *args, **kwargs):
            if self._busy_operation is not None:
                logger.info(
                    "Ignored %s: %s is already running",
                    operation,
                    self._busy_operation,
                )
                return None
            self._busy_operation = operation
            try:
                return await method(self, *args, **kwargs)
            finally:
                self._busy_operation = None

        return wrapper

    return decorator


class EnvironmentListView(toga.Box):
    """Show named environments with open/manage/remove actions."""

    def __init__(
        self,
        environment_service: Optional[EnvironmentService] = None,
        app: Optional[toga.App] = None,
    ):
        super().__init__(style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_WINDOW))
        self.environment_service = environment_service or EnvironmentService()
        self.app_instance = app
        self._environments: list[EnvironmentInfo] = []
        self._running_clones: set[str] = set()
        # Multi-selection of app tiles (Finder-style: click, ⌘-click, drag).
        self._selected_clones: set[str] = set()
        self._selected_tile: AppTile | None = None
        self._selected_clone: str | None = None
        # Anchor used by ⇧-click, plus the rubber-band state of a drag sweep.
        self._selection_anchor: str | None = None
        self._drag_active = False
        self._drag_moved = False
        self._click_suppressed = False
        self._marquee: cocoa_events.Marquee | None = None
        self._marquee_origin: tuple[float, float] | None = None
        self._marquee_location: tuple[float, float] | None = None
        self._marquee_base: set[str] = set()
        # One long-running update/rebuild at a time.
        self._busy_operation: str | None = None
        self._last_status_refresh = 0.0
        # Version comparison per clone, refreshed with the environment list.
        self._update_status: dict[str, AppUpdate] = {}
        # Usable width inside the scroll area, used to lay the app icon grid out.
        self._content_width: float = 1012.0
        self._loading = False
        self._pending_refresh = False
        self._loading_indicator: toga.ActivityIndicator | None = None
        # Cards already mounted, keyed by environment name, so a refresh can
        # patch them instead of tearing the whole page down.
        self._cards: dict[str, _EnvironmentCard] = {}
        self._rendered = False
        # Optimistic running state for apps the user just opened/quit.
        self._optimistic: dict[str, tuple[bool, float]] = {}
        # NSWorkspace pushes launch/terminate events, so the dots stay live
        # without re-scanning the process table on every refresh.
        self._monitor = AppLifecycleMonitor.shared()
        self._clone_by_path: dict[str, str] = {}
        self._env_by_clone: dict[str, str] = {}
        self._monitor.subscribe(self)
        # Shared with the All Clones page: persists "last opened" timestamps.
        self.launch_history = launch_history_for(self.environment_service.state_manager)
        self.launch_history.subscribe(self)

        self._importing = False
        self.top_bar = TopHeaderBar(
            title=t("environment_title", count=0),
            action_label=t("environment_btn_new"),
            on_action=self.on_new_environment,
            action_symbol="plus",
            secondary_action_label=t("env_btn_import"),
            on_secondary_action=self.on_import_template,
            secondary_action_symbol="square.and.arrow.down",
            refresh_symbol="arrow.clockwise",
            on_refresh=lambda widget: asyncio.create_task(self.refresh_environments()),
        )
        self.add(self.top_bar)

        self.hint_label = WrappingLabel(
            t("environment_hint"),
            style=Pack(font_size=12, color=Theme.TEXT_MUTED, margin=(0, 24, 10, 24)),
        )
        self.add(self.hint_label)

        self.interaction_hint = toga.Label(
            t("environment_interaction_hint"),
            style=Pack(font_size=11.5, color=Theme.TEXT_TERTIARY, margin=(0, 24, 12, 24)),
        )
        self.add(self.interaction_hint)

        self.scroll = toga.ScrollContainer(style=Pack(flex=1), horizontal=False)
        self.list_box = toga.Box(style=Pack(direction=COLUMN, margin=(0, 24, 20, 24)))
        self.scroll.content = self.list_box
        self.add(self.scroll)

        # Sweeping the pointer across tiles extends the selection (Finder-style).
        cocoa_events.attach_drag_monitor(self, self._handle_tile_drag)
        cocoa_events.attach_key_monitor(self, self._handle_key)
        cocoa_events.attach_activation_observer(self, self._on_app_activated)
        cocoa_events.attach_right_click_menu(
            self, self._blank_menu_entries_at, self._handle_blank_menu
        )

    async def refresh_environments(self, *, show_loading: bool | None = None) -> None:
        """Reload environment data and repaint the page in place.

        A refresh triggered by an action (open / quit / update) must not blank
        the page: mounted cards stay on screen and only the parts whose state
        actually changed are repainted. The spinner is reserved for the first
        paint, when there is nothing worth keeping on screen.
        """
        if self._loading:
            # Coalesce overlapping requests into one trailing refresh.
            self._pending_refresh = True
            return
        self._loading = True
        if show_loading is None:
            show_loading = not self._rendered
        if show_loading:
            self._show_loading()
        self._set_refresh_busy(True)
        # Let the spinner / toolbar state paint before doing executor work.
        await asyncio.sleep(0)
        loop = asyncio.get_running_loop()
        try:
            try:
                self._environments, self._update_status = await loop.run_in_executor(
                    None, self._load_environments
                )
            except Exception as exc:
                logger.error("Failed to list environments: %s", exc)
                self._environments = []
                self._update_status = {}
            self._prune_selection()
            self._rebuild_path_index()
            running = self._snapshot_running_clones()
            if running is None:
                # Not on macOS, or AppKit could not answer: fall back to `ps`.
                try:
                    running = await loop.run_in_executor(
                        None, self.environment_service.running_clones
                    )
                except Exception as exc:
                    logger.error("Failed to detect running environments: %s", exc)
                    running = set()
            self._running_clones = running
            self._prune_optimistic()
            await self._sync_cards(animate=show_loading)
        finally:
            if self._loading_indicator is not None:
                try:
                    self._loading_indicator.stop()
                except Exception:
                    pass
            self._loading_indicator = None
            self._loading = False
            self._set_refresh_busy(False)
        if self._pending_refresh:
            self._pending_refresh = False
            await self.refresh_environments(show_loading=False)

    def _load_environments(self) -> tuple[list[EnvironmentInfo], dict[str, AppUpdate]]:
        """Read environments plus the clone/source version comparison (worker thread)."""
        environments = self.environment_service.list_environments()
        records = [record for env in environments for record in env.records]
        return environments, update_statuses(records)

    def _prune_selection(self) -> None:
        """Drop selected names that no longer exist after a refresh."""
        known = {
            record.clone_name for env in self._environments for record in env.records
        }
        if not self._selected_clones <= known:
            self._selected_clones &= known
            if self._selected_clone not in self._selected_clones:
                self._selected_clone = None
                self._selected_tile = None
            if self._selection_anchor not in self._selected_clones:
                self._selection_anchor = None

    def _rebuild_path_index(self) -> None:
        """Index clone records by bundle path for O(1) event lookups."""
        self._clone_by_path = {}
        self._env_by_clone = {}
        for env in self._environments:
            for record in env.records:
                path = _normalise_bundle_path(record.dest_path)
                if path:
                    self._clone_by_path[path] = record.clone_name
                self._env_by_clone[record.clone_name] = env.name

    def _snapshot_running_clones(self) -> set[str] | None:
        """Running clones from NSWorkspace; None means "fall back to `ps`"."""
        monitor = self._monitor
        if monitor is None or not monitor.available:
            return None
        paths = monitor.running_paths()
        if paths is None:
            return None
        index = self._clone_by_path
        running: set[str] = set()
        for path in paths:
            clone_name = index.get(path)
            if clone_name is None:
                # Only pay for a syscall when the raw comparison missed.
                clone_name = index.get(_normalise_bundle_path(path))
            if clone_name is not None:
                running.add(clone_name)
        return running

    def handle_app_state_change(self, bundle_path: str, running: bool) -> None:
        """NSWorkspace reported a clone bundle launching or terminating."""
        clone_name = self._clone_by_path.get(bundle_path)
        if clone_name is None:
            clone_name = self._clone_by_path.get(_normalise_bundle_path(bundle_path))
        if clone_name is None:
            return
        if threading.current_thread() is not threading.main_thread():
            loop = getattr(self.app_instance, "loop", None) if self.app_instance else None
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(self._apply_app_state, clone_name, running)
            return
        self._apply_app_state(clone_name, running)

    def _apply_app_state(self, clone_name: str, running: bool) -> None:
        """Repaint a single tile after a real launch/terminate event."""
        if running:
            self._running_clones.add(clone_name)
        else:
            self._running_clones.discard(clone_name)
        # A real event is authoritative; the local guess is no longer needed.
        self._optimistic.pop(clone_name, None)

        env_name = self._env_by_clone.get(clone_name)
        if env_name is None:
            return
        state = self._cards.get(env_name)
        if state is None:
            return
        env = next((item for item in self._environments if item.name == env_name), None)
        if env is not None:
            self._update_card(state, env)

    def handle_clone_opened(self, clone_name: str, timestamp: str) -> None:
        """LaunchHistory reported that a clone bundle just started."""
        self._apply_last_opened(clone_name, timestamp)

    def _apply_last_opened(self, clone_name: str, timestamp: str) -> None:
        """Repaint one tile's last-opened caption without rebuilding the card."""
        for env in self._environments:
            for record in env.records:
                if record.clone_name == clone_name:
                    record.last_opened_at = timestamp
        for state in self._cards.values():
            tile = state.tiles.get(clone_name)
            if tile is not None:
                tile.set_last_opened(timestamp)

    async def _record_opened(self, clone_names: list[str]) -> None:
        """Persist opening timestamps, then paint them on the tiles."""
        if not clone_names:
            return
        loop = asyncio.get_running_loop()
        for clone_name in clone_names:
            timestamp = await loop.run_in_executor(
                None, self.launch_history.mark_opened, clone_name
            )
            if timestamp:
                self._apply_last_opened(clone_name, timestamp)

    def _clone_names_for_app(self, env_name: str, app_key: str) -> list[str]:
        env = next((item for item in self._environments if item.name == env_name), None)
        if env is None:
            return []
        return [
            record.clone_name
            for record in env.records
            if self.environment_service.app_key_for_bundle_id(record.bundle_id) == app_key
        ]

    def _set_refresh_busy(self, busy: bool) -> None:
        """Disable the toolbar refresh button while a reload is in flight."""
        button = getattr(self.top_bar, "btn_refresh", None)
        if button is None:
            return
        try:
            button.enabled = not busy
        except Exception:
            pass

    def _show_loading(self) -> None:
        """Replace the card list with a centered spinner while data loads."""
        # The mounted cards are about to be dropped; forget them so the next
        # reconcile rebuilds them instead of assuming they are still on screen.
        self._cards.clear()
        self._clear(self.list_box)
        wrapper = toga.Box(
            style=Pack(
                direction=COLUMN,
                align_items=CENTER,
                margin=(70, 0, 0, 0),
            )
        )
        indicator = toga.ActivityIndicator(style=Pack(width=28, height=28))
        self._loading_indicator = indicator
        wrapper.add(indicator)
        wrapper.add(
            toga.Label(
                t("environment_loading"),
                style=Pack(
                    font_size=12.5,
                    color=Theme.TEXT_MUTED,
                    margin_top=12,
                ),
            )
        )
        self.list_box.add(wrapper)
        try:
            indicator.start()
        except Exception:
            pass

    async def _sync_cards(self, animate: bool = False) -> None:
        """Reconcile the mounted cards with ``self._environments``.

        Unchanged environments keep their existing native widgets; only cards
        that were added, removed or changed structurally are rebuilt, and their
        volatile parts (running status) are patched in place.
        """
        self._sync_title()
        desired = [env.name for env in self._environments]

        for name in [name for name in self._cards if name not in desired]:
            self._unmount_card(self._cards.pop(name))

        # Drop placeholders (spinner / empty state) so card positions line up.
        mounted = {state.card for state in self._cards.values()}
        for child in list(self.list_box.children):
            if child not in mounted:
                self.list_box.remove(child)

        if not self._environments:
            self._selected_tile = None
            self._selected_clone = None
            self._render_empty_state()
            self._rendered = True
            return

        for index, env in enumerate(self._environments):
            signature = self._card_signature(env)
            state = self._cards.get(env.name)
            if state is not None and state.signature == signature:
                self._update_card(state, env)
                self._place_card(index, state.card)
                continue
            if state is not None:
                self._unmount_card(state)
            state = self._build_environment_card(env)
            state.signature = signature
            self._cards[env.name] = state
            self._place_card(index, state.card)
            if animate:
                cocoa_events.fade_in(state.card)
                await asyncio.sleep(0.01)
        self._rendered = True
        self._apply_selection()

    def _sync_title(self) -> None:
        title = t("environment_title", count=len(self._environments))
        label = getattr(self.top_bar, "label_title", None)
        if label is not None and label.text == title:
            return
        self.top_bar.update_title(title)

    def _card_signature(self, env: EnvironmentInfo) -> tuple[Any, ...]:
        """Identity of a card's static content; a change forces a rebuild."""
        return (str(env.env_dir), tuple(record.clone_name for record in env.records))

    def _place_card(self, index: int, card: toga.Box) -> None:
        """Move ``card`` to ``index`` without rebuilding it when it is already there."""
        children = list(self.list_box.children)
        try:
            current: int = children.index(card)
        except ValueError:
            current = -1
        if current == index:
            return
        if current >= 0:
            self.list_box.remove(card)
        self.list_box.insert(index, card)

    def _unmount_card(self, state: _EnvironmentCard) -> None:
        try:
            if state.card.parent is self.list_box:
                self.list_box.remove(state.card)
        except Exception:
            logger.debug("Could not unmount environment card", exc_info=True)
        if self._selected_tile is not None and self._selected_tile in state.tiles.values():
            self._selected_tile = None

    def _update_card(self, state: _EnvironmentCard, env: EnvironmentInfo) -> None:
        """Patch the volatile parts of a mounted card (running status).

        Every write here reaches AppKit, so unchanged values are skipped: a
        refresh where nothing moved costs no native layout work at all.
        """
        env_running = any(self._is_running(record.clone_name) for record in env.records)
        self._apply_status_pill(state, env_running)
        for clone_name, tile in state.tiles.items():
            tile.set_running(self._is_running(clone_name))
            self._apply_tile_update(tile, clone_name)
        # Also pick up timestamps written while this card was mounted.
        for record in env.records:
            tile = state.tiles.get(record.clone_name)
            if tile is not None:
                tile.set_last_opened(getattr(record, "last_opened_at", ""))
        if state.backup_button.enabled != (not env_running):
            state.backup_button.enabled = not env_running
        # Meanwhile updates and rebuilds stay available: running apps are
        # skipped one by one instead of blocking the whole action.
        if not state.rebuild_button.enabled:
            state.rebuild_button.enabled = True
        update_enabled = self._pending_updates(env) > 0
        if state.update_button.enabled != update_enabled:
            state.update_button.enabled = update_enabled
        self._apply_update_badge(state, env)

    def _apply_tile_update(self, tile: AppTile, clone_name: str) -> None:
        """Paint the "new version" badge of one tile from the cached comparison."""
        status = self._update_status.get(clone_name)
        tile.set_update_info(
            bool(status and status.needs_update),
            status.current if status else "",
            status.latest if status else "",
        )

    def _pending_updates(self, env: EnvironmentInfo) -> int:
        """How many apps of this environment lag behind their source app."""
        pending = 0
        for record in env.records:
            status = self._update_status.get(record.clone_name)
            if status is not None and status.needs_update:
                pending += 1
        return pending

    def _apply_update_badge(self, state: _EnvironmentCard, env: EnvironmentInfo) -> None:
        """Show "n pending updates" next to the environment status pill."""
        pending = self._pending_updates(env)
        text = t("environment_update_badge", count=pending) if pending else ""
        if state.update_badge.text != text:
            state.update_badge.text = text

    @staticmethod
    def _apply_status_pill(state: _EnvironmentCard, running: bool) -> None:
        state.running = running
        text = t("environment_running") if running else t("environment_not_running")
        if state.status_text.text != text:
            # A running update may have replaced the label with its progress.
            state.status_text.text = text
        state.status_text.style.color = (
            Theme.TEXT_SECONDARY if running else Theme.TEXT_TERTIARY
        )
        state.status_dot.style.color = (
            Theme.BTN_SUCCESS if running else Theme.TEXT_TERTIARY
        )

    def _is_running(self, clone_name: str) -> bool:
        """Running state, honouring the optimistic flag set by open/quit actions."""
        pending = self._optimistic.get(clone_name)
        if pending is not None:
            value, expires_at = pending
            if time.monotonic() < expires_at:
                return value
            self._optimistic.pop(clone_name, None)
        return clone_name in self._running_clones

    def _prune_optimistic(self) -> None:
        """Forget optimistic states that the process table now agrees with."""
        now = time.monotonic()
        for clone_name, (value, expires_at) in list(self._optimistic.items()):
            if now >= expires_at or (clone_name in self._running_clones) == value:
                self._optimistic.pop(clone_name, None)

    def _mark_running(self, env_name: str, app_key: str, running: bool) -> None:
        """Flip one app's tile immediately; the process table confirms it later."""
        state = self._cards.get(env_name)
        env = next((item for item in self._environments if item.name == env_name), None)
        if state is None or env is None:
            return
        expires_at = time.monotonic() + _OPTIMISTIC_TTL
        for record in env.records:
            if self.environment_service.app_key_for_bundle_id(record.bundle_id) == app_key:
                self._optimistic[record.clone_name] = (running, expires_at)
        self._update_card(state, env)

    def _mark_environment_running(self, env_name: str, running: bool) -> None:
        """Flip every tile of an environment (Open All)."""
        state = self._cards.get(env_name)
        env = next((item for item in self._environments if item.name == env_name), None)
        if state is None or env is None:
            return
        expires_at = time.monotonic() + _OPTIMISTIC_TTL
        for record in env.records:
            self._optimistic[record.clone_name] = (running, expires_at)
        self._update_card(state, env)

    async def _verify_running_later(self) -> None:
        """Confirm an optimistic open/quit against the process table.

        The first pass usually already agrees with `ps`; a second one runs after
        the optimistic window expires so a crashed launch cannot leave a stale
        green dot behind.
        """
        await asyncio.sleep(_VERIFY_DELAY)
        if not self._optimistic:
            return
        await self.refresh_environments(show_loading=False)
        if not self._optimistic:
            return
        await asyncio.sleep(_OPTIMISTIC_TTL)
        await self.refresh_environments(show_loading=False)

    def on_window_resize(self, width: int) -> None:
        """Reflow the app icon grid when the window width changes."""
        available = max(320.0, float(width) - 240.0 - 48.0)
        if abs(available - self._content_width) < 8.0:
            return
        self._content_width = available
        columns = compute_tile_columns(available)
        for state in self._cards.values():
            if state.columns != columns:
                state.columns = columns
                self._layout_grid(state.grid, state.tiles, columns)

    def _clear(self, box: toga.Box) -> None:
        while len(box.children) > 0:
            box.remove(box.children[0])

    def _render(self) -> None:
        """Rebuild every card from scratch (full repaint, no incremental reuse)."""
        self._cards.clear()
        self._clear(self.list_box)
        self._selected_tile = None
        self._sync_title()

        if not self._environments:
            self._render_empty_state()
            self._rendered = True
            return

        for env in self._environments:
            state = self._build_environment_card(env)
            state.signature = self._card_signature(env)
            self._cards[env.name] = state
            self.list_box.add(state.card)
        self._rendered = True
        self._apply_selection()

    def _render_empty_state(self) -> None:
        empty = toga.Box(style=Pack(direction=COLUMN, align_items=CENTER, margin=(60, 0, 0, 0)))
        symbol = cocoa_events.system_symbol_toga_image("square.grid.2x2", 42)
        if symbol is not None:
            empty.add(toga.ImageView(symbol, style=Pack(width=42, height=42, margin_bottom=12)))
        empty.add(
            toga.Label(
                t("environment_empty_title"),
                style=Pack(
                    font_size=18,
                    font_weight="bold",
                    color=Theme.TEXT_PRIMARY,
                    margin_bottom=8,
                ),
            )
        )
        empty.add(
            WrappingLabel(
                t("environment_empty_hint"),
                style=Pack(font_size=13, color=Theme.TEXT_MUTED, margin=(0, 60, 18, 60)),
            )
        )
        create_button = toga.Button(
            t("environment_btn_new"),
            on_press=self.on_new_environment,
            style=Pack(height=32, font_size=13, font_weight="bold"),
        )
        cocoa_events.configure_button_icon(create_button, "plus")
        cocoa_events.style_primary_button(create_button)
        empty.add(create_button)
        self.list_box.add(empty)

    def _build_environment_card(self, env: EnvironmentInfo) -> _EnvironmentCard:
        env_running = any(self._is_running(record.clone_name) for record in env.records)
        card = toga.Box(
            style=Pack(direction=COLUMN, margin=(0, 0, 14, 0), background_color=Theme.BG_CARD)
        )
        inner = toga.Box(style=Pack(direction=COLUMN, margin=(16, 18, 14, 18)))

        # Header: environment name, live status and the overflow menu.
        header = toga.Box(style=Pack(direction=ROW, align_items=CENTER))
        header.add(
            toga.Label(
                env.name,
                style=Pack(font_size=17, font_weight="bold", color=Theme.TEXT_PRIMARY),
            )
        )
        header.add(toga.Box(style=Pack(width=10)))
        status_pill, status_dot, status_text = self._build_status_pill(env_running)
        header.add(status_pill)
        pending = self._pending_updates(env)
        update_badge = toga.Label(
            t("environment_update_badge", count=pending) if pending else "",
            style=Pack(
                font_size=11.5,
                font_weight="bold",
                color=Theme.BTN_WARNING,
                margin_left=8,
            ),
        )
        header.add(update_badge)
        header.add(toga.Box(style=Pack(flex=1)))
        header.add(
            toga.Button(
                "⋯",
                on_press=lambda widget, current=env: cocoa_events.popup_menu(
                    widget,
                    self._env_menu_entries(env_running),
                    lambda key: self._handle_env_menu(current, key),
                ),
                style=Pack(width=34, height=24, font_size=14),
            )
        )
        inner.add(header)

        inner.add(
            WrappingLabel(
                t("environment_path", path=str(env.env_dir)),
                style=Pack(font_size=11.5, color=Theme.TEXT_TERTIARY, margin_top=3),
            )
        )

        identity = identity_for_environment(env.name)
        inner.add(
            toga.Label(
                t(
                    "env_device_line",
                    uuid=identity.platform_uuid[:8],
                    hostname=identity.hostname,
                ),
                style=Pack(
                    font_size=11.5,
                    color=Theme.TEXT_TERTIARY,
                    margin_top=3,
                ),
            )
        )

        grid, tiles = self._build_app_grid(env)
        inner.add(grid)

        # Footer: daily actions stay visible; everything else lives in the menu.
        inner.add(
            toga.Box(
                style=Pack(
                    height=1,
                    margin=(12, 0, 10, 0),
                    background_color=Theme.BORDER_SUBTLE,
                )
            )
        )
        actions = toga.Box(style=Pack(direction=ROW, align_items=CENTER))
        btn_open = toga.Button(
            t("environment_btn_open_all"),
            on_press=lambda widget, name=env.name: self._schedule(self._open_all(name)),
            style=Pack(height=28, font_size=12.5, font_weight="bold", margin_right=8),
        )
        btn_update = toga.Button(
            t("environment_btn_update_all"),
            on_press=lambda widget, name=env.name: self._schedule(self._update_all(name)),
            enabled=pending > 0,
            style=Pack(height=28, font_size=12.5, margin_right=8),
        )
        btn_rebuild = toga.Button(
            t("environment_btn_rebuild_all"),
            on_press=lambda widget, name=env.name: self._schedule(self._rebuild_all(name)),
            style=Pack(height=28, font_size=12.5, margin_right=8),
        )
        btn_backup = toga.Button(
            t("environment_btn_backup"),
            on_press=lambda widget, name=env.name: self._schedule(self._backup(name)),
            enabled=not env_running,
            style=Pack(height=28, font_size=12.5, margin_right=8),
        )
        btn_manage = toga.Button(
            t("environment_btn_manage"),
            on_press=lambda widget, name=env.name: self._open_manage(name),
            style=Pack(height=28, font_size=12.5),
        )
        for button, symbol in (
            (btn_open, "play.fill"),
            (btn_update, "arrow.clockwise"),
            (btn_rebuild, "arrow.triangle.2.circlepath"),
            (btn_backup, "externaldrive"),
            (btn_manage, "plus"),
        ):
            cocoa_events.configure_button_icon(button, symbol)
        cocoa_events.style_primary_button(btn_open)
        actions.add(btn_open)
        actions.add(btn_update)
        actions.add(btn_rebuild)
        actions.add(btn_backup)
        actions.add(toga.Box(style=Pack(flex=1)))
        actions.add(btn_manage)
        inner.add(actions)

        card.add(inner)
        try:
            native_card = getattr(getattr(card, "_impl", None), "native", None)
            configure_cocoa_card(native_card, corner_radius=16.0, border_width=0.5)
        except Exception:
            pass
        columns = compute_tile_columns(self._content_width)
        return _EnvironmentCard(
            card=card,
            grid=grid,
            tiles=tiles,
            status_dot=status_dot,
            status_text=status_text,
            update_badge=update_badge,
            update_button=btn_update,
            rebuild_button=btn_rebuild,
            backup_button=btn_backup,
            columns=columns,
            running=env_running,
        )

    def _build_status_pill(
        self, running: bool
    ) -> tuple[toga.Box, toga.Label, toga.Label]:
        pill = toga.Box(style=Pack(direction=ROW, align_items=CENTER))
        dot = toga.Label(
            "●",
            style=Pack(
                font_size=9,
                color=Theme.BTN_SUCCESS if running else Theme.TEXT_TERTIARY,
                margin_right=4,
            ),
        )
        pill.add(dot)
        text = toga.Label(
            t("environment_running") if running else t("environment_not_running"),
            style=Pack(
                font_size=11.5,
                color=Theme.TEXT_SECONDARY if running else Theme.TEXT_TERTIARY,
            ),
        )
        pill.add(text)
        return pill, dot, text

    def _build_app_grid(self, env: EnvironmentInfo) -> tuple[toga.Box, dict[str, AppTile]]:
        grid = toga.Box(style=Pack(direction=COLUMN, margin_top=10))
        tiles = {
            record.clone_name: self._build_app_tile(env, record) for record in env.records
        }
        self._layout_grid(grid, tiles, compute_tile_columns(self._content_width))
        return grid, tiles

    def _layout_grid(
        self, grid: toga.Box, tiles: dict[str, AppTile], columns: int
    ) -> None:
        """Flow the tile widgets into rows, reusing the existing native widgets."""
        self._clear(grid)
        ordered = list(tiles.values())
        for start in range(0, len(ordered), columns):
            row = toga.Box(style=Pack(direction=ROW, align_items=START))
            for tile in ordered[start : start + columns]:
                row.add(tile)
            row.add(toga.Box(style=Pack(flex=1)))
            grid.add(row)

    def _build_app_tile(self, env: EnvironmentInfo, record: CloneRecord) -> AppTile:
        key = self.environment_service.app_key_for_bundle_id(record.bundle_id)
        app = self.environment_service.app_for_key(key)
        label = app.label if app else record.source_app
        running = self._is_running(record.clone_name)
        status = self._update_status.get(record.clone_name)
        tile = AppTile(
            label=label,
            clone_name=record.clone_name,
            icon=cocoa_events.load_app_icon(record.dest_path),
            running=running,
            last_opened=getattr(record, "last_opened_at", ""),
            tooltip=t("env_app_tile_hint", app=label, clone=record.clone_name),
            update_available=bool(status and status.needs_update),
            current_version=status.current if status else "",
            latest_version=status.latest if status else "",
            on_open=lambda: self._schedule(self._toggle_app(env.name, key, False)),
            on_close=lambda: self._schedule(self._toggle_app(env.name, key, True)),
            on_edit=lambda: self._edit_app(record),
            on_reveal=lambda: self._schedule(self._reveal_path(record.dest_path)),
            on_update=lambda: self._schedule(
                self._update_app(env.name, key, record.clone_name)
            ),
            on_select=self._select_tile,
            on_batch_action=self._handle_batch_menu,
        )
        # Keep the selection across refreshes so the pill does not flicker away.
        if tile.clone_name in self._selected_clones:
            tile.set_selected(True)
            self._selected_tile = tile
        return tile

    def _select_tile(
        self,
        tile: AppTile,
        intent: str = cocoa_events.SELECT_REPLACE,
    ) -> None:
        """Select a tile, honouring ⌘-click (toggle) and ⇧-click (range)."""
        if self._click_suppressed:
            # The click that ends a drag sweep must not collapse the range.
            self._click_suppressed = False
            return
        if intent == cocoa_events.SELECT_TOGGLE:
            self._toggle_tile(tile)
            return
        if intent == cocoa_events.SELECT_EXTEND and self._selection_anchor:
            self._select_range_to(tile.clone_name)
            return
        self._selected_clones = {tile.clone_name}
        self._selected_clone = tile.clone_name
        self._selection_anchor = tile.clone_name
        self._apply_selection()

    def _toggle_tile(self, tile: AppTile) -> None:
        name = tile.clone_name
        if name in self._selected_clones:
            self._selected_clones.discard(name)
        else:
            self._selected_clones.add(name)
        self._selected_clone = name
        self._selection_anchor = name
        self._apply_selection()

    def _select_range_to(self, clone_name: str) -> None:
        """Select every tile between the anchor and ``clone_name`` (inclusive)."""
        ordered = [tile.clone_name for tile in self._ordered_tiles()]
        anchor = self._selection_anchor
        if clone_name not in ordered or anchor not in ordered:
            self._selected_clones = {clone_name}
            self._selected_clone = clone_name
            self._selection_anchor = clone_name
            self._apply_selection()
            return
        start, end = sorted((ordered.index(anchor), ordered.index(clone_name)))
        self._selected_clones = set(ordered[start : end + 1])
        self._selected_clone = clone_name
        self._apply_selection()

    def _ordered_tiles(self) -> list[AppTile]:
        """Every mounted tile, in reading order across all environments."""
        tiles: list[AppTile] = []
        for env in self._environments:
            state = self._cards.get(env.name)
            if state is not None:
                tiles.extend(state.tiles.values())
        return tiles

    def _apply_selection(self) -> None:
        """Paint the selection pills and refresh the batch action bar."""
        batch_entries = (
            self._batch_menu_entries() if len(self._selected_clones) > 1 else None
        )
        for tile in self._ordered_tiles():
            selected = tile.clone_name in self._selected_clones
            if tile.selected != selected:
                tile.set_selected(selected)
            # Right-clicking a tile of a multi-selection offers batch actions.
            tile.set_batch_menu(batch_entries if selected else None)
        self._selected_tile = next(
            (
                tile
                for tile in self._ordered_tiles()
                if tile.clone_name == self._selected_clone
            ),
            None,
        )

    def _blank_menu_entries_at(
        self, location: tuple[float, float]
    ) -> tuple[cocoa_events.MenuEntry, ...]:
        """Menu shown when a right click lands on the page background."""
        frame = cocoa_events.window_frame(self)
        if frame is None or not cocoa_events.frame_contains(frame, location):
            return ()
        if self._tile_at_location(location) is not None:
            return ()  # the tile brings its own context menu
        hit = cocoa_events.hit_test_view(self, location)
        if cocoa_events.is_control_view(hit):
            return ()
        return (
            cocoa_events.MenuEntry("select_all", t("selection_select_all")),
            cocoa_events.MenuEntry(
                "clear_selection",
                t("selection_clear"),
                enabled=bool(self._selected_clones),
            ),
        )

    def _handle_blank_menu(self, key: str) -> None:
        if key == "select_all":
            self._select_all_tiles()
        elif key == "clear_selection":
            self.clear_selection()

    def _on_app_activated(self) -> None:
        """Re-check the ⬆ badges when the user comes back to TwinSpace."""
        if self._busy_operation is not None or self._drag_active:
            return
        now = time.monotonic()
        if now - self._last_status_refresh < _STATUS_REFRESH_INTERVAL:
            return
        self._last_status_refresh = now
        self._schedule(self.refresh_update_status())

    async def refresh_update_status(self) -> None:
        """Recompute and repaint the "newer source version" badges."""
        records = [record for env in self._environments for record in env.records]
        if not records:
            return
        loop = asyncio.get_running_loop()
        try:
            status = await loop.run_in_executor(None, update_statuses, records)
        except Exception:
            logger.debug("Could not refresh the update badges", exc_info=True)
            return
        self._update_status = status
        for env in self._environments:
            state = self._cards.get(env.name)
            if state is None:
                continue
            for clone_name, tile in state.tiles.items():
                self._apply_tile_update(tile, clone_name)
            self._apply_update_badge(state, env)
            state.update_button.enabled = self._pending_updates(env) > 0

    def _batch_menu_entries(self) -> tuple[cocoa_events.MenuEntry, ...]:
        """Context-menu items offered by a tile that belongs to a multi-selection."""
        selected = self._selected_records()
        count = len(selected)
        running = sum(1 for record in selected if self._is_running(record.clone_name))
        pending = sum(
            1
            for record in selected
            if not self._is_running(record.clone_name)
            and self._needs_update(record.clone_name)
        )
        return (
            cocoa_events.MenuEntry(
                "batch_open",
                t("environment_menu_batch_open", count=count),
                enabled=count - running > 0,
            ),
            cocoa_events.MenuEntry(
                "batch_close",
                t("environment_menu_batch_close", count=count),
                enabled=running > 0,
            ),
            cocoa_events.MenuEntry(
                "batch_update",
                t("environment_menu_batch_update", count=count),
                enabled=pending > 0,
                separator=True,
            ),
            cocoa_events.MenuEntry(
                "batch_rebuild",
                t("environment_menu_batch_rebuild", count=count),
                enabled=count - running > 0,
            ),
            cocoa_events.MenuEntry("batch_clear", t("selection_clear"), separator=True),
        )

    def _handle_batch_menu(self, key: str) -> None:
        """Dispatch the right-click batch actions of a multi-selection."""
        if key == "batch_open":
            self._schedule(self._batch_open_selected())
        elif key == "batch_close":
            self._schedule(self._batch_close_selected())
        elif key == "batch_update":
            self._schedule(self._batch_update_selected())
        elif key == "batch_rebuild":
            self._schedule(self._batch_rebuild_selected())
        elif key == "batch_clear":
            self.clear_selection()

    def clear_selection(self, widget: Any = None) -> None:
        """Drop the whole selection (the context menu's "Clear Selection")."""
        if not self._selected_clones:
            return
        self._selected_clones.clear()
        self._selected_clone = None
        self._selection_anchor = None
        self._apply_selection()

    def _handle_tile_drag(self, state: int, location: tuple[float, float]) -> None:
        """Rubber-band selection: drag a box and select every tile it touches."""
        if state == cocoa_events.GESTURE_BEGAN:
            self._click_suppressed = False
            self._drag_moved = False
            self._close_marquee()
            self._drag_active = False
            if not self._marquee_area_contains(location):
                return
            tile = self._tile_at_location(location)
            intent = cocoa_events.selection_intent()
            if tile is not None:
                self._selection_anchor = tile.clone_name
            elif intent == cocoa_events.SELECT_REPLACE and self._selected_clones:
                # A plain press on empty space drops the selection, like Finder.
                self.clear_selection()
            self._drag_active = True
            self._marquee_origin = location
            self._marquee_base = (
                set(self._selected_clones)
                if intent == cocoa_events.SELECT_EXTEND
                else set()
            )
            self._marquee = cocoa_events.Marquee(self)
            self._apply_marquee(location)
            self._schedule(self._autoscroll_loop())
            return
        if state in (cocoa_events.GESTURE_ENDED, cocoa_events.GESTURE_CANCELLED):
            self._close_marquee()
            if self._drag_active and self._drag_moved:
                # The click that ends a sweep must not collapse the selection.
                self._click_suppressed = True
            self._drag_active = False
            self._drag_moved = False
            return
        if not self._drag_active:
            return
        self._apply_marquee(location)

    def _handle_key(self, key: str, flags: int) -> bool:
        """⌘A selects every tile, Esc clears the selection or the rubber band."""
        if flags & cocoa_events.COMMAND_MODIFIER and key.lower() == "a":
            self._select_all_tiles()
            return True
        if key == "\x1b":
            if self._drag_active:
                self._cancel_marquee()
                return True
            if self._selected_clones:
                self.clear_selection()
                return True
        return False

    def _select_all_tiles(self) -> None:
        """Select every mounted tile (⌘A)."""
        tiles = self._ordered_tiles()
        if not tiles:
            return
        self._selected_clones = {tile.clone_name for tile in tiles}
        self._selected_clone = tiles[-1].clone_name
        self._selection_anchor = tiles[0].clone_name
        self._apply_selection()

    def _cancel_marquee(self) -> None:
        """Abort the rubber band and restore the selection it started from."""
        base = set(self._marquee_base)
        self._close_marquee()
        self._drag_active = False
        self._drag_moved = False
        # The release still produces a click on the tile below the pointer.
        self._click_suppressed = True
        self._selected_clones = base
        self._apply_selection()

    async def _autoscroll_loop(self) -> None:
        """Keep scrolling while the pointer rests near the page edges."""
        while self._drag_active:
            self._autoscroll_tick()
            await asyncio.sleep(_AUTOSCROLL_INTERVAL)

    def _autoscroll_tick(self) -> None:
        location = self._marquee_location
        if location is None:
            return
        frame = cocoa_events.window_frame(self.scroll)
        if frame is None:
            return
        bottom = frame[1]
        top = frame[1] + frame[3]
        y = location[1]
        amount = 0.0
        if y > top - _AUTOSCROLL_EDGE:
            amount = _AUTOSCROLL_STEP
        elif y < bottom + _AUTOSCROLL_EDGE:
            amount = -_AUTOSCROLL_STEP
        if not amount:
            return
        if cocoa_events.scroll_content(self.scroll, amount):
            self._apply_marquee(location)

    def _apply_marquee(self, location: tuple[float, float]) -> None:
        """Paint the rubber band and select every tile overlapping it."""
        self._marquee_location = location
        origin = self._marquee_origin
        if origin is None:
            return
        rect = cocoa_events.drag_rect(origin, location)
        if self._marquee is not None:
            self._marquee.set_rect(rect)
        if rect[2] < _MARQUEE_THRESHOLD and rect[3] < _MARQUEE_THRESHOLD:
            # A plain click: the click recognizer owns the selection.
            return
        self._drag_moved = True
        hits = self._tiles_in_rect(rect)
        self._selected_clones = self._marquee_base | {
            tile.clone_name for tile in hits
        }
        if hits:
            self._selected_clone = hits[-1].clone_name
        self._apply_selection()

    def _close_marquee(self) -> None:
        marquee = self._marquee
        self._marquee = None
        self._marquee_origin = None
        self._marquee_location = None
        self._marquee_base = set()
        if marquee is not None:
            marquee.close()

    def _marquee_area_contains(self, location: tuple[float, float]) -> bool:
        """True when a press starts in the scrollable card area.

        Empty space counts too: the rubber band may start anywhere inside the
        environment list except on a button (or the scrollbar).
        """
        frame = cocoa_events.window_frame(self.scroll)
        if frame is None or not cocoa_events.frame_contains(frame, location):
            return False
        hit = cocoa_events.hit_test_view(self, location)
        return not cocoa_events.is_control_view(hit)

    def _tiles_in_rect(self, rect: tuple[float, float, float, float]) -> list[AppTile]:
        """Tiles overlapping a window-space rectangle, in reading order."""
        hits: list[AppTile] = []
        for tile in self._ordered_tiles():
            frame = cocoa_events.window_frame(tile)
            if frame is not None and cocoa_events.frame_intersects(frame, rect):
                hits.append(tile)
        return hits

    def _tile_at_location(self, location: tuple[float, float]) -> AppTile | None:
        """Resolve the tile under a window-space point (drag hit testing)."""
        for tile in self._ordered_tiles():
            frame = cocoa_events.window_frame(tile)
            if frame is not None and cocoa_events.frame_contains(frame, location):
                return tile
        return None

    def _env_menu_entries(self, running: bool) -> tuple[cocoa_events.MenuEntry, ...]:
        return (
            cocoa_events.MenuEntry("open_all", t("environment_btn_open_all")),
            cocoa_events.MenuEntry(
                "update_all",
                t("environment_btn_update_all"),
                separator=True,
            ),
            cocoa_events.MenuEntry("rebuild_all", t("environment_btn_rebuild_all")),
            cocoa_events.MenuEntry(
                "backup", t("environment_btn_backup"), enabled=not running
            ),
            cocoa_events.MenuEntry("export", t("env_btn_export"), separator=True),
            cocoa_events.MenuEntry("restore", t("env_btn_restore")),
            cocoa_events.MenuEntry("device", t("env_menu_device"), separator=True),
            cocoa_events.MenuEntry("reveal", t("env_menu_reveal_dir"), separator=True),
            cocoa_events.MenuEntry(
                "remove", t("environment_btn_remove"), enabled=not running, separator=True
            ),
        )

    def _handle_env_menu(self, env: EnvironmentInfo, key: str) -> None:
        if key == "open_all":
            self._schedule(self._open_all(env.name))
        elif key == "update_all":
            self._schedule(self._update_all(env.name))
        elif key == "rebuild_all":
            self._schedule(self._rebuild_all(env.name))
        elif key == "backup":
            self._schedule(self._backup(env.name))
        elif key == "export":
            self._schedule(self._export_template(env.name))
        elif key == "restore":
            self._schedule(self._restore_backup(env.name))
        elif key == "device":
            self._show_device_identity(env)
        elif key == "reveal":
            self._schedule(self._reveal_path(env.env_dir))
        elif key == "remove":
            self._schedule(self._remove(env.name))

    def _show_device_identity(self, env: EnvironmentInfo) -> None:
        DeviceIdentityWindow(
            name=env.name,
            identity=identity_for_environment(env.name),
        ).show()

    def _schedule(self, awaitable: Any) -> None:
        """Run a coroutine produced by a native (AppKit) callback.

        Menu items and gesture recognizers are dispatched by AppKit, sometimes
        from inside a nested run loop. Fall back to the app loop and warn instead
        of silently dropping the work when no loop is reachable.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = getattr(self.app_instance, "loop", None) if self.app_instance else None
            if loop is None or not loop.is_running():
                close = getattr(awaitable, "close", None)
                if close is not None:
                    close()
                logger.warning(
                    "Dropped UI action: no running event loop for %r",
                    getattr(awaitable, "__qualname__", awaitable),
                )
                return
            loop.call_soon_threadsafe(loop.create_task, awaitable)
            return
        loop.create_task(awaitable)

    def on_new_environment(self, widget=None) -> None:
        EnvironmentCreateWindow(
            environment_service=self.environment_service,
            app=self.app_instance,
            on_complete=self._on_environment_changed,
        ).show()

    def _open_manage(self, name: str) -> None:
        EnvironmentCreateWindow(
            environment_service=self.environment_service,
            app=self.app_instance,
            initial_name=name,
            on_complete=self._on_environment_changed,
        ).show()

    async def _on_environment_changed(self) -> None:
        await self.refresh_environments()
        if self.app_instance and hasattr(self.app_instance, "clone_view"):
            try:
                await self.app_instance.clone_view.refresh_clones()
            except Exception:
                logger.debug("Clone list refresh after environment change failed", exc_info=True)

    async def _open_all(self, name: str) -> None:
        loop = asyncio.get_running_loop()
        try:
            errors = await loop.run_in_executor(
                None, self.environment_service.open_environment, name
            )
        except Exception as exc:
            errors = [str(exc)]
        if errors and self.app_instance:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"), "\n".join(errors)
            )
            return
        # Repaint the dots straight away; no full page rebuild is involved.
        self._mark_environment_running(name, True)
        env = next((item for item in self._environments if item.name == name), None)
        await self._record_opened([record.clone_name for record in env.records] if env else [])
        self._schedule(self._verify_running_later())

    async def _toggle_app(self, name: str, app_key: str, running: bool) -> None:
        loop = asyncio.get_running_loop()
        try:
            if running:
                errors = await loop.run_in_executor(
                    None, self.environment_service.quit_environment, name, [app_key]
                )
            else:
                errors = await loop.run_in_executor(
                    None, self.environment_service.open_environment, name, [app_key]
                )
        except Exception as exc:
            errors = [str(exc)]
        if errors and self.app_instance:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"), "\n".join(errors)
            )
            await self.refresh_environments(show_loading=False)
            return
        # Flip the tile immediately instead of tearing the page down and
        # waiting for the process table to catch up.
        self._mark_running(name, app_key, not running)
        if not running:
            await self._record_opened(self._clone_names_for_app(name, app_key))
        self._schedule(self._verify_running_later())

    def _edit_app(self, record: CloneRecord) -> None:
        """Open the clone editor for one app inside an environment."""
        window: CloneEditWindow

        async def _save_cb(updated_record: CloneRecord) -> None:
            try:
                await self.environment_service.clone_service.update_clone_record(updated_record)
                if (
                    updated_record.language != record.language
                    or updated_record.display_name != record.display_name
                    or updated_record.proxy_summary != record.proxy_summary
                    or updated_record.proxy_enabled != record.proxy_enabled
                    or getattr(window, "credential_changed", False)
                ):
                    try:
                        await self.environment_service.clone_service.update_clone(
                            updated_record.clone_name
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to rebuild %s after edit: %s",
                            updated_record.clone_name,
                            exc,
                        )
            except Exception as exc:
                logger.warning(
                    "Failed to save edits for %s: %s", updated_record.clone_name, exc
                )
            await self._on_environment_changed()

        window = CloneEditWindow(record=record, on_save=_save_cb)
        window.show()

    @_exclusive("update")
    async def _update_app(self, env_name: str, app_key: str, clone_name: str) -> None:
        """Rebuild a single app of an environment from its current source app."""
        if self._is_running(clone_name):
            if self.app_instance:
                await self.app_instance.main_window.info_dialog(
                    t("environment_done_title"),
                    t("environment_app_running", app=clone_name),
                )
            return
        if self.app_instance:
            confirmed = await self._confirm(
                t("environment_update_title"),
                t("environment_app_update_confirm", app=clone_name),
                t("btn_rebuild"),
            )
            if not confirmed:
                return
        try:
            errors = await self.environment_service.update_environment(
                env_name,
                app_keys=[app_key],
                on_progress=self._progress_reporter(
                    env_name, "environment_progress_rebuilding"
                ),
            )
        except Exception as exc:
            if self.app_instance:
                await self.app_instance.main_window.error_dialog(
                    t("environment_error_title"), str(exc)
                )
            return
        if errors:
            if self.app_instance:
                await self.app_instance.main_window.error_dialog(
                    t("environment_error_title"),
                    t("environment_update_error", errors="\n".join(errors)),
                )
        elif self.app_instance:
            await self.app_instance.main_window.info_dialog(
                t("environment_done_title"),
                t("environment_app_update_done", app=clone_name),
            )
        await self._on_environment_changed()

    def _selected_records(self) -> list[CloneRecord]:
        """Selected clone records in environment / app order."""
        return [
            record
            for env in self._environments
            for record in env.records
            if record.clone_name in self._selected_clones
        ]

    def _group_by_environment(
        self, records: list[CloneRecord]
    ) -> dict[str, list[str]]:
        """Map environment name -> selected app keys, for the batch calls."""
        groups: dict[str, list[str]] = {}
        for env in self._environments:
            names = {record.clone_name for record in env.records}
            keys = [
                self.environment_service.app_key_for_bundle_id(record.bundle_id)
                for record in records
                if record.clone_name in names
            ]
            keys = [key for key in keys if key]
            if keys:
                groups[env.name] = keys
        return groups

    async def _batch_open_selected(self) -> None:
        """Open every selected app that is currently closed."""
        targets = [
            record
            for record in self._selected_records()
            if not self._is_running(record.clone_name)
        ]
        groups = self._group_by_environment(targets)
        if not groups:
            return
        loop = asyncio.get_running_loop()
        errors: list[str] = []
        opened: list[str] = []
        for env_name, keys in groups.items():
            try:
                result = await loop.run_in_executor(
                    None, self.environment_service.open_environment, env_name, keys
                )
            except Exception as exc:
                result = [str(exc)]
            errors.extend(result)
            for key in keys:
                self._mark_running(env_name, key, True)
                opened.extend(self._clone_names_for_app(env_name, key))
        await self._record_opened(opened)
        self._schedule(self._verify_running_later())
        if errors and self.app_instance:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"), "\n".join(errors)
            )

    async def _batch_close_selected(self) -> None:
        """Close every selected app that is currently running."""
        targets = [
            record
            for record in self._selected_records()
            if self._is_running(record.clone_name)
        ]
        groups = self._group_by_environment(targets)
        if not groups:
            return
        loop = asyncio.get_running_loop()
        errors: list[str] = []
        for env_name, keys in groups.items():
            try:
                result = await loop.run_in_executor(
                    None, self.environment_service.quit_environment, env_name, keys
                )
            except Exception as exc:
                result = [str(exc)]
            errors.extend(result)
            for key in keys:
                self._mark_running(env_name, key, False)
        self._schedule(self._verify_running_later())
        if errors and self.app_instance:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"), "\n".join(errors)
            )

    @_exclusive("update")
    async def _batch_update_selected(self) -> None:
        """Update the selected apps, skipping the ones already up to date."""
        selected = self._selected_records()
        outdated = [
            record for record in selected if self._needs_update(record.clone_name)
        ]
        targets = [
            record for record in outdated if not self._is_running(record.clone_name)
        ]
        skipped = [
            record for record in outdated if self._is_running(record.clone_name)
        ]
        if not outdated:
            if self.app_instance:
                await self.app_instance.main_window.info_dialog(
                    t("environment_done_title"),
                    t("environment_update_none_selected"),
                )
            return
        if not targets:
            if self.app_instance:
                await self.app_instance.main_window.info_dialog(
                    t("environment_done_title"),
                    t("environment_batch_update_all_running"),
                )
            return
        groups = self._group_by_environment(targets)
        if not groups:
            return
        if self.app_instance:
            confirmed = await self._confirm(
                t("environment_update_title"),
                t("environment_batch_update_confirm", apps=self._app_list_text(targets))
                + self._skipped_running_text(skipped),
                t("btn_update"),
            )
            if not confirmed:
                return
        errors: list[str] = []
        updated = 0
        for env_name, keys in groups.items():
            try:
                result = await self.environment_service.update_environment(
                    env_name,
                    app_keys=keys,
                    on_progress=self._progress_reporter(
                        env_name, "environment_progress_updating"
                    ),
                )
            except Exception as exc:
                result = [f"{env_name}: {exc}"]
            if result:
                errors.extend(result)
            else:
                updated += len(keys)
        await self._on_environment_changed()
        if not self.app_instance:
            return
        if errors:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"),
                t("environment_update_error", errors="\n".join(errors)),
            )
        else:
            await self.app_instance.main_window.info_dialog(
                t("environment_done_title"),
                t("environment_batch_update_done", count=updated),
            )

    @_exclusive("rebuild")
    async def _batch_rebuild_selected(self) -> None:
        """Rebuild the selected apps from their source apps, skipping running ones."""
        selected = self._selected_records()
        targets = [
            record for record in selected if not self._is_running(record.clone_name)
        ]
        skipped = [
            record for record in selected if self._is_running(record.clone_name)
        ]
        if not targets:
            if self.app_instance:
                await self.app_instance.main_window.info_dialog(
                    t("environment_done_title"),
                    t("environment_batch_update_all_running"),
                )
            return
        groups = self._group_by_environment(targets)
        if not groups:
            return
        if self.app_instance:
            confirmed = await self._confirm(
                t("environment_update_title"),
                t(
                    "environment_batch_rebuild_confirm",
                    apps=self._app_list_text(targets),
                )
                + self._skipped_running_text(skipped),
                t("btn_rebuild"),
            )
            if not confirmed:
                return
        errors: list[str] = []
        rebuilt = 0
        for env_name, keys in groups.items():
            try:
                result = await self.environment_service.update_environment(
                    env_name,
                    app_keys=keys,
                    on_progress=self._progress_reporter(
                        env_name, "environment_progress_rebuilding"
                    ),
                )
            except Exception as exc:
                result = [f"{env_name}: {exc}"]
            if result:
                errors.extend(result)
            else:
                rebuilt += len(keys)
        await self._on_environment_changed()
        if not self.app_instance:
            return
        if errors:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"),
                t("environment_update_error", errors="\n".join(errors)),
            )
        else:
            await self.app_instance.main_window.info_dialog(
                t("environment_done_title"),
                t("environment_batch_rebuild_done", count=rebuilt),
            )

    async def _reveal_path(self, path: str | Path) -> None:
        target = Path(path)
        if not target.exists():
            return
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, lambda: subprocess.Popen(["open", "-R", str(target)])
            )
        except Exception as exc:
            logger.debug("Could not reveal %s: %s", target, exc)

    @_exclusive("update")
    async def _update_all(self, name: str) -> None:
        """Update only the apps whose version lags behind their source app."""
        if not self.app_instance:
            return
        env = next((item for item in self._environments if item.name == name), None)
        if env is None:
            return
        outdated = [
            record for record in env.records if self._needs_update(record.clone_name)
        ]
        targets = [
            record
            for record in outdated
            if not self._is_running(record.clone_name)
        ]
        skipped = [record for record in outdated if self._is_running(record.clone_name)]
        if not outdated:
            await self.app_instance.main_window.info_dialog(
                t("environment_done_title"),
                t("environment_update_all_none", name=name),
            )
            return
        if not targets:
            await self.app_instance.main_window.info_dialog(
                t("environment_done_title"),
                t("environment_update_all_running", name=name),
            )
            return
        confirmed = await self._confirm(
            t("environment_update_title"),
            t(
                "environment_update_confirm",
                name=name,
                apps=self._app_list_text(targets),
            )
            + self._skipped_running_text(skipped),
            t("btn_update"),
        )
        if not confirmed:
            return
        keys = self._app_keys(targets, self.environment_service)
        try:
            errors = await self.environment_service.update_environment(
                name,
                app_keys=keys,
                on_progress=self._progress_reporter(name, "environment_progress_updating"),
            )
        except Exception as exc:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"), str(exc)
            )
            return
        if errors:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"),
                t("environment_update_error", errors="\n".join(errors)),
            )
        else:
            await self.app_instance.main_window.info_dialog(
                t("environment_done_title"),
                t("environment_update_done", name=name),
            )
        await self._on_environment_changed()

    @_exclusive("rebuild")
    async def _rebuild_all(self, name: str) -> None:
        """Recreate every idle app of an environment from its source app."""
        if not self.app_instance:
            return
        env = next((item for item in self._environments if item.name == name), None)
        if env is None:
            return
        targets = [
            record
            for record in env.records
            if not self._is_running(record.clone_name)
        ]
        skipped = [
            record for record in env.records if self._is_running(record.clone_name)
        ]
        if not targets:
            await self.app_instance.main_window.info_dialog(
                t("environment_done_title"),
                t("environment_update_all_running", name=name),
            )
            return
        confirmed = await self._confirm(
            t("environment_update_title"),
            t("environment_rebuild_confirm", name=name, apps=self._app_list_text(targets))
            + self._skipped_running_text(skipped),
            t("btn_rebuild"),
        )
        if not confirmed:
            return
        try:
            if skipped:
                errors = await self.environment_service.update_environment(
                    name,
                    app_keys=self._app_keys(targets, self.environment_service),
                    on_progress=self._progress_reporter(
                        name, "environment_progress_rebuilding"
                    ),
                )
            else:
                errors = await self.environment_service.update_environment(
                    name,
                    on_progress=self._progress_reporter(
                        name, "environment_progress_rebuilding"
                    ),
                )
        except Exception as exc:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"), str(exc)
            )
            return
        if errors:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"),
                t("environment_update_error", errors="\n".join(errors)),
            )
        else:
            await self.app_instance.main_window.info_dialog(
                t("environment_done_title"),
                t("environment_update_done", name=name),
            )
        await self._on_environment_changed()

    def _needs_update(self, clone_name: str) -> bool:
        """True when the source app is newer than the environment's copy."""
        status = self._update_status.get(clone_name)
        return bool(status is not None and status.needs_update)

    def _app_label(self, record: CloneRecord) -> str:
        """Human readable app name (ZCode, WorkBuddy, …) of a clone record."""
        key = self.environment_service.app_key_for_bundle_id(record.bundle_id)
        app = self.environment_service.app_for_key(key) if key else None
        return app.label if app is not None else record.source_app

    def _app_list_text(self, records: list[CloneRecord]) -> str:
        """Comma separated app names for a confirmation dialog (capped)."""
        labels = [self._app_label(record) for record in records]
        limit = 8
        if len(labels) > limit:
            labels = labels[:limit] + [
                t("environment_more_apps", count=len(labels) - limit)
            ]
        return ", ".join(labels)

    def _skipped_running_text(self, records: list[CloneRecord]) -> str:
        """Dialog suffix listing the apps that were skipped because they run."""
        if not records:
            return ""
        return t("environment_update_skipped_running", apps=self._app_list_text(records))

    async def _confirm(self, title: str, message: str, ok_label: str) -> bool:
        """Confirm dialog whose accept button names the action."""
        if not self.app_instance:
            return False
        window = self.app_instance.main_window
        return await cocoa_events.confirm_with_labels(
            window, title, message, ok_label, t("btn_cancel")
        )

    def _progress_reporter(self, env_name: str, message_key: str):
        """Paint "updating 2/3 · ZCode" on the card while an app is rebuilt."""
        def report(index: int, total: int, app: Any, status: str) -> None:
            state = self._cards.get(env_name)
            if state is None:
                return
            label = getattr(app, "label", "") if app is not None else ""
            if status == "failed":
                text = t("environment_progress_failed", app=label)
            else:
                text = t(message_key, current=index, total=total, app=label)
            if state.status_text.text != text:
                state.status_text.text = text

        return report

    @staticmethod
    def _app_keys(records: list[CloneRecord], service: EnvironmentService) -> list[str]:
        keys = [
            key
            for record in records
            if (key := service.app_key_for_bundle_id(record.bundle_id))
        ]
        return list(dict.fromkeys(keys))

    async def _backup(self, name: str) -> None:
        if not self.app_instance:
            return
        loop = asyncio.get_running_loop()
        try:
            path = await loop.run_in_executor(
                None, self.environment_service.backup_environment, name
            )
        except Exception as exc:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"),
                t("environment_backup_error", error=str(exc)),
            )
            return
        await self.app_instance.main_window.info_dialog(
            t("environment_done_title"),
            t("environment_backup_done", path=str(path)),
        )

    async def _export_template(self, name: str) -> None:
        if not self.app_instance:
            return
        window = self.app_instance.main_window
        try:
            target = await window.dialog(
                toga.SaveFileDialog(
                    t("env_btn_export"),
                    suggested_filename=f"{name}.yaml",
                    file_types=["yaml", "yml"],
                )
            )
        except Exception:
            return
        if not target:
            return
        loop = asyncio.get_running_loop()
        try:
            spec = await loop.run_in_executor(
                None, self.environment_service.export_environment, name
            )
            Path(target).write_text(spec.to_yaml(), encoding="utf-8")
        except Exception as exc:
            await window.error_dialog(t("environment_error_title"), str(exc))
            return
        await window.info_dialog(
            t("dialog_success_title") if False else t("environment_done_title"),
            t("env_export_done", path=str(target)),
        )

    async def _restore_backup(self, name: str) -> None:
        if not self.app_instance:
            return
        window = self.app_instance.main_window
        try:
            archive = await window.dialog(
                toga.OpenFileDialog(t("env_btn_restore"), file_types=["gz"])
            )
        except Exception:
            return
        if not archive:
            return
        confirmed = await window.confirm_dialog(
            t("env_btn_restore"),
            t("env_restore_confirm_gui", name=name),
        )
        if not confirmed:
            return
        loop = asyncio.get_running_loop()
        try:
            restored, errors, safety = await loop.run_in_executor(
                None, self.environment_service.restore_environment, name, Path(archive)
            )
        except Exception as exc:
            await window.error_dialog(t("environment_error_title"), str(exc))
            return
        await self._on_environment_changed()
        if errors:
            await window.error_dialog(
                t("environment_error_title"), "\n".join(str(e) for e in errors)
            )
        else:
            await window.info_dialog(
                t("environment_done_title"),
                t("env_restore_done", apps=", ".join(restored) if restored else "-")
                + "\n"
                + t("env_restore_safety", path=str(safety)),
            )

    async def on_import_template(self, widget=None) -> None:
        if not self.app_instance or self._importing:
            return
        window = self.app_instance.main_window
        try:
            source = await window.dialog(
                toga.OpenFileDialog(t("env_btn_import"), file_types=["yaml", "yml"])
            )
        except Exception:
            return
        if not source:
            return
        self._importing = True
        if self.top_bar.btn_secondary is not None:
            self.top_bar.btn_secondary.enabled = False
        try:
            loop = asyncio.get_running_loop()
            spec = await loop.run_in_executor(
                None, lambda: EnvironmentSpec.from_yaml(Path(source).read_text(encoding="utf-8"))
            )
            existing = self.environment_service.environment(spec.name)
            existing_keys = existing.app_keys if existing else set()
            new_apps = [app.key for app in spec.apps if app.key not in existing_keys]
            if not new_apps:
                await window.info_dialog(
                    t("environment_done_title"), t("env_import_no_new")
                )
                return
            confirmed = await window.confirm_dialog(
                t("env_btn_import"),
                t("env_import_confirm", name=spec.name, apps=", ".join(new_apps)),
            )
            if not confirmed:
                return
            created = await self.environment_service.import_environment(spec)
            await self._on_environment_changed()
            await window.info_dialog(
                t("environment_done_title"),
                t("env_import_done", count=len(created), name=spec.name),
            )
        except Exception as exc:
            logger.exception("Environment template import failed")
            await window.error_dialog(t("environment_error_title"), str(exc))
        finally:
            self._importing = False
            if self.top_bar.btn_secondary is not None:
                self.top_bar.btn_secondary.enabled = True

    async def _remove(self, name: str) -> None:
        if not self.app_instance:
            return
        confirmed = await self.app_instance.main_window.confirm_dialog(
            t("environment_remove_title"),
            t("environment_remove_msg", name=name),
        )
        if not confirmed:
            return
        delete_data = await self.app_instance.main_window.confirm_dialog(
            t("environment_remove_title"),
            t("environment_remove_data_msg"),
        )
        try:
            errors = await self.environment_service.remove_environment(name, with_data=delete_data)
        except Exception as exc:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"),
                t("environment_remove_error", error=str(exc)),
            )
            return
        if errors:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"),
                "\n".join(errors),
            )
        await self._on_environment_changed()
