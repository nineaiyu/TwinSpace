"""Cloned Applications Dual-View (Card Grid & Table) View."""

import asyncio
import subprocess
from pathlib import Path
from typing import Any, Optional

import toga
from toga.sources import AccessorColumn
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.app_version import AppUpdate, parse_version, update_statuses
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.state import CloneRecord, quit_clone, running_clone_names
from twinspace.core.timestamps import format_last_opened
from twinspace.gui import cocoa_events
from twinspace.gui.components.clone_card import CloneCard
from twinspace.gui.components.top_bar import TopHeaderBar
from twinspace.gui.patch_cocoa import TABLE_ICON_SIZE, configure_cocoa_danger_button
from twinspace.gui.services.clone_service import CloneService
from twinspace.gui.services.launch_history import launch_history_for
from twinspace.gui.theme import Theme
from twinspace.gui.windows.clone_detail import CloneDetailWindow
from twinspace.gui.windows.clone_edit import CloneEditWindow
from twinspace.validation import redact_url_credentials

logger = get_logger("gui.clone_list")

# A rubber band smaller than this on both axes counts as a plain click.
_GRID_MARQUEE_THRESHOLD = 4.0
# Dragging within this distance of the grid edges scrolls the page.
_GRID_AUTOSCROLL_EDGE = 42.0
_GRID_AUTOSCROLL_STEP = 16.0
_GRID_AUTOSCROLL_INTERVAL = 0.05


class CloneNameColumn(AccessorColumn):
    """Name column that also renders the clone's application icon."""

    def __init__(self, heading: str, accessor: str, icon_provider: Any):
        super().__init__(heading, accessor)
        self._icon_provider = icon_provider

    def icon(self, row: Any) -> Any | None:
        try:
            return self._icon_provider(getattr(row, self.accessor, None))
        except Exception:
            return None


class CloneListView(toga.Box):
    """View rendering application clones with large section title, top-aligned controls, and dual Card/Table views."""

    def __init__(self, clone_service: Optional[CloneService] = None, app: Optional[toga.App] = None):
        super().__init__(style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_WINDOW))
        self.clone_service = clone_service or CloneService()
        self.app_instance = app
        self.launch_history = launch_history_for(self.clone_service.state_manager)
        self.launch_history.subscribe(self)
        self._raw_clones: list[CloneRecord] = []
        self._filtered_clones: list[CloneRecord] = []
        self._busy_clones: set[str] = set()
        self._icon_by_clone: dict[str, Any] = {}
        self._records_by_name: dict[str, CloneRecord] = {}
        # Clone/source version comparison, refreshed together with the list.
        self._update_status: dict[str, AppUpdate] = {}
        # Selection shared by the table and the card grid.
        self._selected_names: set[str] = set()
        self._selection_anchor: str | None = None
        self._grid_cards: list[CloneCard] = []
        self._drag_active = False
        self._drag_moved = False
        self._click_suppressed = False
        self._marquee: cocoa_events.Marquee | None = None
        self._marquee_origin: tuple[float, float] | None = None
        self._marquee_location: tuple[float, float] | None = None
        self._marquee_base: set[str] = set()
        self.view_mode: str = "list"  # "grid" or "list"
        self.search_query: str = ""
        self._search_debounce = None
        self._grid_columns = 2

        # Filter and Sort definitions
        self.filter_all = t("view_clones_filter_all")
        self.filter_hard = t("view_clones_filter_hard")
        self.filter_soft = t("view_clones_filter_soft")
        self.filter_proxy = t("view_clones_filter_proxy")

        self.sort_newest = t("view_clones_sort_newest")
        self.sort_name = t("view_clones_sort_name")
        self.sort_oldest = t("view_clones_sort_oldest")

        self.selected_filter: str = self.filter_all
        self.selected_sort: str = self.sort_newest
        self._env_filter_labels: dict[str, str] = {}

        # Top Header Bar with big section title and compact pinned toolbar
        self.top_bar = TopHeaderBar(
            title=t("view_clones_title", count=0),
            action_label=t("btn_new_clone"),
            on_action=self.on_action_new_clone,
            action_symbol="plus",
            refresh_symbol="arrow.clockwise",
            search_placeholder=t("view_clones_search_placeholder"),
            on_search=self.on_search_query_changed,
            filter_items=[self.filter_all, self.filter_hard, self.filter_soft, self.filter_proxy],
            on_filter_change=self.on_filter_changed,
            sort_items=[self.sort_newest, self.sort_name, self.sort_oldest],
            on_sort_change=self.on_sort_changed,
            view_modes=[t("topbar_view_list"), t("topbar_view_grid")],
            on_view_change=self.on_view_mode_changed,
            on_refresh=lambda w: asyncio.create_task(self.refresh_clones()),
        )
        self.add(self.top_bar)

        # Content container pinned right below header
        self.content_container = toga.Box(style=Pack(direction=COLUMN, flex=1, margin=(0, 24, 20, 24)))
        self.add(self.content_container)

        # Grid-mode hint about multi-selection (the table has native row drag).
        self.grid_hint_label = toga.Label(
            t("view_clones_selection_hint"),
            style=Pack(
                font_size=11.5,
                color=Theme.TEXT_TERTIARY,
                margin=(0, 0, 8, 0),
            ),
        )

        # Grid view scroll container & flow box
        self.grid_scroll = toga.ScrollContainer(style=Pack(flex=1), horizontal=False)
        self.grid_box = toga.Box(style=Pack(direction=COLUMN, margin=4))
        self.grid_scroll.content = self.grid_box

        # Rubber-band selection and shortcuts for the card grid.
        cocoa_events.attach_drag_monitor(self, self._handle_card_drag)
        cocoa_events.attach_key_monitor(self, self._handle_key)
        cocoa_events.attach_right_click_menu(
            self, self._card_menu_entries_at, self._handle_card_menu
        )

        # Table view & action bar, presented as a single elevated card.
        self.table_box = toga.Box(
            style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_CARD)
        )
        self.table = toga.Table(
            columns=[
                CloneNameColumn(t("list_col_name"), "name", self._icon_for_clone),
                t("list_col_source_app"),
                t("list_col_env"),
                t("list_col_strategy"),
                t("list_col_proxy"),
                t("list_col_notes"),
                t("list_col_created_at"),
                t("list_col_last_opened"),
                t("list_col_version"),
            ],
            multiple_select=True,
            on_select=self.on_table_select,
            on_activate=self.on_table_activate,
            style=Pack(flex=1, margin=(8, 8, 0, 8)),
        )
        self.table.on_header_sort = self.on_table_header_sort
        self.table_box.add(self.table)

        self.btn_launch_table = toga.Button(t("btn_launch"), on_press=lambda w: asyncio.create_task(self.on_open_selected()), enabled=False, style=Pack(margin_right=6, height=28, font_size=12.5, font_weight="bold"))
        self.btn_close_table = toga.Button(t("btn_close"), on_press=lambda w: asyncio.create_task(self.on_close_selected()), enabled=False, style=Pack(margin_right=6, height=28, font_size=12.5))
        self.btn_open_dir_table = toga.Button(t("btn_open_clone_dir"), on_press=lambda w: asyncio.create_task(self.on_open_clone_dir(self.get_selected_record())), enabled=False, style=Pack(margin_right=6, height=28, font_size=12.5))
        self.btn_update_table = toga.Button(t("btn_update"), on_press=lambda w: asyncio.create_task(self.on_update_clone(self.get_selected_records())), enabled=False, style=Pack(margin_right=6, height=28, font_size=12.5))
        self.btn_edit_table = toga.Button(t("btn_edit"), on_press=lambda w: asyncio.create_task(self.on_edit_clone(self.get_selected_record())), enabled=False, style=Pack(margin_right=6, height=28, font_size=12.5))
        self.btn_detail_table = toga.Button(t("btn_detail"), on_press=lambda w: asyncio.create_task(self.on_detail_clone(self.get_selected_record())), enabled=False, style=Pack(margin_right=6, height=28, font_size=12.5))
        self.btn_delete_table = toga.Button(t("btn_delete"), on_press=lambda w: asyncio.create_task(self.on_delete_clone(self.get_selected_records())), enabled=False, style=Pack(height=28, font_size=12.5))

        for button, symbol in (
            (self.btn_launch_table, "play.fill"),
            (self.btn_close_table, "stop.fill"),
            (self.btn_open_dir_table, "folder"),
            (self.btn_update_table, "arrow.clockwise"),
            (self.btn_edit_table, "pencil"),
            (self.btn_detail_table, "info.circle"),
            (self.btn_delete_table, "trash"),
        ):
            cocoa_events.configure_button_icon(button, symbol)

        actions_box = toga.Box(
            style=Pack(direction=ROW, align_items=CENTER, margin=(8, 8, 8, 8))
        )
        actions_box.add(self.btn_launch_table)
        actions_box.add(self.btn_close_table)
        actions_box.add(self.btn_open_dir_table)
        actions_box.add(self.btn_update_table)
        actions_box.add(self.btn_edit_table)
        actions_box.add(self.btn_detail_table)
        actions_box.add(toga.Box(style=Pack(flex=1)))
        configure_cocoa_danger_button(self.btn_delete_table)
        actions_box.add(self.btn_delete_table)
        self.table_box.add(actions_box)

        # Empty state — centered, HIG-compliant two-line layout
        self._empty_box = toga.Box(style=Pack(direction=COLUMN, flex=1, align_items=CENTER))
        self._empty_box.add(toga.Box(style=Pack(flex=1)))  # top spacer
        empty_symbol = cocoa_events.system_symbol_toga_image("square.on.square", 44)
        if empty_symbol is not None:
            self._empty_box.add(
                toga.ImageView(
                    empty_symbol,
                    style=Pack(width=44, height=44, margin_bottom=12),
                )
            )
        self._empty_box.add(toga.Label(
            t("view_clones_empty_hint"),
            style=Pack(font_size=16, font_weight="bold", color=Theme.TEXT_MUTED, margin_bottom=8),
        ))
        empty_actions = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_top=14))
        empty_env_button = toga.Button(
            t("view_clones_empty_cta_env"),
            on_press=self.on_goto_environments,
            style=Pack(height=32, font_size=13, font_weight="bold", margin_right=10),
        )
        cocoa_events.configure_button_icon(empty_env_button, "square.grid.2x2")
        cocoa_events.style_primary_button(empty_env_button)
        empty_new_button = toga.Button(
            t("btn_new_clone"),
            on_press=self.on_action_new_clone,
            style=Pack(height=32, font_size=13),
        )
        cocoa_events.configure_button_icon(empty_new_button, "plus")
        empty_actions.add(empty_env_button)
        empty_actions.add(empty_new_button)
        self._empty_box.add(empty_actions)
        self._empty_box.add(toga.Box(style=Pack(flex=2)))  # bottom spacer (2x = shift slightly above center)

        self._render_current_view()

    def on_view_mode_changed(self, mode: str):
        self.view_mode = mode
        self._render_current_view()

    def on_window_resize(self, width: int):
        """Adapt the card grid column count to the window width (1-3 columns)."""
        columns = max(1, min(3, int((width - 240 - 48) // 380)))
        if columns != self._grid_columns:
            self._grid_columns = columns
            if self.view_mode == "grid" and self._filtered_clones:
                self._render_current_view()

    def on_goto_environments(self, widget: toga.Button):
        if self.app_instance and hasattr(self.app_instance, "sidebar") and self.app_instance.sidebar:
            self.app_instance.sidebar.select_item("environments")
        elif self.app_instance and hasattr(self.app_instance, "switch_view"):
            self.app_instance.switch_view("environments")

    def on_search_query_changed(self, query: str):
        self.search_query = query.lower()
        # Debounce keystrokes so the table/card tree is not rebuilt per letter.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._apply_filter()
            return
        if self._search_debounce is not None:
            self._search_debounce.cancel()
        self._search_debounce = loop.call_later(0.2, self._apply_filter)

    def on_filter_changed(self, filter_val: str):
        self.selected_filter = filter_val
        self._apply_filter()

    def on_sort_changed(self, sort_val: str):
        self.selected_sort = sort_val
        self._apply_filter()

    def on_table_header_sort(self, col_index: int, column, ascending: bool):
        """Handle header click sorting for Table view and synchronize with toolbar."""
        if col_index == 0:  # Name
            self._filtered_clones.sort(key=lambda r: r.clone_name.lower(), reverse=not ascending)
            if ascending:
                self.selected_sort = self.sort_name
                if hasattr(self.top_bar, "select_sort") and self.top_bar.select_sort:
                    self.top_bar.select_sort.value = self.sort_name
        elif col_index == 1:  # Source App
            self._filtered_clones.sort(key=lambda r: r.source_app.lower(), reverse=not ascending)
        elif col_index == 2:  # Environment
            self._filtered_clones.sort(
                key=lambda r: (getattr(r, "env_group", "") or "").lower(),
                reverse=not ascending,
            )
        elif col_index == 3:  # Strategy
            self._filtered_clones.sort(key=lambda r: r.strategy.lower(), reverse=not ascending)
        elif col_index == 4:  # Proxy
            self._filtered_clones.sort(key=lambda r: (r.proxy_enabled, r.proxy_summary), reverse=not ascending)
        elif col_index == 5:  # Notes
            self._filtered_clones.sort(key=lambda r: (getattr(r, "notes", "") or "").lower(), reverse=not ascending)
        elif col_index == 6:  # Created At
            self._filtered_clones.sort(key=lambda r: r.created_at, reverse=not ascending)
            target_sort = self.sort_oldest if ascending else self.sort_newest
            self.selected_sort = target_sort
            if hasattr(self.top_bar, "select_sort") and self.top_bar.select_sort:
                self.top_bar.select_sort.value = target_sort
        elif col_index == 7:  # Last Opened (empty timestamps sort first)
            self._filtered_clones.sort(
                key=lambda r: getattr(r, "last_opened_at", "") or "",
                reverse=not ascending,
            )
        elif col_index == 8:  # Version (compared numerically, not as text)
            self._filtered_clones.sort(
                key=self._version_sort_key,
                reverse=not ascending,
            )

        self._render_current_view()

    def on_action_new_clone(self, widget: toga.Button):
        if self.app_instance and hasattr(self.app_instance, "action_new_clone"):
            self.app_instance.action_new_clone(widget)

    def _apply_filter(self):
        items = list(self._raw_clones)

        # 1. Search Query Filter
        if self.search_query:
            items = [
                r for r in items
                if self.search_query in r.clone_name.lower()
                or self.search_query in r.source_app.lower()
                or self.search_query in r.bundle_id.lower()
                or self.search_query in r.strategy.lower()
                or self.search_query in (getattr(r, "notes", "") or "").lower()
            ]

        # 2. Environment / Strategy / Proxy Filter
        selected_filter = str(self.selected_filter)
        if selected_filter in self._env_filter_labels:
            env_name = self._env_filter_labels[selected_filter]
            items = [r for r in items if (getattr(r, "env_group", "") or "") == env_name]
        elif "hard" in selected_filter.lower() or "物理" in selected_filter:
            items = [r for r in items if r.strategy == "hard_clone"]
        elif "soft" in selected_filter.lower() or "软" in selected_filter:
            items = [r for r in items if r.strategy == "soft_clone"]
        elif "proxy" in selected_filter.lower() or "代理" in selected_filter:
            items = [r for r in items if r.proxy_enabled]

        # 3. Sort
        selected_sort = str(self.selected_sort)
        if "name" in selected_sort.lower() or "名称" in selected_sort:
            items.sort(key=lambda r: r.clone_name.lower())
        elif "oldest" in selected_sort.lower() or "最早" in selected_sort:
            items.sort(key=lambda r: r.created_at)
        else:  # newest first
            items.sort(key=lambda r: r.created_at, reverse=True)

        self._filtered_clones = items
        self._render_current_view()

    def _render_current_view(self):
        while len(self.content_container.children) > 0:
            self.content_container.remove(self.content_container.children[0])

        total_count = len(self._raw_clones)
        filter_count = len(self._filtered_clones)
        if self.search_query or self.selected_filter != self.filter_all:
            self.top_bar.update_title(t("view_clones_title_filtered", filter_count=filter_count, total_count=total_count))
        else:
            self.top_bar.update_title(t("view_clones_title", count=total_count))

        if not self._filtered_clones:
            self.content_container.add(self._empty_box)
            return

        if self.view_mode == "grid":
            while len(self.grid_box.children) > 0:
                self.grid_box.remove(self.grid_box.children[0])
            self._grid_cards = []

            # Chunk into rows sized to the current window width
            ROW_SIZE = max(1, self._grid_columns)
            for i in range(0, len(self._filtered_clones), ROW_SIZE):
                chunk = self._filtered_clones[i:i + ROW_SIZE]
                row_box = toga.Box(style=Pack(direction=ROW, margin_bottom=12))
                for record in chunk:
                    status = self._update_status.get(record.clone_name)
                    card = CloneCard(
                        record=record,
                        on_launch=lambda r: asyncio.create_task(self.on_launch_clone(r)),
                        on_open_dir=lambda r: asyncio.create_task(self.on_open_clone_dir(r)),
                        on_update=lambda r: asyncio.create_task(self.on_update_clone(r)),
                        on_edit=lambda r: asyncio.create_task(self.on_edit_clone(r)),
                        on_detail=lambda r: asyncio.create_task(self.on_detail_clone(r)),
                        on_delete=lambda r: asyncio.create_task(self.on_delete_clone(r)),
                        current_version=status.current if status else "",
                        latest_version=status.latest if status else "",
                        update_available=bool(status and status.needs_update),
                    )
                    self._attach_card_selection(card)
                    self._grid_cards.append(card)
                    row_box.add(card)
                self.grid_box.add(row_box)
                cocoa_events.fade_in(row_box)

            self.content_container.add(self.grid_hint_label)
            self.content_container.add(self.grid_scroll)
            self._sync_card_selection()
        else:
            self._grid_cards = []
            prev_sel_names = set(self._selected_names) or {
                r.clone_name for r in self.get_selected_records()
            }

            table_data = [self._table_row(r) for r in self._filtered_clones]
            self.table.data = table_data
            self.content_container.add(self.table_box)

            if prev_sel_names:
                try:
                    from rubicon.objc import ObjCClass
                    NSMutableIndexSet = ObjCClass("NSMutableIndexSet")
                    index_set = NSMutableIndexSet.alloc().init()
                    for idx, r in enumerate(self._filtered_clones):
                        if r.clone_name in prev_sel_names:
                            index_set.addIndex_(idx)
                    native = getattr(getattr(self.table, "_impl", None), "native_table", None)
                    if native is not None and index_set.count > 0:
                        native.selectRowIndexes_byExtendingSelection_(index_set, False)
                except Exception:
                    pass

            self.on_table_select(self.table)

    def _table_row(self, record: CloneRecord) -> tuple[Any, ...]:
        """Build one table row; keep the column order in sync with the headers."""
        proxy_str = (
            redact_url_credentials(record.proxy_summary)
            if record.proxy_enabled
            else t("list_proxy_disabled")
        )
        notes_raw = (getattr(record, "notes", "") or "").replace("\n", " ").replace("\r", "")
        notes_display = (notes_raw[:40] + "…") if len(notes_raw) > 40 else notes_raw
        return (
            record.clone_name,
            record.source_app,
            getattr(record, "env_group", "") or "—",
            record.strategy,
            proxy_str,
            notes_display,
            record.created_at[:19] if len(record.created_at) >= 19 else record.created_at,
            format_last_opened(getattr(record, "last_opened_at", ""), compact=True),
            self._version_cell(record),
        )

    def _version_sort_key(self, record: CloneRecord) -> tuple[int, ...]:
        """Sort the version column by the source app version, numerically."""
        status = self._update_status.get(record.clone_name)
        return parse_version(status.latest if status else "")

    def _version_cell(self, record: CloneRecord) -> str:
        """Version column: "⬆ old → new" when the source app moved ahead."""
        status = self._update_status.get(record.clone_name)
        if status is None:
            return "—"
        if status.needs_update:
            current = status.current or "—"
            return f"⬆ {current} → {status.latest}"
        return status.current or status.latest or "—"

    def _apply_last_opened(self, clone_name: str, timestamp: str) -> None:
        """Refresh the last-opened caption of one clone without a full rebuild."""
        for record in self._raw_clones:
            if record.clone_name == clone_name:
                record.last_opened_at = timestamp

        if self.view_mode == "grid":
            for row in self.grid_box.children:
                for child in getattr(row, "children", []):
                    if isinstance(child, CloneCard) and child.record.clone_name == clone_name:
                        child.set_last_opened(timestamp)
            return

        index = next(
            (i for i, record in enumerate(self._filtered_clones) if record.clone_name == clone_name),
            None,
        )
        if index is None:
            return
        try:
            self.table.data[index] = self._table_row(self._filtered_clones[index])
        except Exception:
            logger.debug("Could not refresh the last-opened cell", exc_info=True)

    def handle_clone_opened(self, clone_name: str, timestamp: str) -> None:
        """LaunchHistory reported that a clone bundle just started."""
        self._apply_last_opened(clone_name, timestamp)

    async def _record_opened(self, clone_name: str) -> None:
        """Persist the launch, then paint the returned timestamp immediately."""
        loop = asyncio.get_running_loop()
        timestamp = await loop.run_in_executor(None, self.launch_history.mark_opened, clone_name)
        if timestamp:
            self._apply_last_opened(clone_name, timestamp)

    def on_table_select(self, widget: toga.Table):
        records = self.get_selected_records()
        if not records:
            single = self.get_selected_record()
            if single:
                records = [single]

        count = len(records)
        has_busy = any(r.clone_name in self._busy_clones for r in records)
        if self.view_mode == "list":
            self._selected_names = {r.clone_name for r in records}

        if count == 0:
            self.btn_launch_table.enabled = False
            self.btn_launch_table.text = t("btn_launch")
            self.btn_close_table.enabled = False
            self.btn_close_table.text = t("btn_close")
            self.btn_open_dir_table.enabled = False
            self.btn_update_table.enabled = False
            self.btn_update_table.text = t("btn_update")
            self.btn_edit_table.enabled = False
            self.btn_detail_table.enabled = False
            self.btn_delete_table.enabled = False
            self.btn_delete_table.text = t("btn_delete")
        elif count == 1:
            self.btn_launch_table.enabled = not has_busy
            self.btn_launch_table.text = t("btn_launch")
            self.btn_close_table.enabled = True
            self.btn_close_table.text = t("btn_close")
            self.btn_open_dir_table.enabled = True
            self.btn_update_table.enabled = not has_busy
            self.btn_update_table.text = t("btn_update")
            self.btn_edit_table.enabled = not has_busy
            self.btn_detail_table.enabled = True
            self.btn_delete_table.enabled = not has_busy
            self.btn_delete_table.text = t("btn_delete")
        else:  # count >= 2: batch open / close / update / delete
            self.btn_launch_table.enabled = not has_busy
            self.btn_launch_table.text = t("btn_batch_open", count=count)
            self.btn_close_table.enabled = True
            self.btn_close_table.text = t("btn_batch_close", count=count)
            self.btn_open_dir_table.enabled = False
            self.btn_update_table.enabled = not has_busy
            self.btn_update_table.text = t("btn_batch_update", count=count)
            self.btn_edit_table.enabled = False
            self.btn_detail_table.enabled = False
            self.btn_delete_table.enabled = not has_busy
            self.btn_delete_table.text = t("btn_batch_delete", count=count)

    async def on_table_activate(self, widget: toga.Table, row=None, **kwargs):
        # Double-click launches the clone — the natural Finder/Launchpad mapping;
        # editing stays on the explicit toolbar button.
        record = self.get_selected_record(row)
        if record is None:
            logger.warning("Table activate could not resolve a clone from row %r", row)
            return
        logger.info("Table activate: launching clone=%s", record.clone_name)
        await self.on_launch_clone(record)

    def _extract_clone_name(self, item, known_names: set[str]) -> Optional[str]:
        if item is None:
            return None
        if isinstance(item, str):
            return item if item in known_names else None
        name = getattr(item, "Name", None) or getattr(item, "clone_name", None) or getattr(item, t("list_col_name"), None)
        if name and name in known_names:
            return name
        if hasattr(item, "_raw") and item._raw and isinstance(item._raw[0], str) and item._raw[0] in known_names:
            return item._raw[0]
        if isinstance(item, (tuple, list)) and len(item) > 0:
            if isinstance(item[0], str) and item[0] in known_names:
                return item[0]
        if hasattr(item, "__dict__"):
            for k, v in item.__dict__.items():
                if not k.startswith("_") and isinstance(v, str) and v in known_names:
                    return v
        return None

    def get_selected_records(self, selection=None) -> list[CloneRecord]:
        sel = selection if selection is not None else self.table.selection
        if sel is None:
            return []

        known_names = {r.clone_name for r in self._filtered_clones}
        selected_names: set[str] = set()

        single_name = self._extract_clone_name(sel, known_names)
        if single_name:
            selected_names.add(single_name)
        elif isinstance(sel, (list, tuple, set)):
            for item in sel:
                name = self._extract_clone_name(item, known_names)
                if name:
                    selected_names.add(name)

        return [r for r in self._filtered_clones if r.clone_name in selected_names]

    def get_selected_record(self, row=None) -> Optional[CloneRecord]:
        if row is not None:
            records = self.get_selected_records(row)
            return records[0] if len(records) == 1 else None
        records = self.get_selected_records()
        return records[0] if len(records) == 1 else None

    async def refresh_clones(self):
        loop = asyncio.get_running_loop()
        self._raw_clones = await self.clone_service.list_clones()
        self._records_by_name = {
            record.clone_name: record for record in self._raw_clones
        }
        self._update_status = await loop.run_in_executor(
            None, update_statuses, self._raw_clones
        )
        self._selected_names &= set(self._records_by_name)
        if self._selection_anchor not in self._selected_names:
            self._selection_anchor = None
        self._icon_by_clone.clear()
        self._sync_env_filters()
        self._apply_filter()

    # ------------------------------------------------------------------
    # Multi-selection shared by the table and the card grid
    # ------------------------------------------------------------------

    def selected_records(self) -> list[CloneRecord]:
        """Records selected in whichever view is showing."""
        if self._selected_names:
            return [
                record
                for record in self._filtered_clones
                if record.clone_name in self._selected_names
            ]
        return self.get_selected_records()

    def clear_selection(self, widget: Any = None) -> None:
        """Drop the whole selection."""
        if not self._selected_names:
            return
        self._selected_names.clear()
        self._selection_anchor = None
        try:
            native = getattr(getattr(self.table, "_impl", None), "native_table", None)
            if native is not None:
                native.deselectAll_(None)
        except Exception:
            logger.debug("Could not clear the table selection", exc_info=True)
        self._sync_card_selection()
        self.on_table_select(self.table)

    def _sync_card_selection(self) -> None:
        for card in self._grid_cards:
            card.set_selected(card.record.clone_name in self._selected_names)

    def _card_batch_entries(self) -> tuple[cocoa_events.MenuEntry, ...]:
        """Context menu of a card that belongs to a multi-selection."""
        count = len(self._selected_names)
        return (
            cocoa_events.MenuEntry(
                "card_batch_open", t("clone_menu_batch_open", count=count)
            ),
            cocoa_events.MenuEntry(
                "card_batch_close", t("clone_menu_batch_close", count=count)
            ),
            cocoa_events.MenuEntry(
                "card_batch_update",
                t("clone_menu_batch_update", count=count),
                separator=True,
            ),
            cocoa_events.MenuEntry("card_batch_clear", t("selection_clear"), separator=True),
        )

    def _handle_card_batch(self, key: str) -> None:
        if key == "card_batch_open":
            self._spawn(self.on_open_selected())
        elif key == "card_batch_close":
            self._spawn(self.on_close_selected())
        elif key == "card_batch_update":
            self._spawn(self.on_update_clone())
        elif key == "card_batch_clear":
            self.clear_selection()

    def _card_menu_entries_at(
        self, location: tuple[float, float]
    ) -> tuple[cocoa_events.MenuEntry, ...]:
        """Context menu for a right click on the card grid."""
        if self.view_mode != "grid":
            return ()
        frame = cocoa_events.window_frame(self.grid_scroll)
        if frame is None or not cocoa_events.frame_contains(frame, location):
            return ()
        hit = cocoa_events.hit_test_view(self, location)
        if cocoa_events.is_control_view(hit):
            return ()
        name = self._card_at_location(location)
        if name is not None and name in self._selected_names and len(self._selected_names) > 1:
            return self._card_batch_entries()
        return (
            cocoa_events.MenuEntry("select_all", t("selection_select_all")),
            cocoa_events.MenuEntry(
                "clear_selection",
                t("selection_clear"),
                enabled=bool(self._selected_names),
            ),
        )

    def _handle_card_menu(self, key: str) -> None:
        if key == "select_all":
            self._select_all_cards()
        elif key == "clear_selection":
            self.clear_selection()
        else:
            self._handle_card_batch(key)

    def _attach_card_selection(self, card: CloneCard) -> None:
        """Turn a card header into a selection surface (click; drag is global)."""
        name = card.record.clone_name
        cocoa_events.attach_click_selection(
            card.header, lambda intent, clone_name=name: self._on_card_click(clone_name, intent)
        )

    def _on_card_click(
        self,
        clone_name: str,
        intent: str = cocoa_events.SELECT_REPLACE,
    ) -> None:
        if self._click_suppressed:
            # The click that ends a drag sweep must not collapse the range.
            self._click_suppressed = False
            return
        if intent == cocoa_events.SELECT_TOGGLE:
            if clone_name in self._selected_names:
                self._selected_names.discard(clone_name)
            else:
                self._selected_names.add(clone_name)
            self._selection_anchor = clone_name
        elif intent == cocoa_events.SELECT_EXTEND and self._selection_anchor:
            self._select_card_range(clone_name)
            return
        else:
            self._selected_names = {clone_name}
            self._selection_anchor = clone_name
        self._sync_card_selection()

    def _select_card_range(self, clone_name: str) -> None:
        ordered = [record.clone_name for record in self._filtered_clones]
        anchor = self._selection_anchor
        if clone_name not in ordered or anchor not in ordered:
            self._selected_names = {clone_name}
            self._selection_anchor = clone_name
        else:
            start, end = sorted((ordered.index(anchor), ordered.index(clone_name)))
            self._selected_names = set(ordered[start : end + 1])
        self._sync_card_selection()

    def _handle_card_drag(self, state: int, location: tuple[float, float]) -> None:
        """Rubber-band selection over the card grid (grid mode only)."""
        if state == cocoa_events.GESTURE_BEGAN:
            self._click_suppressed = False
            self._drag_moved = False
            self._close_marquee()
            self._drag_active = False
            if self.view_mode != "grid" or not self._marquee_area_contains(location):
                return
            name = self._card_at_location(location)
            intent = cocoa_events.selection_intent()
            if name is not None:
                self._selection_anchor = name
            elif intent == cocoa_events.SELECT_REPLACE and self._selected_names:
                # A plain press on empty space drops the selection, like Finder.
                self.clear_selection()
            self._drag_active = True
            self._marquee_origin = location
            self._marquee_base = (
                set(self._selected_names)
                if intent == cocoa_events.SELECT_EXTEND
                else set()
            )
            self._marquee = cocoa_events.Marquee(self)
            self._apply_marquee(location)
            self._spawn(self._autoscroll_loop())
            return
        if state in (cocoa_events.GESTURE_ENDED, cocoa_events.GESTURE_CANCELLED):
            self._close_marquee()
            if self._drag_active and self._drag_moved:
                # The click that ends a sweep must not collapse the range.
                self._click_suppressed = True
            self._drag_active = False
            self._drag_moved = False
            return
        if not self._drag_active:
            return
        self._apply_marquee(location)

    def _apply_marquee(self, location: tuple[float, float]) -> None:
        """Paint the rubber band and select every card overlapping it."""
        self._marquee_location = location
        origin = self._marquee_origin
        if origin is None:
            return
        rect = cocoa_events.drag_rect(origin, location)
        if self._marquee is not None:
            self._marquee.set_rect(rect)
        if rect[2] < _GRID_MARQUEE_THRESHOLD and rect[3] < _GRID_MARQUEE_THRESHOLD:
            # A plain click: the click recognizer owns the selection.
            return
        self._drag_moved = True
        hits = self._cards_in_rect(rect)
        self._selected_names = self._marquee_base | {
            card.record.clone_name for card in hits
        }
        self._sync_card_selection()

    def _close_marquee(self) -> None:
        marquee = self._marquee
        self._marquee = None
        self._marquee_origin = None
        self._marquee_location = None
        self._marquee_base = set()
        if marquee is not None:
            marquee.close()

    def _cancel_marquee(self) -> None:
        """Abort the rubber band and restore the selection it started from."""
        base = set(self._marquee_base)
        self._close_marquee()
        self._drag_active = False
        self._drag_moved = False
        self._click_suppressed = True
        self._selected_names = base
        self._sync_card_selection()

    def _marquee_area_contains(self, location: tuple[float, float]) -> bool:
        """True when a press starts inside the card grid (blank space included)."""
        frame = cocoa_events.window_frame(self.grid_scroll)
        if frame is None or not cocoa_events.frame_contains(frame, location):
            return False
        hit = cocoa_events.hit_test_view(self, location)
        return not cocoa_events.is_control_view(hit)

    def _cards_in_rect(self, rect: tuple[float, float, float, float]) -> list[CloneCard]:
        """Cards overlapping a window-space rectangle, in grid order."""
        hits: list[CloneCard] = []
        for card in self._grid_cards:
            frame = cocoa_events.window_frame(card)
            if frame is not None and cocoa_events.frame_intersects(frame, rect):
                hits.append(card)
        return hits

    async def _autoscroll_loop(self) -> None:
        """Keep scrolling while the pointer rests near the grid edges."""
        while self._drag_active:
            self._autoscroll_tick()
            await asyncio.sleep(_GRID_AUTOSCROLL_INTERVAL)

    def _autoscroll_tick(self) -> None:
        location = self._marquee_location
        if location is None:
            return
        frame = cocoa_events.window_frame(self.grid_scroll)
        if frame is None:
            return
        bottom = frame[1]
        top = frame[1] + frame[3]
        y = location[1]
        amount = 0.0
        if y > top - _GRID_AUTOSCROLL_EDGE:
            amount = _GRID_AUTOSCROLL_STEP
        elif y < bottom + _GRID_AUTOSCROLL_EDGE:
            amount = -_GRID_AUTOSCROLL_STEP
        if not amount:
            return
        if cocoa_events.scroll_content(self.grid_scroll, amount):
            self._apply_marquee(location)

    def _handle_key(self, key: str, flags: int) -> bool:
        """⌘A selects every card; Esc clears the selection or the rubber band."""
        if self.view_mode != "grid":
            return False
        if flags & cocoa_events.COMMAND_MODIFIER and key.lower() == "a":
            self._select_all_cards()
            return True
        if key == "\x1b":
            if self._drag_active:
                self._cancel_marquee()
                return True
            if self._selected_names:
                self.clear_selection()
                return True
        return False

    def _select_all_cards(self) -> None:
        if not self._grid_cards:
            return
        self._selected_names = {card.record.clone_name for card in self._grid_cards}
        self._selection_anchor = self._grid_cards[0].record.clone_name
        self._sync_card_selection()

    def _spawn(self, coroutine: Any) -> None:
        """Run a coroutine produced by an AppKit callback."""
        try:
            asyncio.get_running_loop().create_task(coroutine)
        except RuntimeError:
            close = getattr(coroutine, "close", None)
            if close is not None:
                close()
            logger.debug("No running event loop for a grid task")

    def _card_at_location(
        self,
        location: tuple[float, float],
        *,
        header_only: bool = False,
    ) -> str | None:
        """Resolve the clone card under a window-space point."""
        for card in self._grid_cards:
            target = card.header if header_only else card
            frame = cocoa_events.window_frame(target)
            if frame is not None and cocoa_events.frame_contains(frame, location):
                return card.record.clone_name
        return None

    def _icon_for_clone(self, clone_name: Any) -> Any | None:
        """Resolve the app icon for a table cell, caching it by clone name."""
        name = str(clone_name or "")
        if name in self._icon_by_clone:
            return self._icon_by_clone[name]
        record = self._records_by_name.get(name)
        icon = (
            cocoa_events.load_app_icon(record.dest_path, size=TABLE_ICON_SIZE)
            if record is not None
            else None
        )
        self._icon_by_clone[name] = icon
        return icon

    def _sync_env_filters(self) -> None:
        """Offer one filter entry per environment alongside the strategy filters."""
        env_names = sorted(
            {
                getattr(record, "env_group", "") or ""
                for record in self._raw_clones
            }
            - {""}
        )
        labels = [self.filter_all, self.filter_hard, self.filter_soft, self.filter_proxy]
        self._env_filter_labels = {}
        for env_name in env_names:
            label = t("view_clones_filter_env", name=env_name)
            self._env_filter_labels[label] = env_name
            labels.append(label)
        self.top_bar.update_filter_items(labels)
        if self.selected_filter not in labels:
            self.selected_filter = self.filter_all
            if getattr(self.top_bar, "select_filter", None) is not None:
                self.top_bar.select_filter.value = self.filter_all

    async def on_launch_clone(self, record: Optional[CloneRecord]):
        if not record:
            return
        dest_path = Path(record.dest_path)
        logger.info(f"Launching clone '{record.clone_name}' at '{dest_path}'")
        if not dest_path.exists():
            logger.error(f"Cannot launch clone '{record.clone_name}': file does not exist at '{dest_path}'")
            if self.app_instance and hasattr(self.app_instance, "main_window"):
                await self.app_instance.main_window.error_dialog(
                    t("dialog_launch_error_title"),
                    t("dialog_launch_error_not_found", path=str(dest_path)),
                )
            return

        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, lambda: subprocess.Popen(["open", str(dest_path)]))
            logger.info(f"Successfully triggered open for clone '{record.clone_name}'")
            await self._record_opened(record.clone_name)
        except Exception as e:
            logger.error(f"Failed to launch clone '{record.clone_name}': {e}")
            if self.app_instance and hasattr(self.app_instance, "main_window"):
                await self.app_instance.main_window.error_dialog(t("dialog_launch_error_title"), t("dialog_launch_error_failed", error=str(e)))

    async def on_open_clone_dir(self, record: Optional[CloneRecord]):
        if not record:
            return
        dest_path = Path(record.dest_path)
        logger.info(f"Opening directory for clone '{record.clone_name}' at '{dest_path}'")
        loop = asyncio.get_running_loop()
        try:
            if dest_path.exists():
                await loop.run_in_executor(None, lambda: subprocess.Popen(["open", "-R", str(dest_path)]))
            elif dest_path.parent.exists():
                await loop.run_in_executor(None, lambda: subprocess.Popen(["open", str(dest_path.parent)]))
            else:
                logger.error(f"Cannot open directory for clone '{record.clone_name}': path does not exist at '{dest_path}'")
                if self.app_instance and hasattr(self.app_instance, "main_window"):
                    await self.app_instance.main_window.error_dialog(
                        t("dialog_launch_error_title"),
                        t("dialog_launch_error_not_found", path=str(dest_path)),
                    )
        except Exception as e:
            logger.error(f"Failed to open directory for clone '{record.clone_name}': {e}")
            if self.app_instance and hasattr(self.app_instance, "main_window"):
                await self.app_instance.main_window.error_dialog(t("dialog_launch_error_title"), str(e))

    async def on_detail_clone(self, record: Optional[CloneRecord]):
        if not record:
            return
        win = CloneDetailWindow(
            record=record,
            on_edit=lambda r: asyncio.create_task(self.on_edit_clone(r)),
            on_update=lambda r: asyncio.create_task(self.on_update_clone(r)),
            on_reveal=lambda r: asyncio.create_task(self.on_open_clone_dir(r)),
        )
        win.show()

    async def on_edit_clone(self, record: Optional[CloneRecord]):
        if not record:
            return

        async def _save_cb(updated_record: CloneRecord):
            await self.clone_service.update_clone_record(updated_record)
            if (
                updated_record.language != record.language
                or updated_record.display_name != record.display_name
                or updated_record.proxy_summary != record.proxy_summary
                or updated_record.proxy_enabled != record.proxy_enabled
                or getattr(win, "credential_changed", False)
            ):
                try:
                    await self.clone_service.update_clone(updated_record.clone_name)
                except Exception as e:
                    logger.warning(f"Failed to auto-update clone after edit: {e}")
            await self.refresh_clones()

        win = CloneEditWindow(record=record, on_save=_save_cb)
        win.show()

    async def on_open_selected(self) -> None:
        """Open every selected clone (single selection keeps the old behaviour)."""
        records = self.selected_records()
        if not records:
            return
        if len(records) == 1:
            await self.on_launch_clone(records[0])
            return

        loop = asyncio.get_running_loop()
        errors: list[tuple[str, str]] = []
        opened: list[str] = []
        total = len(records)
        for index, record in enumerate(records, start=1):
            self.btn_launch_table.text = t(
                "btn_opening_progress", current=index, total=total
            )
            path = Path(record.dest_path)
            if not path.exists():
                errors.append((record.clone_name, t("dialog_launch_error_not_found", path=str(path))))
                continue
            try:
                await loop.run_in_executor(
                    None, lambda target=path: subprocess.Popen(["open", str(target)])
                )
                opened.append(record.clone_name)
            except Exception as exc:
                logger.error("Failed to launch clone '%s': %s", record.clone_name, exc)
                errors.append((record.clone_name, str(exc)))
        self.btn_launch_table.text = t("btn_batch_open", count=total)

        for clone_name in opened:
            await self._record_opened(clone_name)

        if errors and self.app_instance and hasattr(self.app_instance, "main_window"):
            err_details = "\n".join(f"- {name}: {err}" for name, err in errors)
            await self.app_instance.main_window.error_dialog(
                t("dialog_batch_summary_title"),
                t(
                    "dialog_batch_summary_msg",
                    success=total - len(errors),
                    failed=len(errors),
                    errors=err_details,
                ),
            )

    async def on_close_selected(self) -> None:
        """Quit every selected clone that is currently running."""
        records = self.selected_records()
        if not records:
            return
        loop = asyncio.get_running_loop()
        try:
            running = await loop.run_in_executor(None, running_clone_names, records)
        except Exception as exc:  # pragma: no cover - ps should always answer
            logger.error("Could not read running clones: %s", exc)
            running = set()
        targets = [record for record in records if record.clone_name in running]
        if not targets:
            if self.app_instance and hasattr(self.app_instance, "main_window"):
                await self.app_instance.main_window.info_dialog(
                    t("clone_close_none_title"), t("clone_close_none_msg")
                )
            return

        errors: list[tuple[str, str]] = []
        total = len(targets)
        for index, record in enumerate(targets, start=1):
            if total > 1:
                self.btn_close_table.text = t(
                    "btn_closing_progress", current=index, total=total
                )
            try:
                stopped = await loop.run_in_executor(
                    None, quit_clone, record.dest_path
                )
                if not stopped:
                    errors.append((record.clone_name, t("clone_close_still_running")))
            except Exception as exc:
                logger.error("Failed to close clone '%s': %s", record.clone_name, exc)
                errors.append((record.clone_name, str(exc)))
        self.btn_close_table.text = (
            t("btn_batch_close", count=total) if total > 1 else t("btn_close")
        )
        if errors and self.app_instance and hasattr(self.app_instance, "main_window"):
            err_details = "\n".join(f"- {name}: {err}" for name, err in errors)
            if total > 1:
                await self.app_instance.main_window.error_dialog(
                    t("dialog_batch_summary_title"),
                    t(
                        "dialog_batch_summary_msg",
                        success=total - len(errors),
                        failed=len(errors),
                        errors=err_details,
                    ),
                )
            else:
                await self.app_instance.main_window.error_dialog(
                    t("environment_error_title"), err_details
                )

    async def on_update_clone(self, target: Optional[CloneRecord | list[CloneRecord]] = None):
        if target is None:
            records = self.selected_records()
        elif isinstance(target, CloneRecord):
            records = [target]
        else:
            records = list(target)

        if not records:
            return

        active_records = [r for r in records if r.clone_name not in self._busy_clones]
        if not active_records:
            return

        for r in active_records:
            self._busy_clones.add(r.clone_name)

        total = len(active_records)
        failed_list: list[tuple[str, str]] = []

        if hasattr(self, "btn_update_table") and self.btn_update_table:
            self.btn_update_table.enabled = False

        try:
            for idx, r in enumerate(active_records, 1):
                if hasattr(self, "btn_update_table") and self.btn_update_table:
                    if total > 1:
                        self.btn_update_table.text = t("btn_updating_progress", current=idx, total=total)
                    else:
                        self.btn_update_table.text = t("btn_updating")
                try:
                    await self.clone_service.update_clone(r.clone_name)
                except Exception as e:
                    logger.error(f"Failed to update clone '{r.clone_name}': {e}")
                    failed_list.append((r.clone_name, str(e)))
            await self.refresh_clones()
        finally:
            for r in active_records:
                self._busy_clones.discard(r.clone_name)
            if hasattr(self, "btn_update_table") and self.btn_update_table:
                self.btn_update_table.text = t("btn_update")
            self.on_table_select(self.table)

        if failed_list and self.app_instance and hasattr(self.app_instance, "main_window"):
            succ_count = total - len(failed_list)
            err_details = "\n".join(f"- {name}: {err}" for name, err in failed_list)
            if total > 1:
                await self.app_instance.main_window.error_dialog(
                    t("dialog_batch_summary_title"),
                    t("dialog_batch_summary_msg", success=succ_count, failed=len(failed_list), errors=err_details),
                )
            else:
                await self.app_instance.main_window.error_dialog(
                    t("dialog_update_error_title"),
                    failed_list[0][1],
                )

    async def on_delete_clone(self, target: Optional[CloneRecord | list[CloneRecord]] = None):
        if target is None:
            records = self.selected_records()
        elif isinstance(target, CloneRecord):
            records = [target]
        else:
            records = list(target)

        if not records:
            return

        active_records = [r for r in records if r.clone_name not in self._busy_clones]
        if not active_records:
            return

        total = len(active_records)
        delete_data = False

        if self.app_instance and hasattr(self.app_instance, "main_window"):
            if total == 1:
                record = active_records[0]
                confirmed = await self.app_instance.main_window.confirm_dialog(
                    t("dialog_delete_confirm_title"),
                    t("dialog_delete_confirm_msg", name=record.clone_name),
                )
                if not confirmed:
                    return

                delete_data = await self.app_instance.main_window.confirm_dialog(
                    t("dialog_delete_data_confirm_title"),
                    t("dialog_delete_data_confirm_msg", path=record.data_dir),
                )
            else:
                names_summary = ", ".join(r.clone_name for r in active_records[:6])
                if total > 6:
                    names_summary += f" ... (+{total - 6})"
                confirmed = await self.app_instance.main_window.confirm_dialog(
                    t("dialog_batch_delete_confirm_title"),
                    t("dialog_batch_delete_confirm_msg", count=total, names=names_summary),
                )
                if not confirmed:
                    return

                delete_data = await self.app_instance.main_window.confirm_dialog(
                    t("dialog_batch_delete_data_confirm_title"),
                    t("dialog_batch_delete_data_confirm_msg", count=total),
                )

        for r in active_records:
            self._busy_clones.add(r.clone_name)

        failed_list: list[tuple[str, str]] = []
        if hasattr(self, "btn_delete_table") and self.btn_delete_table:
            self.btn_delete_table.enabled = False

        try:
            for idx, r in enumerate(active_records, 1):
                if hasattr(self, "btn_delete_table") and self.btn_delete_table:
                    if total > 1:
                        self.btn_delete_table.text = t("btn_deleting_progress", current=idx, total=total)
                    else:
                        self.btn_delete_table.text = t("btn_delete")
                try:
                    await self.clone_service.remove_clone(r.clone_name, with_data=delete_data)
                except Exception as e:
                    logger.error(f"Failed to delete clone '{r.clone_name}': {e}")
                    failed_list.append((r.clone_name, str(e)))
            await self.refresh_clones()
        finally:
            for r in active_records:
                self._busy_clones.discard(r.clone_name)
            if hasattr(self, "btn_delete_table") and self.btn_delete_table:
                self.btn_delete_table.text = t("btn_delete")
            self.on_table_select(self.table)

        if failed_list and self.app_instance and hasattr(self.app_instance, "main_window"):
            succ_count = total - len(failed_list)
            err_details = "\n".join(f"- {name}: {err}" for name, err in failed_list)
            if total > 1:
                await self.app_instance.main_window.error_dialog(
                    t("dialog_batch_summary_title"),
                    t("dialog_batch_summary_msg", success=succ_count, failed=len(failed_list), errors=err_details),
                )
            else:
                await self.app_instance.main_window.error_dialog(
                    t("dialog_error_title"),
                    failed_list[0][1],
                )

