"""Backup manager window: list, create, restore and delete env backups."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import toga
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from twinspace.core.environments.backup import list_backups, summarize_backup
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.gui.patch_cocoa import (
    configure_cocoa_danger_button,
    configure_cocoa_window,
)
from twinspace.gui.services.data_size import format_size
from twinspace.gui.theme import Theme

logger = get_logger("gui.backup_manager")


class BackupManagerWindow(toga.Window):
    """Snapshot list for one environment with restore / delete actions."""

    def __init__(
        self,
        app: Any,
        environment_service: Any,
        env_name: str,
        on_changed: Optional[Callable[[], Any]] = None,
    ):
        super().__init__(title=t("backup_title", name=env_name), size=(660, 430))
        configure_cocoa_window(self, floating=False)
        self._app = app
        self._service = environment_service
        self._env_name = env_name
        self._on_changed = on_changed
        self._items: list[dict[str, object]] = []
        self._busy = False

        root = toga.Box(
            style=Pack(
                direction=COLUMN,
                margin=(16, 18, 14, 18),
                background_color=Theme.BG_WINDOW,
            )
        )
        self.table = toga.Table(
            columns=[
                t("backup_col_file"),
                t("backup_col_size"),
                t("backup_col_created"),
            ],
            multiple_select=False,
            on_select=self._on_table_select,
            style=Pack(flex=1),
        )
        root.add(self.table)
        self._summary_cache: dict[Path, dict] = {}

        buttons = toga.Box(style=Pack(direction=ROW, margin_top=10))
        self.btn_backup = toga.Button(
            t("backup_btn_backup"),
            on_press=self._on_backup,
            style=Pack(height=28, font_weight="bold", margin_right=6),
        )
        self.btn_restore = toga.Button(
            t("backup_btn_restore"),
            on_press=self._on_restore,
            enabled=False,
            style=Pack(height=28, margin_right=6),
        )
        self.btn_delete = toga.Button(
            t("backup_btn_delete"),
            on_press=self._on_delete,
            enabled=False,
            style=Pack(height=28),
        )
        configure_cocoa_danger_button(self.btn_delete)
        buttons.add(self.btn_backup)
        buttons.add(self.btn_restore)
        buttons.add(self.btn_delete)
        root.add(buttons)

        self.label_status = toga.Label(
            "",
            style=Pack(font_size=12, color=Theme.TEXT_MUTED, margin_top=8),
        )
        root.add(self.label_status)
        self.content = root

        self._reload()

    # -- data --------------------------------------------------------------

    def _reload(self) -> None:
        self._items = list_backups(self._env_name)
        self.table.data = [
            (
                str(item["name"]),
                format_size(int(item["size"])),
                datetime.fromtimestamp(float(item["mtime"])).strftime("%Y-%m-%d %H:%M"),
            )
            for item in self._items
        ]
        if not self._items:
            self.label_status.text = t("backup_empty")
        else:
            total = sum(int(item["size"]) for item in self._items)
            self.label_status.text = t(
                "backup_summary", count=len(self._items), size=format_size(total)
            )
        self.btn_restore.enabled = bool(self._items)
        self.btn_delete.enabled = bool(self._items)

    def _selected_path(self) -> Optional[Path]:
        native = getattr(getattr(self.table, "_impl", None), "native_table", None)
        if native is None:
            return None
        try:
            index = int(native.selectedRow)
        except Exception:
            return None
        if not 0 <= index < len(self._items):
            return None
        return Path(self._items[index]["path"])

    def _on_table_select(self, widget: Any, row: Any = None, **kwargs: Any) -> None:
        path = self._selected_path()
        if path is None:
            return
        cached = self._summary_cache.get(path)
        if cached is not None:
            self._show_preview(cached)
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            try:
                self._show_preview(summarize_backup(path))
            except Exception:
                pass
            return
        self.label_status.text = t("backup_preview_pending")
        loop.run_in_executor(None, self._apply_preview, path, loop)

    def _apply_preview(self, path: Path, loop: asyncio.AbstractEventLoop) -> None:
        try:
            summary = summarize_backup(path)
        except Exception as exc:
            logger.debug("Backup preview failed for %s: %s", path, exc)
            return
        self._summary_cache[path] = summary
        loop.call_soon_threadsafe(self._show_preview, summary)

    def _show_preview(self, summary: dict) -> None:
        """Render the per-app content breakdown into the status line."""
        apps = summary.get("apps") or []
        parts = [
            t(
                "backup_preview_app",
                key=str(item["key"]),
                size=format_size(int(item["bytes"])),
                files=int(item["files"]),
            )
            for item in apps[:6]
        ]
        if len(apps) > 6:
            parts.append("…")
        total = int(summary.get("total_bytes", 0))
        preview = t(
            "backup_preview_total",
            total=format_size(total),
            breakdown="  ".join(parts),
        )
        self.label_status.text = preview

    def _refresh_pages(self) -> None:
        if self._on_changed is None:
            return
        try:
            result = self._on_changed()
            if asyncio.iscoroutine(result):
                asyncio.get_running_loop().create_task(result)
        except RuntimeError:
            pass
        except Exception:
            pass

    # -- actions -----------------------------------------------------------

    def _on_backup(self, widget: toga.Button) -> None:
        if self._busy:
            return
        self._busy = True
        task = self._run_backup()
        try:
            asyncio.get_running_loop().create_task(task)
        except RuntimeError:
            self._busy = False

    async def _run_backup(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            path = await loop.run_in_executor(
                None, self._service.backup_environment, self._env_name
            )
            self.label_status.text = t("backup_created_msg", name=Path(path).name)
        except Exception as exc:
            self.label_status.text = str(exc)
        self._busy = False
        self._reload()
        self._refresh_pages()

    def _on_restore(self, widget: toga.Button) -> None:
        path = self._selected_path()
        if path is None or self._busy:
            return
        task = self._run_restore(path)
        try:
            asyncio.get_running_loop().create_task(task)
        except RuntimeError:
            pass

    async def _run_restore(self, path: Path) -> None:
        confirmed = await self.confirm_dialog(
            t("backup_restore_confirm_title"),
            t("backup_restore_confirm", name=Path(path).name),
        )
        if not confirmed:
            return
        self._busy = True
        loop = asyncio.get_running_loop()
        try:
            restored, errors = await loop.run_in_executor(
                None,
                lambda: self._service.restore_environment(
                    self._env_name, Path(path)
                ),
            )
            if errors:
                self.label_status.text = "; ".join(errors)
            else:
                self.label_status.text = t("backup_restored_msg", count=len(restored))
        except Exception as exc:
            self.label_status.text = str(exc)
        self._busy = False
        self._reload()
        self._refresh_pages()

    def _on_delete(self, widget: toga.Button) -> None:
        path = self._selected_path()
        if path is None or self._busy:
            return
        task = self._run_delete(path)
        try:
            asyncio.get_running_loop().create_task(task)
        except RuntimeError:
            pass

    async def _run_delete(self, path: Path) -> None:
        confirmed = await self.confirm_dialog(
            t("backup_delete_confirm_title"),
            t("backup_delete_confirm", name=Path(path).name),
        )
        if not confirmed:
            return
        try:
            path.unlink()
            self.label_status.text = t("backup_deleted_msg", name=Path(path).name)
        except Exception as exc:
            self.label_status.text = str(exc)
        self._reload()
