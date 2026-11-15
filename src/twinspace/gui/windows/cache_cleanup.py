"""Storage cleanup window: review clone caches and delete the selected ones.

The scan itself lives in :mod:`twinspace.core.cleanup` (whitelisted paths,
realpath containment, symlink refusal). This module only presents the result:
every directory is a selectable row with its clone, path and size, grouped by
category. Nothing is deleted without an explicit confirmation.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.cleanup import (
    CATEGORY_CACHE,
    CATEGORY_CRASH,
    CATEGORY_LOGS,
    CATEGORY_ORDER,
    CATEGORY_ORPHAN,
    CATEGORY_PACKAGE,
    CATEGORY_TMP,
    CacheEntry,
    CleanupReport,
    delete_entries,
    scan_cleanup,
)
from twinspace.core.config import get_base_dir
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.state import running_clone_names
from twinspace.gui import cocoa_events
from twinspace.gui.components.wrapping_label import WrappingLabel
from twinspace.gui.patch_cocoa import (
    configure_cocoa_danger_button,
    configure_cocoa_window,
)
from twinspace.gui.services.data_size import format_size, invalidate_size_cache
from twinspace.gui.theme import Theme

logger = get_logger("gui.cache_cleanup")

# Categories checked by default: pure caches and throwaway files. Package
# caches and orphaned data stay unchecked — they are safe too, but re-download
# or deserve a second look respectively.
_DEFAULT_SELECTED = {CATEGORY_CACHE, CATEGORY_TMP, CATEGORY_LOGS, CATEGORY_CRASH}

_CATEGORY_HINTS = {
    CATEGORY_PACKAGE: "storage_cleanup_hint_package",
    CATEGORY_ORPHAN: "storage_cleanup_hint_orphan",
}

_CHECKED = "☑"
_UNCHECKED = "☐"


class _SelectableRow:
    """One directory row with a clickable checkbox glyph."""

    def __init__(
        self,
        entry: CacheEntry,
        on_toggle: Callable[[], None],
    ):
        self.entry = entry
        self.selected = entry.category in _DEFAULT_SELECTED
        self._on_toggle = on_toggle

        self.widget = toga.Box(
            style=Pack(direction=ROW, align_items=CENTER, margin=(2, 0, 2, 0))
        )
        self.mark = toga.Label(
            _CHECKED if self.selected else _UNCHECKED,
            style=Pack(
                width=20,
                font_size=14,
                color=Theme.ACCENT_BLUE if self.selected else Theme.TEXT_TERTIARY,
                margin_right=6,
            ),
        )
        self.widget.add(self.mark)

        info = toga.Box(style=Pack(direction=COLUMN, flex=1))
        info.add(
            toga.Label(
                f"{entry.clone_name or t('storage_cleanup_orphan_label')} · "
                f"{entry.detail or entry.path.name}",
                style=Pack(font_size=12.5, color=Theme.TEXT_PRIMARY),
            )
        )
        info.add(
            toga.Label(
                self._relative_path(entry.path),
                style=Pack(font_size=10.5, color=Theme.TEXT_TERTIARY, margin_top=1),
            )
        )
        self.widget.add(info)
        self.widget.add(
            toga.Label(
                format_size(entry.size),
                style=Pack(
                    font_size=12.5,
                    font_weight="bold",
                    color=Theme.TEXT_PRIMARY,
                    margin_left=10,
                ),
            )
        )
        # The whole row is the hit target; AppKit walks the child views too.
        cocoa_events.attach_tile_interactions(
            self.widget,
            on_click=self.toggle,
            on_hover=self._handle_hover,
        )

    def _handle_hover(self, active: bool) -> None:
        cocoa_events.set_hover_background(
            self.widget, bool(active), Theme.BG_HOVER, radius=8.0
        )

    @staticmethod
    def _relative_path(path: Path) -> str:
        try:
            return str(path.relative_to(get_base_dir()))
        except (ValueError, OSError):
            return str(path)

    def toggle(self) -> None:
        self.set_selected(not self.selected)

    def set_selected(self, selected: bool, *, notify: bool = True) -> None:
        selected = bool(selected)
        if selected == self.selected:
            return
        self.selected = selected
        self._paint_mark()
        if notify:
            self._on_toggle()

    def _paint_mark(self) -> None:
        """Flip the checkbox glyph without relaying out the whole list.

        ``Label.text`` triggers a Toga refresh (rehint + layout of the scroll
        content); doing that for every row turned one "select all" click into
        seconds of work. The glyph label has a fixed width, so writing the
        native string directly is safe and keeps the toggle instant.
        """
        text = _CHECKED if self.selected else _UNCHECKED
        native = getattr(getattr(self.mark, "_impl", None), "native", None)
        if native is not None:
            try:
                native.setStringValue_(text)
                self.mark.style.color = (
                    Theme.ACCENT_BLUE if self.selected else Theme.TEXT_TERTIARY
                )
                return
            except Exception:
                logger.debug("Native checkbox paint failed", exc_info=True)
        self.mark.text = text
        self.mark.style.color = (
            Theme.ACCENT_BLUE if self.selected else Theme.TEXT_TERTIARY
        )


class CacheCleanupWindow(toga.Window):
    """Per-directory cache review with selectable cleanup."""

    def __init__(
        self,
        app: Any,
        clone_service: Any,
        *,
        clone_names: Optional[Iterable[str]] = None,
        on_cleaned: Optional[Callable[[], Any]] = None,
        auto_scan: bool = True,
    ):
        super().__init__(title=t("storage_cleanup_title"), size=(820, 660))
        configure_cocoa_window(self, floating=False)
        # NOTE: never assign to `self._app` — toga.Window keeps its App there.
        self._host_app = app
        self._service = clone_service
        self._clone_names = set(clone_names) if clone_names is not None else None
        self._on_cleaned = on_cleaned
        self._entries: list[CacheEntry] = []
        self._rows: list[_SelectableRow] = []
        self._busy = False
        self._scan_token = 0

        root = toga.Box(
            style=Pack(
                direction=COLUMN,
                margin=(16, 18, 14, 18),
                background_color=Theme.BG_WINDOW,
            )
        )
        root.add(
            WrappingLabel(
                t("storage_cleanup_intro"),
                style=Pack(font_size=12, color=Theme.TEXT_MUTED),
            )
        )

        header = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_top=10))
        self.indicator = toga.ActivityIndicator(style=Pack(width=16, height=16))
        indicator_box = toga.Box(
            style=Pack(direction=ROW, width=20, align_items=CENTER)
        )
        indicator_box.add(self.indicator)
        header.add(indicator_box)
        self.label_summary = toga.Label(
            "",
            style=Pack(font_size=13, font_weight="bold", color=Theme.TEXT_PRIMARY),
        )
        header.add(self.label_summary)
        header.add(toga.Box(style=Pack(flex=1)))
        self.label_selected = toga.Label(
            "",
            style=Pack(font_size=12, color=Theme.TEXT_SECONDARY),
        )
        header.add(self.label_selected)
        root.add(header)

        self.label_status = toga.Label(
            "",
            style=Pack(font_size=11.5, color=Theme.TEXT_TERTIARY, margin_top=4),
        )
        root.add(self.label_status)

        self.scroll = toga.ScrollContainer(
            horizontal=False, style=Pack(flex=1, margin_top=10)
        )
        self.rows_box = toga.Box(style=Pack(direction=COLUMN))
        self.scroll.content = self.rows_box
        root.add(self.scroll)

        buttons = toga.Box(
            style=Pack(direction=ROW, align_items=CENTER, margin_top=12)
        )
        self.btn_all = toga.Button(
            t("storage_cleanup_btn_select_all"),
            on_press=self._on_select_all,
            style=Pack(height=28, font_size=12.5, margin_right=6),
        )
        self.btn_none = toga.Button(
            t("storage_cleanup_btn_select_none"),
            on_press=self._on_select_none,
            style=Pack(height=28, font_size=12.5, margin_right=6),
        )
        self.btn_rescan = toga.Button(
            t("storage_cleanup_btn_rescan"),
            on_press=lambda widget: self.scan(),
            style=Pack(height=28, font_size=12.5),
        )
        cocoa_events.configure_button_icon(self.btn_rescan, "arrow.clockwise")
        self.btn_clean = toga.Button(
            t("storage_cleanup_btn_clean"),
            on_press=lambda widget: self._schedule(self._clean_selected()),
            enabled=False,
            style=Pack(height=28, font_size=12.5, font_weight="bold"),
        )
        configure_cocoa_danger_button(self.btn_clean)
        buttons.add(self.btn_all)
        buttons.add(self.btn_none)
        buttons.add(self.btn_rescan)
        buttons.add(toga.Box(style=Pack(flex=1)))
        buttons.add(self.btn_clean)
        root.add(buttons)

        self.content = root
        if auto_scan:
            self.scan()

    # -- scanning --------------------------------------------------------------

    def scan(self) -> None:
        """Start a background scan (sizes are walked on a worker thread)."""
        if self._busy:
            return
        self._scan_token += 1
        token = self._scan_token
        self._set_busy(True)
        self._clear_rows()
        self._entries = []
        self._rows = []
        self.label_summary.text = ""
        self.label_selected.text = ""
        self.label_status.text = t("storage_cleanup_scanning")
        self._set_indicator(True)
        self._schedule(self._scan_async(token))

    @staticmethod
    def _schedule(awaitable: Any) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            close = getattr(awaitable, "close", None)
            if close is not None:
                close()
            return
        loop.create_task(awaitable)

    async def _scan_async(self, token: int) -> None:
        loop = asyncio.get_running_loop()
        try:
            records = await self._service.list_clones()
            if self._clone_names is not None:
                records = [
                    record
                    for record in records
                    if record.clone_name in self._clone_names
                ]
            try:
                running = await loop.run_in_executor(
                    None, running_clone_names, records
                )
            except Exception:
                logger.debug("Running detection failed", exc_info=True)
                running = set()
            report = await loop.run_in_executor(
                None,
                lambda: scan_cleanup(records, skip_clones=running),
            )
        except Exception as exc:
            logger.warning("Cache scan failed: %s", exc)
            if token == self._scan_token:
                self.label_status.text = str(exc)
                self._set_busy(False)
                self._set_indicator(False)
            return
        if token != self._scan_token:
            return
        self._render_report(report)
        self._set_busy(False)
        self._set_indicator(False)

    # -- rendering -------------------------------------------------------------

    def _clear_rows(self) -> None:
        while len(self.rows_box.children) > 0:
            self.rows_box.remove(self.rows_box.children[0])

    def _render_report(self, report: CleanupReport) -> None:
        self._entries = list(report.entries)
        self._rows = []
        self._clear_rows()

        if report.skipped_running:
            self.label_status.text = t(
                "storage_cleanup_running",
                names=", ".join(sorted(report.skipped_running)),
            )
        else:
            self.label_status.text = ""

        if not report.entries:
            self.label_summary.text = t("storage_cleanup_empty")
            self._update_selected_state()
            return

        self.label_summary.text = t(
            "storage_cleanup_summary",
            count=len(report.entries),
            size=format_size(report.total_size),
        )
        totals = report.by_category()
        for category in CATEGORY_ORDER:
            items = [entry for entry in self._entries if entry.category == category]
            if not items:
                continue
            header = toga.Box(
                style=Pack(direction=ROW, align_items=CENTER, margin=(14, 0, 4, 0))
            )
            header.add(
                toga.Label(
                    f"{t(f'storage_cleanup_cat_{category}')} · "
                    f"{format_size(totals.get(category, 0))}",
                    style=Pack(
                        font_size=12.5,
                        font_weight="bold",
                        color=Theme.TEXT_PRIMARY,
                    ),
                )
            )
            self.rows_box.add(header)
            hint_key = _CATEGORY_HINTS.get(category)
            if hint_key is not None:
                self.rows_box.add(
                    toga.Label(
                        t(hint_key),
                        style=Pack(
                            font_size=10.5,
                            color=Theme.TEXT_TERTIARY,
                            margin=(0, 0, 4, 0),
                        ),
                    )
                )
            for entry in sorted(items, key=lambda item: -item.size):
                row = _SelectableRow(entry, self._update_selected_state)
                self._rows.append(row)
                self.rows_box.add(row.widget)

        self._update_selected_state()

    # -- selection -------------------------------------------------------------

    def _selected_entries(self) -> list[CacheEntry]:
        return [row.entry for row in self._rows if row.selected]

    def _update_selected_state(self) -> None:
        selected = self._selected_entries()
        total = sum(entry.size for entry in selected)
        self.label_selected.text = (
            t(
                "storage_cleanup_selected",
                count=len(selected),
                size=format_size(total),
            )
            if selected
            else ""
        )
        enabled = bool(selected) and not self._busy
        if self.btn_clean.enabled != enabled:
            self.btn_clean.enabled = enabled

    def _on_select_all(self, widget: Any = None) -> None:
        # Bulk toggles must not recompute the summary per row: on a few hundred
        # rows that turned one click into ~5 seconds of repeated full-list
        # scans and status-label relayouts.
        for row in self._rows:
            row.set_selected(True, notify=False)
        self._update_selected_state()

    def _on_select_none(self, widget: Any = None) -> None:
        for row in self._rows:
            row.set_selected(False, notify=False)
        self._update_selected_state()

    # -- cleanup ---------------------------------------------------------------

    async def _clean_selected(self) -> None:
        selected = self._selected_entries()
        if self._busy or not selected:
            return
        total = sum(entry.size for entry in selected)
        try:
            confirmed = await cocoa_events.confirm_with_labels(
                self,
                t("storage_cleanup_title"),
                t(
                    "storage_cleanup_confirm",
                    count=len(selected),
                    size=format_size(total),
                ),
                t("storage_cleanup_btn_clean"),
                t("btn_cancel"),
            )
        except Exception:
            logger.debug("Could not show the cleanup confirmation", exc_info=True)
            return
        if not confirmed:
            return

        self._set_busy(True)
        loop = asyncio.get_running_loop()
        freed, errors = await loop.run_in_executor(None, delete_entries, selected)
        invalidate_size_cache()
        self._set_busy(False)
        self.label_status.text = t("storage_cleanup_done", size=format_size(freed))
        if errors:
            try:
                await self.error_dialog(
                    t("environment_error_title"),
                    t("storage_cleanup_error", errors="\n".join(errors[:8])),
                )
            except Exception:
                logger.debug("Could not show the cleanup errors", exc_info=True)
        if self._on_cleaned is not None:
            try:
                self._on_cleaned()
            except Exception:
                logger.debug("Cleanup callback failed", exc_info=True)
        self.scan()

    # -- busy / indicator ------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button in (self.btn_all, self.btn_none, self.btn_rescan):
            if button.enabled == busy:
                button.enabled = not busy
        if busy and self.btn_clean.enabled:
            self.btn_clean.enabled = False
        elif not busy:
            self._update_selected_state()

    def _set_indicator(self, running: bool) -> None:
        try:
            if running:
                self.indicator.start()
            else:
                self.indicator.stop()
        except Exception:
            pass
