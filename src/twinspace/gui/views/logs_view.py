"""Logs View for displaying persistent runtime logs and live execution output."""

from typing import Optional

import toga
from toga.style import Pack
from toga.style.pack import COLUMN

from twinspace.core.i18n import t
from twinspace.core.logger import (
    add_log_listener,
    clear_logs,
    get_logger,
    read_logs,
    remove_log_listener,
)
from twinspace.gui.components.top_bar import TopHeaderBar
from twinspace.gui.theme import Theme

logger = get_logger("gui.logs_view")

# Cap the in-memory buffer: every extra line costs text-store work on each
# repaint, and the log file on disk remains the complete record anyway.
_MAX_LOG_LINES = 2000
# Coalesce bursts of log lines into one repaint instead of one per line; a
# clone operation can emit dozens of lines per second.
_FLUSH_DELAY = 0.3


class LogsView(toga.Box):
    """View presenting persistent application logs and real-time task output."""

    def __init__(self, app: Optional[toga.App] = None):
        super().__init__(style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_WINDOW))
        self.app_instance = app
        self._raw_log_lines: list[str] = []
        self._current_filter: str = ""
        self._current_level: str = ""
        self._flush_scheduled = False
        self._dirty = False

        # Top Header Bar
        self.top_bar = TopHeaderBar(
            title=t("nav_logs"),
            search_placeholder=t("logs_search_placeholder"),
            on_search=self.on_filter_logs,
            filter_items=[
                t("logs_filter_all"),
                t("logs_filter_info"),
                t("logs_filter_warning"),
                t("logs_filter_error"),
            ],
            on_filter_change=self.on_level_changed,
            action_label=t("logs_btn_clear"),
            on_action=self.on_clear_logs,
            action_symbol="trash",
            refresh_symbol="arrow.clockwise",
            on_refresh=self.on_refresh_logs,
        )
        self.add(self.top_bar)

        # Monospace log surface inside an elevated card
        self.log_card = toga.Box(
            style=Pack(
                direction=COLUMN,
                flex=1,
                margin=(0, 24, 20, 24),
                background_color=Theme.BG_CARD,
            )
        )
        self.log_inner = toga.Box(style=Pack(direction=COLUMN, flex=1, margin=(10, 12, 10, 12)))
        self.log_text = toga.MultilineTextInput(
            readonly=True,
            style=Pack(
                flex=1,
                font_family="monospace",
                font_size=12,
                background_color=Theme.BG_CARD,
                color=Theme.TEXT_PRIMARY,
            ),
        )
        self.log_inner.add(self.log_text)
        self.log_card.add(self.log_inner)
        self.add(self.log_card)

        # Load persisted disk logs
        self.reload_from_disk()

        # Register live broadcast listener
        add_log_listener(self._on_live_log_entry)

    def focus_search(self) -> None:
        """Focus the toolbar search field (menu / keyboard driven)."""
        self.top_bar.focus_search()

    def reload_from_disk(self):
        """Read all log entries from the persistent log file on disk (reversed, latest first)."""
        content = read_logs()
        if content:
            lines = [line for line in content.strip().split("\n") if line.strip()]
            self._raw_log_lines = list(reversed(lines))
        else:
            self._raw_log_lines = []
        self._dirty = False
        self._update_log_display()

    def cleanup(self):
        """Deregister listeners to avoid memory leaks."""
        try:
            remove_log_listener(self._on_live_log_entry)
        except Exception:
            pass

    def _on_live_log_entry(self, entry: str):
        """Listener callback for new log messages emitted anywhere in the app (inserted at top)."""
        if not entry.strip():
            return
        entry = entry.strip()

        def _apply():
            self._raw_log_lines.insert(0, entry)
            if len(self._raw_log_lines) > _MAX_LOG_LINES:
                del self._raw_log_lines[_MAX_LOG_LINES:]
            self._schedule_flush()

        import asyncio

        loop = None
        if (
            self.app_instance
            and hasattr(self.app_instance, "loop")
            and self.app_instance.loop
            and self.app_instance.loop.is_running()
        ):
            loop = self.app_instance.loop
        else:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                pass

        if loop and loop.is_running():
            loop.call_soon_threadsafe(_apply)
        else:
            import threading
            if threading.current_thread() is threading.main_thread():
                # Main thread with no running loop (e.g., sync tests or early startup)
                _apply()
            # Background thread with no loop: silently drop — entry is on disk already.

    def _schedule_flush(self):
        """Repaint once per _FLUSH_DELAY window, however many lines arrived."""
        if self._flush_scheduled:
            return
        import asyncio

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._flush_pending_logs()
            return
        self._flush_scheduled = True
        loop.call_later(_FLUSH_DELAY, self._flush_pending_logs)

    def _flush_pending_logs(self):
        self._flush_scheduled = False
        if not self._is_visible():
            self._dirty = True
            return
        self._update_log_display()

    def _is_visible(self) -> bool:
        """True while the logs page is the one mounted in the main window.

        Repainting a hidden NSTextView is pure waste; the pending update is
        replayed when the view is shown again (switch_view reloads from disk).
        """
        app = self.app_instance
        name = getattr(app, "current_view_name", None)
        return name is None or name == "logs"

    def _update_log_display(self):
        try:
            query = self._current_filter.strip().lower()
            if not query:
                filtered = self._raw_log_lines
            else:
                filtered = [line for line in self._raw_log_lines if query in line.lower()]

            if self._current_level:
                filtered = [
                    line for line in filtered if self._matches_level(line)
                ]

            if hasattr(self, "log_text") and self.log_text:
                self.log_text.value = "\n".join(filtered)
            count = len(filtered)
            total = len(self._raw_log_lines)
            if hasattr(self, "top_bar") and self.top_bar:
                if query:
                    self.top_bar.update_title(t("logs_title_filtered", count=count, total=total))
                else:
                    self.top_bar.update_title(t("logs_title_total", total=total))
        except Exception:
            pass



    def _matches_level(self, line: str) -> bool:
        if self._current_level == "INFO":
            return "[INFO]" in line
        if self._current_level == "WARNING":
            return "[WARNING]" in line or "[WARN]" in line
        if self._current_level == "ERROR":
            return "[ERROR]" in line
        return True

    def on_filter_logs(self, query: str):
        self._current_filter = query
        self._update_log_display()

    def on_level_changed(self, value: str):
        mapping = {
            t("logs_filter_info"): "INFO",
            t("logs_filter_warning"): "WARNING",
            t("logs_filter_error"): "ERROR",
        }
        self._current_level = mapping.get(value, "")
        self._update_log_display()

    def on_clear_logs(self, widget: toga.Button):
        clear_logs()
        self.reload_from_disk()

    def on_refresh_logs(self, widget: toga.Button):
        self.reload_from_disk()

    def log_info(self, message: str):
        get_logger("gui").info(message)

    def log_error(self, message: str):
        get_logger("gui").error(message)
