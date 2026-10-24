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


class LogsView(toga.Box):
    """View presenting persistent application logs and real-time task output."""

    def __init__(self, app: Optional[toga.App] = None):
        super().__init__(style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_WINDOW))
        self.app_instance = app
        self._raw_log_lines: list[str] = []
        self._current_filter: str = ""

        # Top Header Bar
        self.top_bar = TopHeaderBar(
            title=t("nav_logs"),
            search_placeholder=t("logs_search_placeholder"),
            on_search=self.on_filter_logs,
            action_label=t("logs_btn_clear"),
            on_action=self.on_clear_logs,
            on_refresh=self.on_refresh_logs,
        )
        self.add(self.top_bar)

        # Monospace Log Text Area
        self.log_text = toga.MultilineTextInput(
            readonly=True,
            style=Pack(
                flex=1,
                margin=(0, 24, 20, 24),
                font_family="monospace",
                font_size=12,
                background_color=Theme.BG_CARD,
                color=Theme.TEXT_PRIMARY,
            ),
        )
        self.add(self.log_text)

        # Load persisted disk logs
        self.reload_from_disk()

        # Register live broadcast listener
        add_log_listener(self._on_live_log_entry)

    def reload_from_disk(self):
        """Read all log entries from the persistent log file on disk (reversed, latest first)."""
        content = read_logs()
        if content:
            lines = [line for line in content.strip().split("\n") if line.strip()]
            self._raw_log_lines = list(reversed(lines))
        else:
            self._raw_log_lines = []
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

        def _apply():
            self._raw_log_lines.insert(0, entry.strip())
            self._update_log_display()

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

    def _update_log_display(self):
        try:
            query = self._current_filter.strip().lower()
            if not query:
                filtered = self._raw_log_lines
            else:
                filtered = [line for line in self._raw_log_lines if query in line.lower()]

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



    def on_filter_logs(self, query: str):
        self._current_filter = query
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
