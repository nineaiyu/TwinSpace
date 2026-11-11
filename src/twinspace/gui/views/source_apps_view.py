"""Source Apps view: clones grouped by the application they were cloned from.

The clone page is a flat list; this page answers the "one source app, many
clones" question — how many clones exist for WeChat/Chrome, which are running,
how much disk they occupy — with open/close/update actions for the whole group.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from typing import Any, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.app_version import update_statuses
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.state import CloneRecord, quit_clones, running_clone_names
from twinspace.gui import cocoa_events
from twinspace.gui.cocoa_events import MenuEntry
from twinspace.gui.components.top_bar import TopHeaderBar
from twinspace.gui.services.app_monitor import AppLifecycleMonitor, enclosing_bundle
from twinspace.gui.services.data_size import compute_data_sizes, format_size
from twinspace.gui.theme import Theme

logger = get_logger("gui.source_apps")


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

    def clone_names(self) -> list[str]:
        return [record.clone_name for record in self.records]


class SourceAppCard(toga.Box):
    """One source application and all of its clones."""

    def __init__(self, group: _SourceGroup, view: "SourceAppsView"):
        super().__init__(
            style=Pack(
                direction=COLUMN,
                margin=(6, 8, 8, 8),
                background_color=Theme.BG_CARD,
            )
        )
        self.group = group
        self._view = view

        header = toga.Box(
            style=Pack(direction=ROW, align_items=CENTER, margin=(12, 14, 6, 14))
        )
        icon = cocoa_events.load_app_icon(group.source_path, size=48)
        if icon is not None:
            header.add(
                toga.ImageView(icon, style=Pack(width=48, height=48, margin_right=12))
            )
        title_box = toga.Box(style=Pack(direction=COLUMN, flex=1))
        title_box.add(
            toga.Label(
                group.source_app,
                style=Pack(font_weight="bold", font_size=15, color=Theme.TEXT_PRIMARY),
            )
        )
        title_box.add(
            toga.Label(
                group.bundle_id,
                style=Pack(font_size=11, color=Theme.TEXT_TERTIARY, margin_top=1),
            )
        )
        header.add(title_box)
        self.label_pill = toga.Label(
            "",
            style=Pack(
                font_size=12, font_weight="bold", color=Theme.TEXT_MUTED, margin_left=8
            ),
        )
        header.add(self.label_pill)
        self.add(header)

        self.label_stats = toga.Label(
            "", style=Pack(font_size=12, color=Theme.TEXT_MUTED, margin=(0, 14, 4, 14))
        )
        self.add(self.label_stats)

        actions = toga.Box(
            style=Pack(direction=ROW, align_items=CENTER, margin=(2, 14, 8, 14))
        )
        btn_open = toga.Button(
            t("environment_btn_open_all"),
            on_press=lambda w: view.dispatch_action("open_all", group),
            style=Pack(height=28, font_size=12, font_weight="bold", margin_right=6),
        )
        cocoa_events.configure_button_icon(btn_open, "play.fill")
        btn_close = toga.Button(
            t("environment_btn_close_all"),
            on_press=lambda w: view.dispatch_action("close_all", group),
            style=Pack(height=28, font_size=12, margin_right=6),
        )
        cocoa_events.configure_button_icon(btn_close, "stop.fill")
        btn_update = toga.Button(
            t("environment_btn_update_all"),
            on_press=lambda w: view.dispatch_action("update_all", group),
            style=Pack(height=28, font_size=12),
        )
        cocoa_events.configure_button_icon(btn_update, "arrow.clockwise")
        actions.add(btn_open)
        actions.add(btn_close)
        actions.add(btn_update)
        self.add(actions)

        self.chips_box = toga.Box(style=Pack(direction=ROW, margin=(0, 14, 12, 14)))
        self.chip_buttons: dict[str, toga.Button] = {}
        for record in group.records:
            chip = toga.Button(
                record.clone_name,
                on_press=lambda w, r=record: view.dispatch_launch(r),
                style=Pack(height=26, font_size=11.5, margin_right=6),
            )
            self.chip_buttons[record.clone_name] = chip
            self.chips_box.add(chip)
        self.add(self.chips_box)

        cocoa_events.attach_tile_interactions(
            self,
            on_hover=self._handle_hover,
            menu_entries=self._menu_entries(),
            menu_handler=self._handle_menu,
        )

    # -- menu ----------------------------------------------------------------

    def _menu_entries(self) -> tuple[MenuEntry, ...]:
        return (
            MenuEntry("open_all", t("environment_btn_open_all")),
            MenuEntry("close_all", t("environment_btn_close_all")),
            MenuEntry("update_all", t("environment_btn_update_all"), separator=True),
            MenuEntry("reveal", t("sources_menu_reveal_source")),
        )

    def _handle_menu(self, key: str) -> None:
        self._view.dispatch_action(key, self.group)

    def _handle_hover(self, active: bool) -> None:
        cocoa_events.set_hover_background(self, bool(active), Theme.BG_HOVER, radius=14.0)

    # -- in-place patches ------------------------------------------------------

    def set_running(self, running: set[str]) -> None:
        """Repaint the running pill and the per-clone chips in place."""
        count = sum(1 for r in self.group.records if r.clone_name in running)
        self.label_pill.text = t("sources_running_pill", count=count)
        self.label_pill.style.color = Theme.BTN_SUCCESS if count else Theme.TEXT_MUTED
        for clone_name, chip in self.chip_buttons.items():
            prefix = "● " if clone_name in running else ""
            chip.text = f"{prefix}{clone_name}"

    def set_stats(self, size: int, updates: int) -> None:
        parts = [t("sources_stat_clones", count=len(self.group.records)), format_size(size)]
        if updates:
            parts.append(t("sources_stat_updates", count=updates))
        self.label_stats.text = " · ".join(parts)


class SourceAppsView(toga.Box):
    """Clones grouped by source application, with group-level batch actions."""

    def __init__(self, clone_service: Any, app: Optional[toga.App] = None):
        super().__init__(
            style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_WINDOW)
        )
        self.clone_service = clone_service
        self.app_instance = app

        self.top_bar = TopHeaderBar(
            title=t("sources_title", count=0),
            refresh_symbol="arrow.clockwise",
            on_refresh=self.on_refresh_sources,
        )
        self.add(self.top_bar)

        self.content_container = toga.Box(
            style=Pack(direction=COLUMN, flex=1, margin=(0, 24, 20, 24))
        )
        self.add(self.content_container)

        self.list_box = toga.Box(style=Pack(direction=COLUMN, flex=1))
        self.scroll = toga.ScrollContainer(
            content=self.list_box, horizontal=False, style=Pack(flex=1)
        )
        self._mounted: str | None = None

        self._records: list[CloneRecord] = []
        self._groups: list[_SourceGroup] = []
        self._group_of: dict[str, str] = {}
        self._clone_by_path: dict[str, str] = {}
        self._cards: dict[str, tuple[SourceAppCard, tuple]] = {}
        self._running: set[str] = set()
        self._sizes: dict[str, int] = {}
        self._updates: dict[str, bool] = {}
        self._busy = False
        self._pending_refresh = False

        self._monitor = AppLifecycleMonitor.shared()
        self._monitor.subscribe(self)

        self._empty_box = toga.Box(
            style=Pack(direction=COLUMN, flex=1, align_items=CENTER)
        )
        self._empty_box.add(toga.Box(style=Pack(flex=1)))
        self._empty_box.add(
            toga.Label(
                t("sources_empty_hint"),
                style=Pack(font_size=14, color=Theme.TEXT_MUTED),
            )
        )
        self._empty_box.add(toga.Box(style=Pack(flex=2)))

    # -- data ------------------------------------------------------------

    async def refresh_sources(self) -> None:
        if self._busy:
            self._pending_refresh = True
            return
        self._busy = True
        try:
            loop = asyncio.get_running_loop()
            self._records = await loop.run_in_executor(
                None, self.clone_service.list_clones
            )
            self._rebuild_groups()
            try:
                statuses = await loop.run_in_executor(
                    None, update_statuses, self._records
                )
                self._updates = {
                    record.clone_name: bool(status.needs_update)
                    for record, status in zip(self._records, statuses)
                }
            except Exception:
                self._updates = {}
            running = self._snapshot_running()
            if running is None:
                try:
                    running = await loop.run_in_executor(
                        None, running_clone_names, self._records
                    )
                except Exception:
                    running = set()
            self._running = running
            self._sync_cards()
        finally:
            self._busy = False
        self._schedule_size_fill()
        if self._pending_refresh:
            self._pending_refresh = False
            await self.refresh_sources()

    def on_refresh_sources(self, widget: Any = None) -> None:
        self._dispatch_async(self.refresh_sources())

    def _rebuild_groups(self) -> None:
        groups: dict[str, _SourceGroup] = {}
        for record in self._records:
            key = _normalise_path(record.source_path)
            if not key:
                key = f"name:{record.source_app}"
            group = groups.get(key)
            if group is None:
                group = _SourceGroup(key, record.source_app)
                group.bundle_id = record.bundle_id
                groups[key] = group
            if not group.bundle_id:
                group.bundle_id = record.bundle_id
            group.records.append(record)
        for group in groups.values():
            group.records.sort(key=lambda r: r.clone_name.lower())
        self._groups = sorted(groups.values(), key=lambda g: g.source_app.lower())
        self._group_of = {}
        self._clone_by_path = {}
        for group in self._groups:
            for record in group.records:
                self._group_of[record.clone_name] = group.source_path
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

    def _mount_content(self, widget: toga.Widget) -> None:
        children = self.content_container.children
        if len(children) == 1 and children[0] is widget:
            return
        while len(self.content_container.children) > 0:
            self.content_container.remove(self.content_container.children[0])
        self.content_container.add(widget)

    def _sync_cards(self) -> None:
        self._update_title()
        live_keys = {group.source_path for group in self._groups}
        for key in [key for key in self._cards if key not in live_keys]:
            card, _ = self._cards.pop(key)
            parent = getattr(card, "parent", None)
            if parent is not None:
                parent.remove(card)

        if not self._groups:
            self._mount_content(self._empty_box)
            self._mounted = "empty"
            return

        if self._mounted != "sources":
            self._mount_content(self.scroll)
            self._mounted = "sources"

        mounted_cards = {card for card, _ in self._cards.values()}
        for child in list(self.list_box.children):
            if child not in mounted_cards:
                self.list_box.remove(child)

        for group in self._groups:
            signature = self._group_signature(group)
            entry = self._cards.get(group.source_path)
            if entry is None or entry[1] != signature:
                card = SourceAppCard(group, self)
                self._cards[group.source_path] = (card, signature)
            else:
                card = entry[0]
                card.group = group
            if getattr(card, "parent", None) is not self.list_box:
                parent = getattr(card, "parent", None)
                if parent is not None:
                    parent.remove(card)
                self.list_box.add(card)
            card.set_running(self._running)
            card.set_stats(self._group_size(group), self._group_updates(group))

    def _group_signature(self, group: _SourceGroup) -> tuple:
        return (group.source_app, group.bundle_id, tuple(group.clone_names()))

    def _group_size(self, group: _SourceGroup) -> int:
        return sum(self._sizes.get(record.clone_name, 0) for record in group.records)

    def _group_updates(self, group: _SourceGroup) -> int:
        return sum(
            1 for record in group.records if self._updates.get(record.clone_name)
        )

    def _update_title(self) -> None:
        title = t("sources_title", count=len(self._groups))
        running = len(self._running)
        if running:
            title += t("title_running_suffix", running=running)
        label = getattr(self.top_bar, "label_title", None)
        if label is None or label.text != title:
            self.top_bar.update_title(title)

    def _schedule_size_fill(self) -> None:
        if not self._records:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._sizes = compute_data_sizes(self._records)
            self._patch_stats()
            return
        loop.run_in_executor(None, self._apply_sizes, loop)

    def _apply_sizes(self, loop: asyncio.AbstractEventLoop) -> None:
        sizes = compute_data_sizes(self._records)
        loop.call_soon_threadsafe(self._set_sizes, sizes)

    def _set_sizes(self, sizes: dict[str, int]) -> None:
        self._sizes = sizes
        self._patch_stats()

    def _patch_stats(self) -> None:
        for group in self._groups:
            entry = self._cards.get(group.source_path)
            if entry is not None:
                entry[0].set_stats(
                    self._group_size(group), self._group_updates(group)
                )

    # -- actions ---------------------------------------------------------------

    def dispatch_action(self, key: str, group: _SourceGroup) -> None:
        handler = {
            "open_all": self._open_all,
            "close_all": self._close_all,
            "update_all": self._update_all,
            "reveal": self._reveal,
        }.get(key)
        if handler is not None:
            self._dispatch_async(handler(group))

    def dispatch_launch(self, record: CloneRecord) -> None:
        self._dispatch_async(self._launch(record))

    def _dispatch_async(self, coro) -> None:
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            logger.debug("No running loop for source app action")

    async def _launch(self, record: CloneRecord) -> None:
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: subprocess.Popen(["open", str(record.dest_path)])
            )
            self._running.add(record.clone_name)
            self._patch_running()
            self._update_title()
        except Exception as exc:
            logger.warning("Could not launch %s: %s", record.clone_name, exc)

    async def _open_all(self, group: _SourceGroup) -> None:
        loop = asyncio.get_running_loop()

        def _open():
            errors = []
            for record in group.records:
                try:
                    subprocess.Popen(["open", str(record.dest_path)])
                except Exception as exc:
                    errors.append(f"{record.clone_name}: {exc}")
            return errors

        errors = await loop.run_in_executor(None, _open)
        self._running.update(record.clone_name for record in group.records)
        self._patch_running()
        self._update_title()
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
        self._patch_running()
        self._update_title()
        if failed:
            await self._report_errors([f"{name}: still running" for name in failed])

    async def _update_all(self, group: _SourceGroup) -> None:
        errors: list[str] = []
        for record in group.records:
            try:
                await self.clone_service.update_clone(record.clone_name)
            except Exception as exc:
                errors.append(f"{record.clone_name}: {exc}")
        await self.refresh_sources()
        await self._report_errors(errors)

    async def _reveal(self, group: _SourceGroup) -> None:
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: subprocess.Popen(["open", "-R", group.source_path])
        )

    async def _report_errors(self, errors: list[str]) -> None:
        if not errors or self.app_instance is None:
            return
        try:
            await self.app_instance.main_window.error_dialog(
                t("environment_error_title"), "\n".join(errors)
            )
        except Exception:
            logger.debug("Could not show source app error dialog", exc_info=True)

    def on_window_resize(self, width: int) -> None:  # pragma: no cover
        pass

    # -- live updates ------------------------------------------------------------

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
        self._patch_running()
        self._update_title()

    def _patch_running(self) -> None:
        for card, _signature in self._cards.values():
            card.set_running(self._running)

    def focus_search(self) -> None:  # pragma: no cover - no search on this page
        pass
