"""Quick-launch palette: fuzzy-filter clones and launch one with ⏎ (⌘K)."""

from __future__ import annotations

import asyncio
from typing import Any

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.state import CloneRecord
from twinspace.core.timestamps import format_last_opened, parse_iso_timestamp
from twinspace.gui.patch_cocoa import configure_cocoa_window
from twinspace.gui.theme import Theme

logger = get_logger("gui.quick_launcher")

# NSEvent key codes used for palette navigation.
_KEY_ESCAPE = 53
_KEY_RETURN = 36
_KEY_DOWN = 125
_KEY_UP = 126
_KEY_EVENT_MASK = 1 << 10  # NSEventMaskKeyDown


def _recent_key(record: CloneRecord) -> tuple[int, float]:
    """Sort value by last-opened recency; never-opened clones rank lowest."""
    stamp = parse_iso_timestamp(getattr(record, "last_opened_at", ""))
    if stamp is None:
        return (0, 0.0)
    try:
        return (1, stamp.timestamp())
    except (OSError, OverflowError, ValueError):
        return (1, 0.0)


def _match_score(name: str, query: str) -> int | None:
    """None = no match; lower = better (prefix < substring < subsequence)."""
    if not query:
        return 0
    if name.startswith(query):
        return 0
    if query in name:
        return 1
    # Subsequence fallback ("wc1" matches "wechat_1").
    cursor = 0
    for char in query:
        cursor = name.find(char, cursor)
        if cursor < 0:
            return None
        cursor += 1
    return 2


class QuickLauncherWindow(toga.Window):
    """Spotlight-style palette listing clones ranked by recent use."""

    def __init__(self, app: Any, clone_service: Any):
        super().__init__(title=t("quick_launch_title"), size=(580, 400))
        configure_cocoa_window(self, floating=True)
        self.app_ref = app
        self._clone_service = clone_service
        self._records: list[CloneRecord] = []
        self._filtered: list[CloneRecord] = []
        self._selected_row = 0
        self._monitor_token: Any = None

        root = toga.Box(
            style=Pack(
                direction=COLUMN,
                margin=(14, 16, 12, 16),
                background_color=Theme.BG_WINDOW,
            )
        )
        self.input_search = toga.TextInput(
            placeholder=t("quick_launch_placeholder"),
            on_change=self._on_query_changed,
            style=Pack(
                height=32,
                font_size=14,
                margin_bottom=10,
                background_color=Theme.BG_CARD,
                color=Theme.TEXT_PRIMARY,
            ),
        )
        root.add(self.input_search)

        self.table = toga.Table(
            columns=[
                t("list_col_name"),
                t("list_col_source_app"),
                t("list_col_env"),
                t("list_col_last_opened"),
            ],
            multiple_select=False,
            on_select=self._on_table_select,
            on_activate=self._on_row_activate,
            style=Pack(flex=1),
        )
        root.add(self.table)
        root.add(
            toga.Label(
                t("quick_launch_hint"),
                style=Pack(font_size=11.5, color=Theme.TEXT_MUTED, margin_top=8),
            )
        )
        self.content = root

        self.on_close = self._on_window_close
        self._install_key_monitor()

        # Loading runs as a task once the launcher is created inside the GUI
        # loop; the app falls back to safe_create_task when there is none yet.
        self._load_task: Any = None
        try:
            self._load_task = asyncio.get_running_loop().create_task(self._load_records())
        except RuntimeError:
            pass

    # -- data ---------------------------------------------------------------

    async def _load_records(self) -> None:
        try:
            self._records = await self._clone_service.list_clones()
        except Exception:
            logger.debug("Quick launcher failed to list clones", exc_info=True)
            self._records = []
        self._refresh_results()

    def _refresh_results(self) -> None:
        query = self.input_search.value.strip().lower()
        scored = []
        for record in self._records:
            score = _match_score(record.clone_name.lower(), query)
            if score is None:
                continue
            recency = _recent_key(record)
            # Exact/prefix matches first, then most recently used, then name.
            sort_value = (
                score,
                -recency[0],
                -recency[1],
                record.clone_name,
            )
            scored.append((sort_value, record))
        scored.sort(key=lambda item: item[0])
        self._filtered = [record for _, record in scored]
        self.table.data = [
            (
                record.clone_name,
                record.source_app,
                getattr(record, "env_group", "") or "—",
                format_last_opened(getattr(record, "last_opened_at", ""), compact=True),
            )
            for record in self._filtered
        ]
        self._selected_row = 0
        self._set_selected_row(0)

    # -- selection ----------------------------------------------------------

    def _set_selected_row(self, index: int) -> None:
        count = len(self._filtered)
        if count == 0:
            return
        self._selected_row = max(0, min(count - 1, index))
        native = getattr(getattr(self.table, "_impl", None), "native_table", None)
        if native is None:
            return
        try:
            from rubicon.objc import ObjCClass

            index_set = ObjCClass("NSIndexSet").alloc().initWithIndex_(self._selected_row)
            native.selectRowIndexes_byExtendingSelection_(index_set, False)
            native.scrollRowToVisible_(self._selected_row)
        except Exception:
            logger.debug("Could not move quick-launch selection", exc_info=True)

    def _on_table_select(self, widget: Any, row: Any = None, **kwargs: Any) -> None:
        native = getattr(getattr(self.table, "_impl", None), "native_table", None)
        if native is None:
            return
        try:
            self._selected_row = int(native.selectedRow)
        except Exception:
            pass

    def _on_query_changed(self, widget: Any) -> None:
        self._refresh_results()

    def _on_row_activate(self, widget: Any, row: Any = None, **kwargs: Any) -> None:
        self._launch_selected()

    # -- keyboard -----------------------------------------------------------

    def _install_key_monitor(self) -> None:
        try:
            from rubicon.objc import ObjCClass

            event_class = ObjCClass("NSEvent")
            self._monitor_token = event_class.addLocalMonitorForEventsMatchingMask_handler_(
                _KEY_EVENT_MASK, self._handle_key_event
            )
        except Exception:
            logger.debug("Could not install quick-launch key monitor", exc_info=True)
            self._monitor_token = None

    def _teardown_monitor(self) -> None:
        token = self._monitor_token
        if token is None:
            return
        self._monitor_token = None
        try:
            from rubicon.objc import ObjCClass

            ObjCClass("NSEvent").removeMonitor_(token)
        except Exception:
            logger.debug("Could not remove quick-launch key monitor", exc_info=True)

    def _handle_key_event(self, event: Any) -> Any:
        """Route palette keys while this window is key; pass everything else."""
        try:
            from rubicon.objc import ObjCClass, ObjCInstance

            native_event = event if isinstance(event, ObjCInstance) else ObjCInstance(event)
            self_native = getattr(getattr(self, "_impl", None), "native", None)
            key_window = ObjCClass("NSApplication").sharedApplication.keyWindow
            if key_window is None or self_native is None:
                return event
            if int(key_window.windowNumber) != int(self_native.windowNumber):
                return event
            key_code = int(native_event.keyCode)
            if key_code == _KEY_ESCAPE:
                self.close()
                return None
            if key_code == _KEY_RETURN:
                self._launch_selected()
                return None
            if key_code in (_KEY_UP, _KEY_DOWN):
                self._set_selected_row(
                    self._selected_row + (-1 if key_code == _KEY_UP else 1)
                )
                return None
        except Exception:
            logger.debug("Quick-launch key handling failed", exc_info=True)
        return event.value if hasattr(event, "value") else event

    # -- launch -------------------------------------------------------------

    def _launch_selected(self) -> None:
        if not 0 <= self._selected_row < len(self._filtered):
            return
        record = self._filtered[self._selected_row]
        try:
            asyncio.get_running_loop().create_task(self._launch(record))
        except RuntimeError:
            # No running loop (tests): launch synchronously via subprocess.
            import subprocess

            subprocess.Popen(["open", str(record.dest_path)])

    async def _launch(self, record: CloneRecord) -> None:
        """Launch through the clone page flow, then close the palette."""
        try:
            clone_view = getattr(self.app_ref, "clone_view", None)
            if clone_view is not None:
                await clone_view.on_launch_clone(record)
            else:
                import subprocess

                await asyncio.get_running_loop().run_in_executor(
                    None, lambda: subprocess.Popen(["open", str(record.dest_path)])
                )
        finally:
            self.close()

    def _on_window_close(self, window: Any) -> bool:
        self._teardown_monitor()
        app_ref = self.app_ref
        if getattr(app_ref, "_quick_launcher", None) is self:
            app_ref._quick_launcher = None
        return True
