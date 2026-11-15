"""Source Apps view: clones grouped by the application they were cloned from.

The clone page is a flat list; this page answers the "one source app, many
clones" question — how many clones exist for WeChat/Chrome, which are running,
how much disk they occupy — with open/close/update actions for the whole group.

Layout follows the Environments page: a rounded card per source app, a
Finder-style icon grid of its clones (``AppTile``), a status pill plus update
badge in the header and the batch actions in the footer. Filtering reuses the
mounted cards — hidden ones are pooled instead of destroyed — so changing the
search text or a filter costs native re-parenting rather than rebuilding every
icon, caption and context menu.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from pathlib import Path
from typing import Any, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW, START

from twinspace.core.app_version import AppUpdate, update_statuses
from twinspace.core.config import get_config_value
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.state import CloneRecord, quit_clones, running_clone_names
from twinspace.core.timestamps import parse_iso_timestamp
from twinspace.gui import cocoa_events
from twinspace.gui.cocoa_events import MenuEntry
from twinspace.gui.components.app_tile import AppTile, compute_tile_columns
from twinspace.gui.components.top_bar import TopHeaderBar
from twinspace.gui.components.wrapping_label import WrappingLabel
from twinspace.gui.patch_cocoa import configure_cocoa_card
from twinspace.gui.services.app_monitor import AppLifecycleMonitor, enclosing_bundle
from twinspace.gui.services.data_size import data_size, format_size
from twinspace.gui.services.launch_history import launch_history_for
from twinspace.gui.theme import Theme
from twinspace.gui.windows.clone_edit import CloneEditWindow

logger = get_logger("gui.source_apps")

# Matches the Environments page so both pages read as one product.
_CARD_RADIUS = 16.0
# Hidden cards kept around for a filter change; beyond this they are dropped.
_POOL_LIMIT = 24
# Typing coalesces into one re-render (each keystroke mounts/unmounts cards).
_SEARCH_DEBOUNCE = 0.12
# Source paths are probed in the worker; this is the "unknown" placeholder.
_NAME_PREFIX = "name:"


def _normalise_path(raw: Any) -> str:
    text = str(raw or "")
    if not text:
        return ""
    try:
        return os.path.realpath(text)
    except OSError:  # pragma: no cover - realpath is tolerant in practice
        return text


class _SourceGroup:
    """Clones sharing one source application bundle."""

    def __init__(self, source_path: str, source_app: str):
        self.source_path = source_path
        self.source_app = source_app
        self.bundle_id = ""
        self.records: list[CloneRecord] = []
        # Optimistic until the worker probe reports; avoids a warning flash.
        self.source_exists = True

    def clone_names(self) -> list[str]:
        return [record.clone_name for record in self.records]

    def last_opened(self) -> float:
        """Newest "last opened" timestamp of the group, 0.0 when never opened."""
        newest = 0.0
        for record in self.records:
            stamp = parse_iso_timestamp(getattr(record, "last_opened_at", ""))
            if stamp is None:
                continue
            try:
                newest = max(newest, stamp.timestamp())
            except (OSError, OverflowError, ValueError):
                continue
        return newest


class SourceAppCard(toga.Box):
    """One source application and all of its clones."""

    def __init__(self, group: _SourceGroup, view: "SourceAppsView"):
        super().__init__(
            style=Pack(
                direction=COLUMN,
                margin=(0, 0, 14, 0),
                background_color=Theme.BG_CARD,
            )
        )
        self.group = group
        self._view = view
        self.tiles: dict[str, AppTile] = {}
        self.columns = 0
        self._source_missing = not group.source_exists
        self.label_warning: toga.Label | None = None
        # Painted-state caches: every write below reaches AppKit, so unchanged
        # values must cost nothing (a refresh with no changes writes nothing).
        self._running_count = -1
        self._painted_status: tuple[str, str] | None = None
        self._progress_text: str | None = None
        self._updating_active = False
        self._update_count: int | None = None
        self._downgrade_count: int | None = None
        self._stats_text = ""
        self._update_text = t("environment_btn_update_all")
        self._update_enabled: bool | None = None
        self._menu_signature: tuple | None = None
        self._painted_updates: dict[str, tuple] = {}

        inner = toga.Box(style=Pack(direction=COLUMN, margin=(16, 18, 14, 18)))

        header = toga.Box(style=Pack(direction=ROW, align_items=CENTER))
        header.add(self._build_source_icon())
        header.add(
            toga.Label(
                group.source_app,
                style=Pack(
                    font_size=17,
                    font_weight="bold",
                    color=Theme.TEXT_PRIMARY,
                    margin_right=10,
                ),
            )
        )
        self.update_badge = toga.Label(
            "",
            style=Pack(font_size=11.5, font_weight="bold", color=Theme.BTN_WARNING),
        )
        header.add(self.update_badge)
        header.add(toga.Box(style=Pack(flex=1)))
        header.add(self._build_status_pill())
        self.btn_menu = toga.Button(
            "⋯",
            on_press=self._show_menu,
            style=Pack(width=34, height=24, font_size=14, margin_left=8),
        )
        header.add(self.btn_menu)
        inner.add(header)

        self.label_path = WrappingLabel(
            self._path_text(),
            style=Pack(font_size=11.5, color=Theme.TEXT_TERTIARY, margin_top=4),
        )
        inner.add(self.label_path)
        self.label_stats = toga.Label(
            "",
            style=Pack(font_size=11.5, color=Theme.TEXT_TERTIARY, margin_top=2),
        )
        inner.add(self.label_stats)
        if self._source_missing:
            self.label_warning = toga.Label(
                "⚠ " + t("sources_missing_warning"),
                style=Pack(
                    font_size=11.5,
                    font_weight="bold",
                    color=Theme.BTN_WARNING,
                    margin_top=3,
                ),
            )
            inner.add(self.label_warning)

        self.grid = toga.Box(style=Pack(direction=COLUMN, margin_top=12))
        self.tiles = {
            record.clone_name: self._build_tile(record) for record in group.records
        }
        inner.add(self.grid)

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
        self.btn_open = toga.Button(
            t("environment_btn_open_all"),
            on_press=lambda widget: view.dispatch_action("open_all", self.group),
            style=Pack(height=28, font_size=12.5, font_weight="bold", margin_right=8),
        )
        self.btn_close = toga.Button(
            t("environment_btn_close_all"),
            on_press=lambda widget: view.dispatch_action("close_all", self.group),
            style=Pack(height=28, font_size=12.5, margin_right=8),
        )
        self.btn_update = toga.Button(
            t("environment_btn_update_all"),
            on_press=lambda widget: view.dispatch_action("update_all", self.group),
            style=Pack(height=28, font_size=12.5, margin_right=8),
        )
        btn_reveal = toga.Button(
            t("sources_menu_reveal_source"),
            on_press=lambda widget: view.dispatch_action("reveal", self.group),
            style=Pack(height=28, font_size=12.5),
        )
        for button, symbol in (
            (self.btn_open, "play.fill"),
            (self.btn_close, "stop.fill"),
            (self.btn_update, "arrow.clockwise"),
            (btn_reveal, "folder"),
        ):
            cocoa_events.configure_button_icon(button, symbol)
        cocoa_events.style_primary_button(self.btn_open)
        actions.add(self.btn_open)
        actions.add(self.btn_close)
        actions.add(self.btn_update)
        actions.add(toga.Box(style=Pack(flex=1)))
        actions.add(btn_reveal)
        inner.add(actions)

        self.add(inner)
        try:
            native_card = getattr(getattr(self, "_impl", None), "native", None)
            configure_cocoa_card(
                native_card,
                corner_radius=_CARD_RADIUS,
                border_width=Theme.BORDER_WIDTH_HAIRLINE,
            )
        except Exception:
            pass
        # Group-level right-click menu, installed on the card's own view only:
        # the tiles keep their per-clone menus (AppKit walks up the responder
        # chain for right clicks that land on labels or empty card space).
        cocoa_events.attach_root_menu(
            self, self._menu_entries(), self._handle_menu
        )

    # -- construction helpers --------------------------------------------------

    def _path_text(self) -> str:
        path = self.group.source_path
        if path.startswith(_NAME_PREFIX):
            return t("sources_path_line", path=self.group.source_app)
        return t("sources_path_line", path=path)

    def _build_source_icon(self) -> toga.Widget:
        icon = (
            cocoa_events.load_app_icon(self.group.source_path, size=40)
            if self.group.source_exists
            else None
        )
        if icon is not None:
            return toga.ImageView(icon, style=Pack(width=40, height=40, margin_right=12))
        fallback = toga.Box(
            style=Pack(
                direction=COLUMN,
                width=40,
                height=40,
                align_items=CENTER,
                margin_right=12,
                background_color=Theme.BADGE_HARD_BG,
            )
        )
        fallback.add(
            toga.Label(
                (self.group.source_app.strip()[:1] or "?").upper(),
                style=Pack(
                    font_size=18,
                    font_weight="bold",
                    color=Theme.BADGE_HARD_TEXT,
                    text_align=CENTER,
                    margin_top=9,
                ),
            )
        )
        try:
            configure_cocoa_card(
                getattr(getattr(fallback, "_impl", None), "native", None),
                corner_radius=10.0,
                border_width=0.0,
            )
        except Exception:
            pass
        return fallback

    def _build_status_pill(self) -> toga.Box:
        pill = toga.Box(
            style=Pack(direction=ROW, align_items=CENTER, margin_left=8)
        )
        self.status_dot = toga.Label(
            "●",
            style=Pack(
                font_size=9,
                color=Theme.TEXT_TERTIARY,
                margin_right=4,
            ),
        )
        self.label_pill = toga.Label(
            t("environment_not_running"),
            style=Pack(font_size=11.5, color=Theme.TEXT_TERTIARY),
        )
        pill.add(self.status_dot)
        pill.add(self.label_pill)
        self._paint_status()
        return pill

    def _build_tile(self, record: CloneRecord) -> AppTile:
        status = self._view.status_for(record.clone_name)
        name = record.clone_name
        tile = AppTile(
            label=name,
            clone_name=name,
            icon=cocoa_events.load_app_icon(record.dest_path),
            running=name in self._view.running_clones,
            last_opened=getattr(record, "last_opened_at", ""),
            tooltip=t(
                "sources_tile_hint",
                app=self.group.source_app,
                clone=name,
            ),
            update_available=bool(status and status.needs_update),
            current_version=status.current if status else "",
            latest_version=status.latest if status else "",
            downgrade_available=bool(status and status.needs_downgrade),
            on_open=lambda clone=name: self._view.dispatch_chip_action("launch", clone),
            on_close=lambda clone=name: self._view.dispatch_chip_action("close", clone),
            on_edit=lambda clone=name: self._view.dispatch_chip_action("edit", clone),
            on_reveal=lambda clone=name: self._view.dispatch_chip_action(
                "reveal_data", clone
            ),
            on_update=lambda clone=name: self._view.dispatch_chip_action(
                "update", clone
            ),
            on_detail=lambda clone=name: self._view.dispatch_chip_action(
                "detail", clone
            ),
            on_select=self._view._select_tile,
        )
        if name == self._view.selected_clone:
            tile.set_selected(True)
        return tile

    # -- menus -----------------------------------------------------------------

    def _update_label(self, syncs: int) -> str:
        label = t("environment_btn_update_all")
        return f"{label} ({syncs})" if syncs else label

    def _syncs(self) -> int:
        """Clones whose version differs from the source, in either direction."""
        return max(0, self._update_count or 0) + max(0, self._downgrade_count or 0)

    def _refresh_update_enabled(self) -> None:
        enabled = (
            self._syncs() > 0
            and not self._source_missing
            and not self._updating_active
        )
        if self._update_enabled != enabled:
            self._update_enabled = enabled
            self.btn_update.enabled = enabled

    def _menu_entries(self) -> tuple[MenuEntry, ...]:
        total = len(self.group.records)
        running = max(0, self._running_count)
        return (
            MenuEntry(
                "open_all",
                t("environment_btn_open_all"),
                enabled=running < total,
            ),
            MenuEntry(
                "close_all",
                t("environment_btn_close_all"),
                enabled=running > 0,
            ),
            MenuEntry(
                "update_all",
                self._update_label(self._syncs()),
                enabled=(
                    self._syncs() > 0
                    and not self._source_missing
                    and not self._updating_active
                ),
                separator=True,
            ),
            MenuEntry("reveal", t("sources_menu_reveal_source"), separator=True),
        )

    def _sync_menu(self, force: bool = False) -> None:
        """Rebuild the native menu only when its enabled states changed."""
        signature = (
            max(0, self._running_count),
            self._syncs(),
            self._source_missing,
            self._updating_active,
        )
        if signature == self._menu_signature and not force:
            return
        self._menu_signature = signature
        cocoa_events.attach_root_menu(self, self._menu_entries(), self._handle_menu)

    def _show_menu(self, widget: Any = None) -> None:
        self._sync_menu(force=True)
        cocoa_events.popup_menu(widget, self._menu_entries(), self._handle_menu)

    def _handle_menu(self, key: str) -> None:
        self._view.dispatch_action(key, self.group)

    # -- in-place patches ------------------------------------------------------

    def set_running(self, running: set[str]) -> None:
        """Repaint the running pill, the action buttons and every tile."""
        count = sum(1 for record in self.group.records if record.clone_name in running)
        if count != self._running_count:
            self._running_count = count
            open_enabled = count < len(self.group.records)
            if self.btn_open.enabled != open_enabled:
                self.btn_open.enabled = open_enabled
            close_enabled = count > 0
            if self.btn_close.enabled != close_enabled:
                self.btn_close.enabled = close_enabled
            self._sync_menu()
        self._paint_status()
        for name, tile in self.tiles.items():
            tile.set_running(name in running)

    def set_progress(self, text: str | None) -> None:
        """Show an update progress line in the status pill.

        Passing ``None`` restores the running/idle pill. While a progress line
        is shown the update action is disabled, so a group cannot be queued
        twice from the button or its context menu.
        """
        text = text or None
        if text == self._progress_text:
            return
        self._progress_text = text
        self._updating_active = text is not None
        self._paint_status()
        self._refresh_update_enabled()
        self._sync_menu()

    def _paint_status(self) -> None:
        """Paint the status pill, letting update progress win over running state."""
        if self._progress_text:
            text = self._progress_text
            color = Theme.BTN_WARNING
        elif self._running_count > 0:
            text = t("sources_running_pill", count=self._running_count)
            color = Theme.BTN_SUCCESS
        else:
            text = t("environment_not_running")
            color = Theme.TEXT_TERTIARY
        state = (text, color)
        if state == self._painted_status:
            return
        self._painted_status = state
        self.label_pill.text = text
        self.label_pill.style.color = color
        self.status_dot.style.color = color

    def set_stats(
        self,
        size: int | None,
        updates: int,
        downgrades: int = 0,
    ) -> None:
        """Repaint the metadata line and the update badge without a rebuild."""
        parts: list[str] = []
        if self.group.bundle_id:
            parts.append(self.group.bundle_id)
        parts.append(t("sources_stat_clones", count=len(self.group.records)))
        if size is not None:
            parts.append(format_size(size))
        text = " · ".join(parts)
        if text != self._stats_text:
            self._stats_text = text
            self.label_stats.text = text

        updates = max(0, int(updates or 0))
        downgrades = max(0, int(downgrades or 0))
        if (updates, downgrades) != (self._update_count, self._downgrade_count):
            self._update_count = updates
            self._downgrade_count = downgrades
            syncs = updates + downgrades
            label = self._update_label(syncs)
            if label != self._update_text:
                self._update_text = label
                self.btn_update.text = label
            badge_parts: list[str] = []
            if updates:
                badge_parts.append(t("environment_update_badge", count=updates))
            if downgrades:
                badge_parts.append(t("environment_downgrade_badge", count=downgrades))
            badge_text = "  ".join(badge_parts)
            if self.update_badge.text != badge_text:
                self.update_badge.text = badge_text
            self.update_badge.style.color = (
                Theme.BTN_WARNING if updates else Theme.BADGE_HARD_TEXT
            )
            self._sync_menu()
        self._refresh_update_enabled()

    def patch_updates(self) -> None:
        """Repaint the per-tile version badges from the cached comparison.

        ``AppTile.set_update_info`` always writes the badge colour, so the
        values are compared here first: an unchanged badge costs no AppKit work.
        """
        for record in self.group.records:
            tile = self.tiles.get(record.clone_name)
            if tile is None:
                continue
            status = self._view.status_for(record.clone_name)
            info = (
                bool(status and status.needs_update),
                status.current if status else "",
                status.latest if status else "",
                bool(status and status.needs_downgrade),
            )
            if self._painted_updates.get(record.clone_name) == info:
                continue
            self._painted_updates[record.clone_name] = info
            tile.set_update_info(*info)

    def patch_last_opened(self) -> None:
        """Repaint the "last opened" captions (no widget rebuild)."""
        for record in self.group.records:
            tile = self.tiles.get(record.clone_name)
            if tile is not None:
                tile.set_last_opened(getattr(record, "last_opened_at", ""))

    def set_last_opened(self, clone_name: str, timestamp: str) -> None:
        tile = self.tiles.get(clone_name)
        if tile is not None:
            tile.set_last_opened(timestamp)

    # -- layout ----------------------------------------------------------------

    def layout_tiles(self, columns: int) -> None:
        """Flow the clone tiles into rows of ``columns`` (reusing the widgets)."""
        if columns == self.columns and len(self.grid.children) > 0:
            return
        self.columns = columns
        self._view.layout_grid(self.grid, list(self.tiles.values()), columns)


class SourceAppsView(toga.Box):
    """Clones grouped by source application, with group-level batch actions."""

    def __init__(self, clone_service: Any, app: Optional[toga.App] = None):
        super().__init__(
            style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_WINDOW)
        )
        self.clone_service = clone_service
        self.app_instance = app

        self._records: list[CloneRecord] = []
        self._groups: list[_SourceGroup] = []
        self._group_by_key: dict[str, _SourceGroup] = {}
        self._group_of: dict[str, str] = {}
        self._record_by_name: dict[str, CloneRecord] = {}
        self._clone_by_path: dict[str, str] = {}
        self._status: dict[str, AppUpdate] = {}
        # Visible cards (key -> card, signature); hidden ones move to _pool.
        self._cards: dict[str, tuple[SourceAppCard, tuple]] = {}
        self._pool: dict[str, tuple[SourceAppCard, tuple]] = {}
        self._running: set[str] = set()
        # Finder-style single selection of one clone tile (visual feedback for
        # clicks; ⌘-click toggles it off). Kept across refreshes when possible.
        self._selected_clone: str | None = None
        # Groups with an update running; blocks a second click from the button
        # and the context menu while the rebuild loop is in flight.
        self._updating_groups: set[str] = set()
        self._sizes: dict[str, int] = {}
        self._sizes_computed = False
        self._computing_sizes = False
        self._busy = False
        self._pending_refresh = False
        self._mounted: str | None = None
        self._rendered = False
        self._content_width = 1012.0
        self._loading_indicator: toga.ActivityIndicator | None = None

        self._query = ""
        self._filter = "all"
        self._sort = "name"
        self._search_handle: Any = None
        self._filter_labels = {
            "all": t("sources_filter_all"),
            "updates": t("sources_filter_updates"),
            "running": t("sources_filter_running"),
            "missing": t("sources_filter_missing"),
        }
        self._filter_key_by_label = {
            label: key for key, label in self._filter_labels.items()
        }
        self._sort_labels = {
            "name": t("sources_sort_name"),
            "clones": t("sources_sort_clones"),
            "recent": t("sources_sort_recent"),
        }
        self._sort_key_by_label = {
            label: key for key, label in self._sort_labels.items()
        }

        self._monitor = AppLifecycleMonitor.shared()
        self._monitor.subscribe(self)
        self.launch_history = None
        state_manager = getattr(clone_service, "state_manager", None)
        if state_manager is not None:
            try:
                self.launch_history = launch_history_for(state_manager)
                self.launch_history.subscribe(self)
            except Exception:
                logger.debug("Could not attach launch history", exc_info=True)

        self.top_bar = TopHeaderBar(
            title=t("sources_title", count=0),
            search_placeholder=t("sources_search_placeholder"),
            on_search=self.on_search_changed,
            filter_items=list(self._filter_labels.values()),
            on_filter_change=self.on_filter_changed,
            sort_items=list(self._sort_labels.values()),
            on_sort_change=self.on_sort_changed,
            secondary_action_label=t("btn_compute_sizes"),
            on_secondary_action=self.on_compute_sizes,
            secondary_action_symbol="internaldrive",
            extra_action_label=t("storage_cleanup_btn"),
            on_extra_action=self.on_cleanup_caches,
            extra_action_symbol="trash",
            refresh_symbol="arrow.clockwise",
            on_refresh=self.on_refresh_sources,
        )
        self.add(self.top_bar)

        self.add(
            WrappingLabel(
                t("sources_hint"),
                style=Pack(font_size=12, color=Theme.TEXT_MUTED, margin=(0, 24, 10, 24)),
            )
        )

        self.content_container = toga.Box(
            style=Pack(direction=COLUMN, flex=1, margin=(0, 24, 20, 24))
        )
        self.add(self.content_container)

        self.list_box = toga.Box(
            style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_WINDOW)
        )
        self.scroll = toga.ScrollContainer(
            content=self.list_box, horizontal=False, style=Pack(flex=1)
        )

        self._empty_box = self._build_empty_state()
        self._no_results_box = self._build_no_results_state()

        # Right clicks on the page background offer page-level actions.
        cocoa_events.attach_right_click_menu(
            self, self._blank_menu_entries_at, self._handle_blank_menu
        )

    # -- derived state ---------------------------------------------------------

    @property
    def running_clones(self) -> set[str]:
        return self._running

    @property
    def selected_clone(self) -> str | None:
        return self._selected_clone

    def status_for(self, clone_name: str) -> AppUpdate | None:
        return self._status.get(clone_name)

    def _columns(self) -> int:
        return compute_tile_columns(self._content_width)

    # -- data ------------------------------------------------------------

    async def refresh_sources(self) -> None:
        if self._busy:
            self._pending_refresh = True
            return
        self._busy = True
        first_paint = not self._rendered
        if first_paint:
            self._show_loading()
        self._set_refresh_busy(True)
        # Let the spinner / toolbar state paint before doing executor work.
        await asyncio.sleep(0)
        loop = asyncio.get_running_loop()
        try:
            self._records = await self.clone_service.list_clones()
            self._rebuild_groups()
            try:
                statuses, exists = await loop.run_in_executor(
                    None, self._load_status_and_paths
                )
            except Exception:
                logger.debug("Could not compare source app versions", exc_info=True)
                statuses, exists = {}, {}
            self._status = statuses or {}
            for group in self._groups:
                if group.source_path in exists:
                    group.source_exists = bool(exists[group.source_path])
            running = self._snapshot_running()
            if running is None:
                try:
                    running = await loop.run_in_executor(
                        None, running_clone_names, self._records
                    )
                except Exception:
                    running = set()
            self._running = set(running)
            if self._sizes_computed:
                known = {record.clone_name for record in self._records}
                self._sizes = {
                    name: size for name, size in self._sizes.items() if name in known
                }
            self._sync_cards(animate=first_paint)
            self._rendered = True
        finally:
            self._busy = False
            self._stop_loading()
            self._set_refresh_busy(False)
        if self._pending_refresh:
            self._pending_refresh = False
            await self.refresh_sources()

    def _load_status_and_paths(self) -> tuple[dict[str, AppUpdate], dict[str, bool]]:
        """Version comparison plus source-bundle existence (worker thread)."""
        statuses = update_statuses(self._records)
        paths = {
            group.source_path
            for group in self._groups
            if not group.source_path.startswith(_NAME_PREFIX)
        }
        exists = {path: os.path.exists(path) for path in paths}
        return statuses, exists

    def on_refresh_sources(self, widget: Any = None) -> None:
        self._schedule(self.refresh_sources())

    def on_search_changed(self, query: str) -> None:
        """Filter groups by source app, bundle id or clone name.

        Keystrokes are coalesced: each re-render mounts/unmounts cards, so a
        burst of typing must only pay for the final query. Without a running
        loop (tests, early startup) the filter applies immediately.
        """
        self._query = str(query or "").strip().lower()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is None:
            self._sync_cards()
            return
        if self._search_handle is not None:
            try:
                self._search_handle.cancel()
            except Exception:
                pass
        self._search_handle = loop.call_later(_SEARCH_DEBOUNCE, self._apply_search)

    def _apply_search(self) -> None:
        self._search_handle = None
        self._sync_cards()

    def on_filter_changed(self, label: Any) -> None:
        key = self._filter_key_by_label.get(str(label), "all")
        if key == self._filter:
            return
        self._filter = key
        self._sync_cards()

    def on_sort_changed(self, label: Any) -> None:
        key = self._sort_key_by_label.get(str(label), "name")
        if key == self._sort:
            return
        self._sort = key
        self._sync_cards()

    def _clear_filters(self, widget: Any = None) -> None:
        """Reset the search field and the filter dropdown to "all"."""
        if self.top_bar.input_search is not None:
            self.top_bar.input_search.value = ""
        filter_select = getattr(self.top_bar, "select_filter", None)
        if filter_select is not None:
            filter_select.value = self._filter_labels["all"]
        self._query = ""
        self._filter = "all"
        # The field edits above scheduled a debounced render; render now and
        # drop the pending one so the page updates on the click itself.
        if self._search_handle is not None:
            try:
                self._search_handle.cancel()
            except Exception:
                pass
            self._search_handle = None
        self._sync_cards()

    def _filtered_groups(self) -> list[_SourceGroup]:
        groups = self._groups
        if self._query:
            groups = [
                group
                for group in groups
                if self._matches(group, self._query)
            ]
        if self._filter == "updates":
            groups = [
                group
                for group in groups
                if self._group_updates(group) or self._group_downgrades(group)
            ]
        elif self._filter == "running":
            groups = [
                group
                for group in groups
                if any(
                    record.clone_name in self._running for record in group.records
                )
            ]
        elif self._filter == "missing":
            groups = [group for group in groups if not group.source_exists]
        return self._sorted_groups(groups)

    @staticmethod
    def _matches(group: _SourceGroup, query: str) -> bool:
        if query in group.source_app.lower():
            return True
        if group.bundle_id and query in group.bundle_id.lower():
            return True
        return any(query in name.lower() for name in group.clone_names())

    def _sorted_groups(self, groups: list[_SourceGroup]) -> list[_SourceGroup]:
        if self._sort == "clones":
            return sorted(
                groups, key=lambda g: (-len(g.records), g.source_app.lower())
            )
        if self._sort == "recent":
            return sorted(
                groups, key=lambda g: (-g.last_opened(), g.source_app.lower())
            )
        return sorted(groups, key=lambda g: g.source_app.lower())

    def _rebuild_groups(self) -> None:
        groups: dict[str, _SourceGroup] = {}
        for record in self._records:
            key = _normalise_path(record.source_path)
            if not key:
                key = f"{_NAME_PREFIX}{record.source_app}"
            group = groups.get(key)
            if group is None:
                group = _SourceGroup(key, record.source_app)
                groups[key] = group
            if not group.bundle_id:
                group.bundle_id = record.bundle_id
            group.records.append(record)
        for group in groups.values():
            group.records.sort(key=lambda r: r.clone_name.lower())
        self._groups = sorted(groups.values(), key=lambda g: g.source_app.lower())
        self._group_by_key = {group.source_path: group for group in self._groups}
        self._group_of = {}
        self._record_by_name = {}
        self._clone_by_path = {}
        for group in self._groups:
            for record in group.records:
                self._group_of[record.clone_name] = group.source_path
                self._record_by_name[record.clone_name] = record
                path = _normalise_path(record.dest_path)
                if path:
                    self._clone_by_path[path] = record.clone_name

    def _snapshot_running(self) -> set[str] | None:
        monitor = self._monitor
        if monitor is None or not monitor.available:
            return None
        paths = monitor.running_paths()
        if paths is None:
            return None
        running: set[str] = set()
        for path in paths:
            clone_name = self._clone_by_path.get(path)
            if clone_name is None:
                clone_name = self._clone_by_path.get(_normalise_path(path))
            if clone_name is None:
                clone_name = self._clone_by_path.get(enclosing_bundle(path))
            if clone_name is not None:
                running.add(clone_name)
        return running

    # -- rendering -----------------------------------------------------------

    def _build_empty_state(self) -> toga.Box:
        box = toga.Box(style=Pack(direction=COLUMN, flex=1, align_items=CENTER))
        box.add(toga.Box(style=Pack(flex=1)))
        symbol = cocoa_events.system_symbol_toga_image("square.stack.3d.up", 42)
        if symbol is not None:
            box.add(
                toga.ImageView(
                    symbol, style=Pack(width=42, height=42, margin_bottom=12)
                )
            )
        box.add(
            toga.Label(
                t("sources_empty_title"),
                style=Pack(
                    font_size=18,
                    font_weight="bold",
                    color=Theme.TEXT_PRIMARY,
                    margin_bottom=8,
                ),
            )
        )
        box.add(
            WrappingLabel(
                t("sources_empty_hint"),
                style=Pack(font_size=13, color=Theme.TEXT_MUTED, margin=(0, 60, 18, 60)),
            )
        )
        button = toga.Button(
            t("sources_empty_action"),
            on_press=self._goto_create_clone,
            style=Pack(height=32, font_size=13, font_weight="bold"),
        )
        cocoa_events.configure_button_icon(button, "plus")
        cocoa_events.style_primary_button(button)
        box.add(button)
        box.add(toga.Box(style=Pack(flex=2)))
        return box

    def _build_no_results_state(self) -> toga.Box:
        box = toga.Box(style=Pack(direction=COLUMN, flex=1, align_items=CENTER))
        box.add(toga.Box(style=Pack(flex=1)))
        symbol = cocoa_events.system_symbol_toga_image("magnifyingglass", 38)
        if symbol is not None:
            box.add(
                toga.ImageView(
                    symbol, style=Pack(width=38, height=38, margin_bottom=12)
                )
            )
        box.add(
            toga.Label(
                t("sources_no_results"),
                style=Pack(
                    font_size=16,
                    font_weight="bold",
                    color=Theme.TEXT_PRIMARY,
                    margin_bottom=8,
                ),
            )
        )
        button = toga.Button(
            t("sources_clear_filters"),
            on_press=self._clear_filters,
            style=Pack(height=30, font_size=12.5),
        )
        box.add(button)
        box.add(toga.Box(style=Pack(flex=2)))
        return box

    def _mount_content(self, widget: toga.Widget) -> None:
        children = self.content_container.children
        if len(children) == 1 and children[0] is widget:
            return
        while len(self.content_container.children) > 0:
            self.content_container.remove(self.content_container.children[0])
        self.content_container.add(widget)

    def _sync_cards(self, animate: bool = False) -> None:
        """Reconcile the mounted cards with the filtered group list.

        Cards whose content did not change keep their native widgets; a card
        that leaves the current filter moves to the pool instead of being
        destroyed, so clearing the search restores it without rebuilding.
        """
        groups = self._filtered_groups()
        self._update_title(len(groups))
        visible = {group.source_path for group in groups}
        live = {group.source_path for group in self._groups}

        for key, (card, signature) in list(self._cards.items()):
            if key in visible:
                continue
            self._cards.pop(key)
            parent = card.parent
            if parent is not None:
                parent.remove(card)
            self._pool[key] = (card, signature)
        for key in [key for key in self._pool if key not in live]:
            self._pool.pop(key, None)
        while len(self._pool) > _POOL_LIMIT:
            self._pool.pop(next(iter(self._pool)))

        if not groups:
            no_results = bool(self._query) or self._filter != "all"
            self._mount_content(self._no_results_box if no_results else self._empty_box)
            self._mounted = "empty"
            return

        if self._mounted != "sources":
            self._mount_content(self.scroll)
            self._mounted = "sources"

        for index, group in enumerate(groups):
            card = self._card_for(group, animate)
            card.group = group
            card.patch_updates()
            card.patch_last_opened()
            card.set_running(self._running)
            card.set_stats(
                self._group_size(group) if self._sizes_computed else None,
                self._group_updates(group),
                self._group_downgrades(group),
            )
            self._place_card(index, card)

        if (
            self._selected_clone is not None
            and self._selected_clone not in self._record_by_name
        ):
            self._selected_clone = None
        self._apply_selection()

        mounted = {card for card, _signature in self._cards.values()}
        for child in list(self.list_box.children):
            if child not in mounted:
                self.list_box.remove(child)

    def _card_for(self, group: _SourceGroup, animate: bool) -> SourceAppCard:
        signature = self._group_signature(group)
        entry = self._cards.get(group.source_path)
        if entry is not None:
            if entry[1] == signature:
                return entry[0]
            parent = entry[0].parent
            if parent is not None:
                parent.remove(entry[0])
            self._cards.pop(group.source_path, None)

        pooled = self._pool.pop(group.source_path, None)
        if pooled is not None and pooled[1] == signature:
            card = pooled[0]
        else:
            if pooled is not None:
                parent = pooled[0].parent
                if parent is not None:
                    parent.remove(pooled[0])
            card = SourceAppCard(group, self)
            card.layout_tiles(self._columns())
            if animate:
                cocoa_events.fade_in(card)
        self._cards[group.source_path] = (card, signature)
        return card

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

    # -- selection -------------------------------------------------------------

    def _select_tile(
        self,
        tile: AppTile,
        intent: str = cocoa_events.SELECT_REPLACE,
    ) -> None:
        """Finder-style tile selection: click selects, ⌘-click toggles off."""
        name = tile.clone_name
        if intent == cocoa_events.SELECT_TOGGLE and self._selected_clone == name:
            self._selected_clone = None
        else:
            self._selected_clone = name
        self._apply_selection()

    def _apply_selection(self) -> None:
        """Paint the selection pill on the selected clone (guarded writes)."""
        selected = self._selected_clone
        for card, _signature in self._cards.values():
            for name, tile in card.tiles.items():
                wanted = name == selected
                if tile.selected != wanted:
                    tile.set_selected(wanted)

    def clear_selection(self, widget: Any = None) -> None:
        if self._selected_clone is None:
            return
        self._selected_clone = None
        self._apply_selection()

    # -- update progress -------------------------------------------------------

    def _card_for_clone(self, clone_name: str) -> SourceAppCard | None:
        key = self._group_of.get(clone_name)
        entry = self._cards.get(key) if key is not None else None
        return entry[0] if entry is not None else None

    def _set_tile_updating(self, clone_name: str, updating: bool) -> None:
        card = self._card_for_clone(clone_name)
        tile = card.tiles.get(clone_name) if card is not None else None
        if tile is not None:
            tile.set_updating(updating)

    def _show_update_progress(
        self, clone_name: str, current: int, total: int
    ) -> None:
        """Mark one tile as updating and paint the group's progress in its pill."""
        card = self._card_for_clone(clone_name)
        if card is None:
            return
        tile = card.tiles.get(clone_name)
        if tile is not None:
            tile.set_updating(True)
        card.set_progress(
            t(
                "sources_progress_updating",
                current=current,
                total=total,
                clone=clone_name,
            )
        )

    def _clear_update_progress(self, clone_name: str) -> None:
        card = self._card_for_clone(clone_name)
        if card is None:
            return
        tile = card.tiles.get(clone_name)
        if tile is not None:
            tile.set_updating(False)
        card.set_progress(None)

    def _group_signature(self, group: _SourceGroup) -> tuple:
        return (
            group.source_app,
            group.bundle_id,
            group.source_exists,
            tuple(group.clone_names()),
        )

    def layout_grid(
        self, grid: toga.Box, tiles: list[AppTile], columns: int
    ) -> None:
        """Flow tiles into rows, reusing the existing native widgets."""
        while len(grid.children) > 0:
            grid.remove(grid.children[0])
        for start in range(0, len(tiles), columns):
            row = toga.Box(style=Pack(direction=ROW, align_items=START))
            for tile in tiles[start : start + columns]:
                row.add(tile)
            row.add(toga.Box(style=Pack(flex=1)))
            grid.add(row)

    def _group_size(self, group: _SourceGroup) -> int:
        return sum(self._sizes.get(record.clone_name, 0) for record in group.records)

    def _group_updates(self, group: _SourceGroup) -> int:
        return sum(
            1
            for record in group.records
            if (status := self._status.get(record.clone_name)) is not None
            and status.needs_update
        )

    def _group_downgrades(self, group: _SourceGroup) -> int:
        return sum(
            1
            for record in group.records
            if (status := self._status.get(record.clone_name)) is not None
            and status.needs_downgrade
        )

    def _needs_sync(self, clone_name: str) -> bool:
        status = self._status.get(clone_name)
        return bool(status and (status.needs_update or status.needs_downgrade))

    def _update_title(self, count: int | None = None) -> None:
        shown = len(self._groups) if count is None else count
        title = t("sources_title", count=shown)
        running = len(self._running)
        if running:
            title += t("title_running_suffix", running=running)
        label = getattr(self.top_bar, "label_title", None)
        if label is None or label.text != title:
            self.top_bar.update_title(title)

    def _set_refresh_busy(self, busy: bool) -> None:
        button = getattr(self.top_bar, "btn_refresh", None)
        if button is not None and button.enabled == busy:
            button.enabled = not busy

    def _set_secondary_busy(self, busy: bool) -> None:
        button = getattr(self.top_bar, "btn_secondary", None)
        if button is not None and button.enabled == busy:
            button.enabled = not busy

    def on_window_resize(self, width: int) -> None:
        """Reflow every icon grid when the window width changes."""
        available = max(320.0, float(width) - 240.0 - 48.0)
        if abs(available - self._content_width) < 8.0:
            return
        self._content_width = available
        columns = compute_tile_columns(available)
        for card, _signature in self._cards.values():
            card.layout_tiles(columns)
        for card, _signature in self._pool.values():
            card.layout_tiles(columns)

    # -- size computation ------------------------------------------------------

    def on_compute_sizes(self, widget: Any = None) -> None:
        """Measure every clone's data dir on demand (trees can be 10s of GB)."""
        if not self._records or self._computing_sizes:
            return
        self._schedule(self._compute_sizes())

    async def _compute_sizes(self) -> None:
        """Measure one clone at a time so sizes appear progressively.

        A single ``compute_data_sizes`` call walks every data dir before the
        UI changes at all — on a large install that is half a minute of nothing
        happening. Iterating here keeps each group's number arriving as it is
        measured, and the toolbar button reports ``计算中 12/36``.
        """
        if self._computing_sizes:
            return
        self._computing_sizes = True
        self._set_secondary_busy(True)
        loop = asyncio.get_running_loop()
        records = list(self._records)
        total = len(records)
        self._sizes_computed = True
        try:
            for index, record in enumerate(records, start=1):
                try:
                    size = await loop.run_in_executor(
                        None, data_size, record.data_dir
                    )
                except Exception:
                    size = 0
                self._sizes[record.clone_name] = size
                self._patch_stats()
                self._set_secondary_text(
                    t("btn_computing_sizes", current=index, total=total)
                )
        finally:
            self._computing_sizes = False
            self._set_secondary_text(t("btn_compute_sizes"))
            self._set_secondary_busy(False)

    def on_cleanup_caches(self, widget: Any = None) -> None:
        """Open the storage cleanup window (cache review + selective delete)."""
        if self.app_instance is None:
            return
        from twinspace.gui.windows.cache_cleanup import CacheCleanupWindow

        CacheCleanupWindow(
            self.app_instance,
            self.clone_service,
            on_cleaned=self._on_caches_cleaned,
        ).show()

    def _on_caches_cleaned(self) -> None:
        """Forget measured sizes and recompute them after a cleanup."""
        self._sizes = {}
        self._sizes_computed = False
        self._patch_stats()
        if self._records:
            self.on_compute_sizes()

    def _set_secondary_text(self, text: str) -> None:
        button = getattr(self.top_bar, "btn_secondary", None)
        if button is not None and button.text != text:
            button.text = text

    def _patch_stats(self) -> None:
        for group in self._groups:
            entry = self._cards.get(group.source_path)
            if entry is not None:
                entry[0].set_stats(
                    self._group_size(group) if self._sizes_computed else None,
                    self._group_updates(group),
                    self._group_downgrades(group),
                )

    # -- actions ---------------------------------------------------------------

    def dispatch_action(self, key: str, group: _SourceGroup) -> None:
        # Same convention as the environment page: batch actions show no
        # loading UI — the cards repaint in place the moment it finishes.
        handler = {
            "open_all": self._open_all,
            "close_all": self._close_all,
            "update_all": self._update_all,
            "reveal": self._reveal,
        }.get(key)
        if handler is not None:
            self._schedule(handler(group))

    def dispatch_launch(self, record: CloneRecord) -> None:
        self.dispatch_chip_action("launch", record.clone_name)

    def dispatch_chip_action(self, key: str, clone_name: str) -> None:
        """Handle one per-clone tile action."""
        record = self._record_by_name.get(clone_name)
        if record is None:
            return
        handler = {
            "launch": self._launch,
            "close": self._close_one,
            "reveal_data": self._reveal_data,
            "edit": self._edit,
            "update": self._update_one,
            "detail": self._detail,
        }.get(key)
        if handler is not None:
            self._schedule(handler(record))

    def _schedule(self, awaitable: Any) -> None:
        """Run a coroutine produced by a native (AppKit) callback."""
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

    async def _launch(self, record: CloneRecord) -> None:
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: subprocess.Popen(["open", str(record.dest_path)])
            )
        except Exception as exc:
            logger.warning("Could not launch %s: %s", record.clone_name, exc)
            return
        self._running.add(record.clone_name)
        self._sync_cards()
        await self._record_opened([record.clone_name])

    async def _close_one(self, record: CloneRecord) -> None:
        loop = asyncio.get_running_loop()
        results = await loop.run_in_executor(None, quit_clones, [record.dest_path])
        if results.get(record.dest_path, True):
            self._running.discard(record.clone_name)
            self._sync_cards()
        else:
            await self._report_errors([f"{record.clone_name}: still running"])

    async def _open_all(self, group: _SourceGroup) -> None:
        """Launch the group's idle clones, spaced by the launch interval."""
        targets = [
            record for record in group.records if record.clone_name not in self._running
        ]
        if not targets:
            return
        try:
            interval = float(get_config_value("launch_interval", 2.0) or 0)
        except Exception:
            interval = 0.0
        interval = max(0.0, min(interval, 30.0))
        loop = asyncio.get_running_loop()
        errors: list[str] = []
        opened: list[str] = []
        for index, record in enumerate(targets):
            if index and interval:
                await asyncio.sleep(interval)
            try:
                await loop.run_in_executor(
                    None, lambda r=record: subprocess.Popen(["open", str(r.dest_path)])
                )
            except Exception as exc:
                errors.append(f"{record.clone_name}: {exc}")
                continue
            self._running.add(record.clone_name)
            opened.append(record.clone_name)
            self._sync_cards()
        await self._record_opened(opened)
        await self._report_errors(errors)

    async def _close_all(self, group: _SourceGroup) -> None:
        loop = asyncio.get_running_loop()
        paths = [record.dest_path for record in group.records]
        results = await loop.run_in_executor(None, quit_clones, paths)
        failed = [name for name, stopped in results.items() if not stopped]
        self._running.difference_update(
            record.clone_name
            for record in group.records
            if results.get(record.dest_path)
        )
        self._sync_cards()
        if failed:
            await self._report_errors([f"{name}: still running" for name in failed])

    async def _update_all(self, group: _SourceGroup) -> None:
        """Rebuild the outdated clones of a group, skipping the running ones."""
        if group.source_path in self._updating_groups:
            return
        outdated = [
            record
            for record in group.records
            if self._needs_sync(record.clone_name)
        ]
        if not outdated:
            await self._info(
                t("environment_done_title"),
                t("sources_update_none", app=group.source_app),
            )
            return
        if not group.source_exists:
            await self._info(
                t("environment_done_title"),
                t("sources_update_source_missing", app=group.source_app),
            )
            return
        targets = [
            record for record in outdated if record.clone_name not in self._running
        ]
        skipped = [
            record for record in outdated if record.clone_name in self._running
        ]
        if not targets:
            await self._info(
                t("environment_done_title"),
                t("sources_update_running", app=group.source_app),
            )
            return
        confirmed = await self._confirm(
            t("sources_update_title"),
            t(
                "sources_update_confirm",
                apps=self._name_list(targets),
            )
            + self._skipped_text(skipped),
            t("btn_update"),
        )
        if not confirmed:
            return
        errors: list[str] = []
        updated = 0
        self._updating_groups.add(group.source_path)
        try:
            for index, record in enumerate(targets, start=1):
                # Paint "更新中 i/n · 分身" in the card pill and the tile caption
                # before awaiting the rebuild, which can take a while.
                self._show_update_progress(record.clone_name, index, len(targets))
                try:
                    await self.clone_service.update_clone(record.clone_name)
                except Exception as exc:
                    errors.append(f"{record.clone_name}: {exc}")
                    self._set_tile_updating(record.clone_name, False)
                    card = self._card_for_clone(record.clone_name)
                    if card is not None:
                        card.set_progress(
                            t(
                                "environment_progress_failed",
                                app=record.clone_name,
                            )
                        )
                    continue
                self._set_tile_updating(record.clone_name, False)
                updated += 1
        finally:
            for record in targets:
                self._set_tile_updating(record.clone_name, False)
            entry = self._cards.get(group.source_path)
            if entry is not None:
                entry[0].set_progress(None)
            self._updating_groups.discard(group.source_path)
        await self.refresh_sources()
        if errors:
            await self._error(
                t("environment_error_title"),
                t("environment_update_error", errors="\n".join(errors)),
            )
        else:
            await self._info(
                t("environment_done_title"),
                t("sources_update_done", count=updated),
            )

    async def _update_one(self, record: CloneRecord) -> None:
        """Rebuild one clone from its source app (tile context menu)."""
        if record.clone_name in self._running:
            await self._info(
                t("environment_done_title"),
                t("environment_app_running", app=record.clone_name),
            )
            return
        group_key = self._group_of.get(record.clone_name)
        if group_key in self._updating_groups:
            return
        confirmed = await self._confirm(
            t("sources_update_title"),
            t("environment_app_update_confirm", app=record.clone_name),
            t("btn_rebuild"),
        )
        if not confirmed:
            return
        if group_key is not None:
            self._updating_groups.add(group_key)
        self._show_update_progress(record.clone_name, 1, 1)
        try:
            await self.clone_service.update_clone(record.clone_name)
        except Exception as exc:
            logger.warning("Could not update %s: %s", record.clone_name, exc)
            await self._error(t("environment_error_title"), str(exc))
            return
        finally:
            self._clear_update_progress(record.clone_name)
            if group_key is not None:
                self._updating_groups.discard(group_key)
        await self.refresh_sources()
        await self._info(
            t("environment_done_title"),
            t("environment_app_update_done", app=record.clone_name),
        )

    async def _edit(self, record: CloneRecord) -> None:
        """Open the clone editor and reload the page after a save."""
        window: CloneEditWindow

        async def _save_cb(updated_record: CloneRecord) -> None:
            try:
                await self.clone_service.update_clone_record(updated_record)
                if (
                    updated_record.language != record.language
                    or updated_record.display_name != record.display_name
                    or updated_record.proxy_summary != record.proxy_summary
                    or updated_record.proxy_enabled != record.proxy_enabled
                    or getattr(window, "credential_changed", False)
                ):
                    try:
                        await self.clone_service.update_clone(updated_record.clone_name)
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
            await self.refresh_sources()

        window = CloneEditWindow(record=record, on_save=_save_cb)
        window.show()

    async def _reveal_data(self, record: CloneRecord) -> None:
        target = Path(str(record.data_dir or ""))
        if not target.exists():
            return
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: subprocess.Popen(["open", "-R", str(target)])
        )

    async def _detail(self, record: CloneRecord) -> None:
        """Open the clone detail window through the clones page."""
        clone_view = getattr(self.app_instance, "clone_view", None)
        if clone_view is not None:
            await clone_view.on_detail_clone(record)

    async def _reveal(self, group: _SourceGroup) -> None:
        path = group.source_path
        if path.startswith(_NAME_PREFIX) or not Path(path).exists():
            return
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: subprocess.Popen(["open", "-R", path])
        )

    def _name_list(self, records: list[CloneRecord]) -> str:
        """Comma separated clone names for a confirmation dialog (capped)."""
        names = [record.clone_name for record in records]
        limit = 8
        if len(names) > limit:
            names = names[:limit] + [
                t("environment_more_apps", count=len(names) - limit)
            ]
        return ", ".join(names)

    def _skipped_text(self, records: list[CloneRecord]) -> str:
        if not records:
            return ""
        return t("environment_update_skipped_running", apps=self._name_list(records))

    async def _info(self, title: str, message: str) -> None:
        if self.app_instance is None:
            return
        try:
            await self.app_instance.main_window.info_dialog(title, message)
        except Exception:
            logger.debug("Could not show the info dialog", exc_info=True)

    async def _error(self, title: str, message: str) -> None:
        if self.app_instance is None:
            return
        try:
            await self.app_instance.main_window.error_dialog(title, message)
        except Exception:
            logger.debug("Could not show the error dialog", exc_info=True)

    async def _confirm(self, title: str, message: str, ok_label: str) -> bool:
        """Confirm dialog whose accept button names the action."""
        if self.app_instance is None:
            return False
        window = self.app_instance.main_window
        try:
            return await cocoa_events.confirm_with_labels(
                window, title, message, ok_label, t("btn_cancel")
            )
        except Exception:
            logger.debug("Could not show the confirm dialog", exc_info=True)
            return False

    async def _report_errors(self, errors: list[str]) -> None:
        if not errors:
            return
        await self._error(t("environment_quit_error_title"), "\n".join(errors))

    def _goto_create_clone(self, widget: Any = None) -> None:
        """Empty-state CTA: switch to the clone page and open the wizard."""
        app = self.app_instance
        if app is None:
            return
        try:
            app.switch_view("clones")
        except Exception:
            logger.debug("Could not switch to the clones page", exc_info=True)
        handler = getattr(getattr(app, "clone_view", None), "on_action_new_clone", None)
        if handler is not None:
            try:
                handler(None)
            except Exception:
                logger.debug("Could not open the clone wizard", exc_info=True)

    # -- page background menu --------------------------------------------------

    def _blank_menu_entries_at(
        self, location: tuple[float, float]
    ) -> tuple[MenuEntry, ...]:
        frame = cocoa_events.window_frame(self.scroll)
        if frame is None or not cocoa_events.frame_contains(frame, location):
            return ()
        if self._card_at_location(location) is not None:
            # Cards and the tiles inside them bring their own context menus.
            return ()
        hit = cocoa_events.hit_test_view(self, location)
        if cocoa_events.is_control_view(hit):
            return ()
        return (
            MenuEntry("refresh", t("sources_menu_refresh")),
            MenuEntry("compute", t("btn_compute_sizes")),
            MenuEntry(
                "clear",
                t("sources_clear_filters"),
                enabled=bool(self._query or self._filter != "all"),
                separator=True,
            ),
        )

    def _handle_blank_menu(self, key: str) -> None:
        if key == "refresh":
            self.on_refresh_sources()
        elif key == "compute":
            self.on_compute_sizes()
        elif key == "clear":
            self._clear_filters()

    def _card_at_location(
        self, location: tuple[float, float]
    ) -> SourceAppCard | None:
        for card, _signature in self._cards.values():
            frame = cocoa_events.window_frame(card)
            if frame is not None and cocoa_events.frame_contains(frame, location):
                return card
        return None

    # -- loading ---------------------------------------------------------------

    def _show_loading(self) -> None:
        """Full-page spinner for the very first load (nothing mounted yet)."""
        self._mounted = "loading"
        while len(self.content_container.children) > 0:
            self.content_container.remove(self.content_container.children[0])
        wrapper = toga.Box(
            style=Pack(direction=COLUMN, align_items=CENTER, margin=(70, 0, 0, 0))
        )
        indicator = toga.ActivityIndicator(style=Pack(width=28, height=28))
        self._loading_indicator = indicator
        wrapper.add(indicator)
        wrapper.add(
            toga.Label(
                t("sources_loading"),
                style=Pack(font_size=12.5, color=Theme.TEXT_MUTED, margin_top=12),
            )
        )
        self.content_container.add(wrapper)
        try:
            indicator.start()
        except Exception:
            pass

    def _stop_loading(self) -> None:
        indicator = self._loading_indicator
        self._loading_indicator = None
        if indicator is not None:
            try:
                indicator.stop()
            except Exception:
                pass

    # -- live updates ----------------------------------------------------------

    def handle_app_state_change(self, bundle_path: str, running: bool) -> None:
        """NSWorkspace reported a clone bundle launching or terminating."""
        clone_name = self._clone_by_path.get(bundle_path)
        if clone_name is None:
            clone_name = self._clone_by_path.get(_normalise_path(bundle_path))
        if clone_name is None:
            return
        if threading.current_thread() is not threading.main_thread():
            loop = (
                getattr(self.app_instance, "loop", None) if self.app_instance else None
            )
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(
                    self._apply_running_state, clone_name, running
                )
            return
        self._apply_running_state(clone_name, running)

    def _apply_running_state(self, clone_name: str, running: bool) -> None:
        if running:
            self._running.add(clone_name)
        else:
            self._running.discard(clone_name)
        if self._filter == "running":
            # Which groups are visible depends on the running state.
            self._sync_cards()
            return
        key = self._group_of.get(clone_name)
        entry = self._cards.get(key) if key is not None else None
        if entry is None:
            self._update_title()
            return
        card = entry[0]
        group = self._group_by_key.get(card.group.source_path)
        card.set_running(self._running)
        if group is not None:
            card.set_stats(
                self._group_size(group) if self._sizes_computed else None,
                self._group_updates(group),
                self._group_downgrades(group),
            )
        self._update_title()

    def handle_clone_opened(self, clone_name: str, timestamp: str) -> None:
        """LaunchHistory reported that a clone bundle just started."""
        self._apply_last_opened(clone_name, timestamp)

    def _apply_last_opened(self, clone_name: str, timestamp: str) -> None:
        record = self._record_by_name.get(clone_name)
        if record is not None:
            record.last_opened_at = timestamp
        key = self._group_of.get(clone_name)
        entry = self._cards.get(key) if key is not None else None
        if entry is not None:
            entry[0].set_last_opened(clone_name, timestamp)

    async def _record_opened(self, clone_names: list[str]) -> None:
        """Persist opening timestamps, then paint them on the tiles."""
        history = self.launch_history
        if history is None or not clone_names:
            return
        loop = asyncio.get_running_loop()
        for clone_name in clone_names:
            try:
                timestamp = await loop.run_in_executor(
                    None, history.mark_opened, clone_name
                )
            except Exception:
                continue
            if isinstance(timestamp, str) and timestamp:
                self._apply_last_opened(clone_name, timestamp)

    def focus_search(self) -> None:
        """Focus the toolbar search field (menu / keyboard driven)."""
        self.top_bar.focus_search()
