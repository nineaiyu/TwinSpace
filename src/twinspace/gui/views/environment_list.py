"""Environment list view: one card per multi-app isolated environment."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.environments import EnvironmentSpec
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.gui.components.top_bar import TopHeaderBar
from twinspace.gui.components.wrapping_label import WrappingLabel
from twinspace.gui.patch_cocoa import configure_cocoa_card, configure_cocoa_danger_button
from twinspace.gui.services.environment_service import EnvironmentInfo, EnvironmentService
from twinspace.gui.theme import Theme
from twinspace.gui.windows.environment_create import EnvironmentCreateWindow

logger = get_logger("gui.environment_list")


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

        self._importing = False
        self.top_bar = TopHeaderBar(
            title=t("environment_title", count=0),
            action_label=t("environment_btn_new"),
            on_action=self.on_new_environment,
            secondary_action_label=t("env_btn_import"),
            on_secondary_action=self.on_import_template,
            on_refresh=lambda widget: asyncio.create_task(self.refresh_environments()),
        )
        self.add(self.top_bar)

        self.hint_label = WrappingLabel(
            t("environment_hint"),
            style=Pack(font_size=12, color=Theme.TEXT_MUTED, margin=(0, 24, 10, 24)),
        )
        self.add(self.hint_label)

        self.scroll = toga.ScrollContainer(style=Pack(flex=1), horizontal=False)
        self.list_box = toga.Box(style=Pack(direction=COLUMN, margin=(0, 24, 20, 24)))
        self.scroll.content = self.list_box
        self.add(self.scroll)

    async def refresh_environments(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            self._environments = await loop.run_in_executor(
                None, self.environment_service.list_environments
            )
        except Exception as exc:
            logger.error("Failed to list environments: %s", exc)
            self._environments = []
        try:
            self._running_clones = await loop.run_in_executor(
                None, self.environment_service.running_clones
            )
        except Exception as exc:
            logger.error("Failed to detect running environments: %s", exc)
            self._running_clones = set()
        self._render()

    def _clear(self, box: toga.Box) -> None:
        while len(box.children) > 0:
            box.remove(box.children[0])

    def _render(self) -> None:
        self._clear(self.list_box)
        self.top_bar.update_title(t("environment_title", count=len(self._environments)))

        if not self._environments:
            self._render_empty_state()
            return

        for env in self._environments:
            self.list_box.add(self._build_environment_card(env))

    def _render_empty_state(self) -> None:
        empty = toga.Box(style=Pack(direction=COLUMN, align_items=CENTER, margin=(50, 0, 0, 0)))
        empty.add(
            toga.Label(
                t("environment_empty_title"),
                style=Pack(font_size=17, font_weight="bold", color=Theme.TEXT_MUTED, margin_bottom=8),
            )
        )
        empty.add(
            WrappingLabel(
                t("environment_empty_hint"),
                style=Pack(font_size=13, color=Theme.TEXT_TERTIARY, margin=(0, 60, 16, 60)),
            )
        )
        empty.add(
            toga.Button(
                t("environment_btn_new"),
                on_press=self.on_new_environment,
                style=Pack(height=32, font_size=13, font_weight="bold"),
            )
        )
        self.list_box.add(empty)

    def _build_environment_card(self, env: EnvironmentInfo) -> toga.Box:
        env_running = any(record.clone_name in self._running_clones for record in env.records)
        card = toga.Box(
            style=Pack(direction=COLUMN, margin=(0, 0, 12, 0), background_color=Theme.BG_CARD)
        )
        inner = toga.Box(style=Pack(direction=COLUMN, margin=(14, 16, 14, 16)))

        header = toga.Box(style=Pack(direction=ROW, align_items=CENTER))
        header.add(
            toga.Label(
                env.name,
                style=Pack(font_size=15.5, font_weight="bold", color=Theme.TEXT_PRIMARY),
            )
        )
        header.add(toga.Box(style=Pack(flex=1)))
        header.add(
            toga.Label(
                t("environment_running") if env_running else t("environment_not_running"),
                style=Pack(
                    font_size=11.5,
                    color=Theme.TEXT_SECONDARY if env_running else Theme.TEXT_TERTIARY,
                ),
            )
        )
        inner.add(header)

        inner.add(
            WrappingLabel(
                t("environment_path", path=str(env.env_dir)),
                style=Pack(font_size=11.5, color=Theme.TEXT_TERTIARY, margin_top=3),
            )
        )

        app_rows = toga.Box(style=Pack(direction=COLUMN, margin_top=6))
        for record in env.records:
            key = self.environment_service.app_key_for_bundle_id(record.bundle_id)
            app = self.environment_service.app_for_key(key)
            label = app.label if app else record.source_app
            running = record.clone_name in self._running_clones
            row = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=4))
            row.add(
                WrappingLabel(
                    f"{label} · {record.clone_name}",
                    style=Pack(flex=1, font_size=12.5, color=Theme.TEXT_SECONDARY),
                )
            )
            row.add(
                toga.Button(
                    t("environment_app_close") if running else t("environment_app_open"),
                    on_press=lambda widget, env_name=env.name, app_key=key, is_running=running: (
                        asyncio.create_task(
                            self._toggle_app(env_name, app_key, is_running)
                        )
                    ),
                    style=Pack(height=24, font_size=11.5, width=64),
                )
            )
            app_rows.add(row)
        inner.add(app_rows)

        actions = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_top=10))
        btn_open = toga.Button(
            t("environment_btn_open_all"),
            on_press=lambda widget, name=env.name: asyncio.create_task(self._open_all(name)),
            style=Pack(height=28, font_size=12.5, font_weight="bold", margin_right=8),
        )
        btn_manage = toga.Button(
            t("environment_btn_manage"),
            on_press=lambda widget, name=env.name: self._open_manage(name),
            style=Pack(height=28, font_size=12.5, margin_right=8),
        )
        btn_update = toga.Button(
            t("environment_btn_update_all"),
            on_press=lambda widget, name=env.name: asyncio.create_task(self._update_all(name)),
            enabled=not env_running,
            style=Pack(height=28, font_size=12.5, margin_right=8),
        )
        btn_backup = toga.Button(
            t("environment_btn_backup"),
            on_press=lambda widget, name=env.name: asyncio.create_task(self._backup(name)),
            enabled=not env_running,
            style=Pack(height=28, font_size=12.5, margin_right=8),
        )
        btn_remove = toga.Button(
            t("environment_btn_remove"),
            on_press=lambda widget, name=env.name: asyncio.create_task(self._remove(name)),
            enabled=not env_running,
            style=Pack(height=28, font_size=12.5),
        )
        actions.add(btn_open)
        actions.add(btn_manage)
        actions.add(btn_update)
        actions.add(btn_backup)

        secondary = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_top=6))
        btn_export = toga.Button(
            t("env_btn_export"),
            on_press=lambda widget, name=env.name: asyncio.create_task(self._export_template(name)),
            style=Pack(height=26, font_size=11.5, margin_right=6),
        )
        btn_restore = toga.Button(
            t("env_btn_restore"),
            on_press=lambda widget, name=env.name: asyncio.create_task(self._restore_backup(name)),
            style=Pack(height=26, font_size=11.5, margin_right=6),
        )
        secondary.add(btn_export)
        secondary.add(btn_restore)
        secondary.add(toga.Box(style=Pack(flex=1)))
        configure_cocoa_danger_button(btn_remove)
        secondary.add(btn_remove)
        inner.add(secondary)
        inner.add(actions)

        card.add(inner)
        try:
            native_card = getattr(getattr(card, "_impl", None), "native", None)
            configure_cocoa_card(native_card, corner_radius=8.0, border_width=0.5)
        except Exception:
            pass
        return card

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
        await self.refresh_environments()

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
