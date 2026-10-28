"""Environment list view: one card per multi-app isolated environment."""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW, START

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
        "update_button",
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
        update_button: toga.Button,
        backup_button: toga.Button,
        columns: int,
        running: bool,
    ):
        self.card = card
        self.grid = grid
        self.tiles = tiles
        self.status_dot = status_dot
        self.status_text = status_text
        self.update_button = update_button
        self.backup_button = backup_button
        self.signature: tuple[Any, ...] = ()
        self.columns = columns
        self.running = running


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
        # Selected app tile (Finder-style single-click selection).
        self._selected_tile: AppTile | None = None
        self._selected_clone: str | None = None
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
                self._environments = await loop.run_in_executor(
                    None, self.environment_service.list_environments
                )
            except Exception as exc:
                logger.error("Failed to list environments: %s", exc)
                self._environments = []
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
        for button in (state.update_button, state.backup_button):
            if button.enabled != (not env_running):
                button.enabled = not env_running

    @staticmethod
    def _apply_status_pill(state: _EnvironmentCard, running: bool) -> None:
        if state.running == running:
            return
        state.running = running
        state.status_text.text = (
            t("environment_running") if running else t("environment_not_running")
        )
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
            enabled=not env_running,
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
            (btn_backup, "externaldrive"),
            (btn_manage, "plus"),
        ):
            cocoa_events.configure_button_icon(button, symbol)
        cocoa_events.style_primary_button(btn_open)
        actions.add(btn_open)
        actions.add(btn_update)
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
            update_button=btn_update,
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
        tile = AppTile(
            label=label,
            clone_name=record.clone_name,
            icon=cocoa_events.load_app_icon(record.dest_path),
            running=running,
            tooltip=t("env_app_tile_hint", app=label, clone=record.clone_name),
            on_open=lambda: self._schedule(self._toggle_app(env.name, key, False)),
            on_close=lambda: self._schedule(self._toggle_app(env.name, key, True)),
            on_edit=lambda: self._edit_app(record),
            on_reveal=lambda: self._schedule(self._reveal_path(record.dest_path)),
            on_update=lambda: self._schedule(
                self._update_app(env.name, key, record.clone_name)
            ),
            on_select=self._select_tile,
        )
        # Keep the selection across refreshes so the pill does not flicker away.
        if self._selected_clone is not None and tile.clone_name == self._selected_clone:
            tile.set_selected(True)
            self._selected_tile = tile
        return tile

    def _select_tile(self, tile: AppTile) -> None:
        """Select one tile at a time, Finder-style."""
        if self._selected_tile is not None and self._selected_tile is not tile:
            self._selected_tile.set_selected(False)
        self._selected_tile = tile
        self._selected_clone = tile.clone_name
        if not tile.selected:
            tile.set_selected(True)

    def _env_menu_entries(self, running: bool) -> tuple[cocoa_events.MenuEntry, ...]:
        return (
            cocoa_events.MenuEntry("open_all", t("environment_btn_open_all")),
            cocoa_events.MenuEntry(
                "update_all",
                t("environment_btn_update_all"),
                enabled=not running,
                separator=True,
            ),
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

    async def _update_app(self, env_name: str, app_key: str, clone_name: str) -> None:
        """Rebuild a single app of an environment from its current source app."""
        if self._is_running(clone_name):
            return
        if self.app_instance:
            confirmed = await self.app_instance.main_window.confirm_dialog(
                t("environment_update_title"),
                t("environment_app_update_confirm", app=clone_name),
            )
            if not confirmed:
                return
        try:
            errors = await self.environment_service.update_environment(
                env_name, app_keys=[app_key]
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

    async def _update_all(self, name: str) -> None:
        if not self.app_instance:
            return
        confirmed = await self.app_instance.main_window.confirm_dialog(
            t("environment_update_title"),
            t("environment_update_confirm", name=name),
        )
        if not confirmed:
            return
        try:
            errors = await self.environment_service.update_environment(name)
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
