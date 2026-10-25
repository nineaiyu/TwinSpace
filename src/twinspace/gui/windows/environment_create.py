"""GUI dialog for creating a multi-app isolated environment."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, HIDDEN, ROW, VISIBLE

from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.gui.components.wrapping_label import WrappingLabel
from twinspace.gui.patch_cocoa import configure_cocoa_window
from twinspace.gui.services.environment_service import (
    EnvironmentApp,
    EnvironmentService,
)
from twinspace.gui.theme import Theme
from twinspace.validation import validate_clone_name

logger = get_logger("gui.environment_create")


class EnvironmentCreateWindow(toga.Window):
    """Create an environment, or add missing apps to an existing one."""

    def __init__(
        self,
        environment_service: EnvironmentService,
        app: Optional[toga.App] = None,
        initial_name: Optional[str] = None,
        on_complete: Optional[Callable[[], Coroutine[Any, Any, None]]] = None,
    ):
        self._manage_mode = bool(initial_name)
        title = (
            t("environment_manage_title", name=initial_name)
            if initial_name
            else t("environment_window_title")
        )
        super().__init__(title=title, size=(760, 620))
        configure_cocoa_window(self, floating=False)

        self.environment_service = environment_service
        self.app_instance = app
        self.on_complete_callback = on_complete
        self._busy = False
        self._app_switches: dict[str, toga.Switch] = {}
        self._app_enabled: dict[str, bool] = {}
        self._name_inputs: dict[str, toga.TextInput] = {}
        self._name_edited: set[str] = set()
        self._syncing_names = False
        self._existing_env = (
            environment_service.environment(initial_name) if initial_name else None
        )
        self._existing_keys = self._existing_env.app_keys if self._existing_env else set()
        self._existing_records: dict[str, Any] = {}
        if self._existing_env:
            for record in self._existing_env.records:
                key = environment_service.app_key_for_bundle_id(record.bundle_id)
                if key:
                    self._existing_records[key] = record

        self.input_name = toga.TextInput(
            value=initial_name or "",
            placeholder=t("environment_name_placeholder"),
            on_change=self._on_name_change,
            readonly=bool(initial_name),
            style=Pack(flex=1, font_size=13.5),
        )

        self.label_hint = WrappingLabel(
            t("environment_existing_hint") if self._existing_env else "",
            style=Pack(font_size=11.5, color=Theme.TEXT_MUTED, margin=(2, 0, 6, 0)),
        )

        self.app_box = toga.Box(style=Pack(direction=COLUMN))
        for app_def in environment_service.available_apps():
            self.app_box.add(self._build_app_row(app_def))

        # Browser binding: how links/OAuth from non-Chrome env apps are opened.
        self.select_browser_mode = toga.Selection(
            items=[
                t("env_browser_mode_chrome"),
                t("env_browser_mode_system"),
                t("env_browser_mode_external"),
            ],
            on_change=self._on_browser_mode_change,
            style=Pack(width=300, font_size=12.5, margin_right=10),
        )
        self.input_browser_path = toga.TextInput(
            placeholder=t("env_browser_path_placeholder"),
            style=Pack(flex=1, font_size=12.5, margin_right=6),
        )
        self.btn_browser_browse = toga.Button(
            t("env_browser_browse"),
            on_press=lambda widget: asyncio.create_task(self._on_browse_browser()),
            style=Pack(height=28, font_size=12.5),
        )
        self.browser_row = toga.Box(
            style=Pack(direction=ROW, align_items=CENTER, margin=(4, 0, 0, 0), visibility=HIDDEN)
        )
        self.browser_row.add(self.input_browser_path)
        self.browser_row.add(self.btn_browser_browse)
        self.label_browser_hint = WrappingLabel(
            t("env_browser_hint_chrome"),
            style=Pack(font_size=11, color=Theme.TEXT_MUTED, margin=(2, 0, 0, 0)),
        )

        self.label_status = toga.Label(
            "",
            style=Pack(font_size=12.5, color=Theme.TEXT_MUTED, margin=(6, 0, 4, 0)),
        )
        self.progress_bar = toga.ProgressBar(
            max=1,
            value=0,
            style=Pack(margin_bottom=8),
        )

        self.btn_cancel = toga.Button(
            t("btn_cancel"),
            on_press=lambda widget: self.close(),
            style=Pack(height=30, font_size=13, margin_right=8),
        )
        self.btn_create = toga.Button(
            t("environment_btn_add") if self._manage_mode else t("environment_btn_create"),
            on_press=lambda widget: asyncio.create_task(self._on_create()),
            style=Pack(height=30, font_size=13, font_weight="bold"),
        )

        self.content = self._build_layout()
        self.on_close = self._on_close

    def _on_close(self, window: toga.Window) -> bool:
        return not self._busy

    def _default_clone_name(self, app: EnvironmentApp) -> str:
        env_name = self.input_name.value.strip() if hasattr(self, "input_name") else ""
        return f"{app.clone_prefix}-{env_name}" if env_name else app.clone_prefix

    def _build_app_row(self, app: EnvironmentApp) -> toga.Box:
        installed_path = app.installed_path
        existing = app.key in self._existing_keys
        enabled = bool(installed_path) and not existing
        default_value = existing or bool(installed_path)
        existing_record = self._existing_records.get(app.key)

        switch = toga.Switch(
            app.label,
            value=default_value,
            enabled=enabled,
            on_change=lambda widget, key=app.key: self._on_switch_change(key, widget),
            style=Pack(width=170, font_size=13),
        )
        self._app_switches[app.key] = switch
        self._app_enabled[app.key] = enabled

        name_input = toga.TextInput(
            value=(
                existing_record.clone_name
                if existing_record is not None
                else self._default_clone_name(app)
            ),
            placeholder=self._default_clone_name(app),
            readonly=not enabled,
            on_change=lambda widget, key=app.key: self._on_clone_name_change(key, widget),
            style=Pack(width=190, margin_left=6, margin_right=10, font_size=12.5),
        )
        self._name_inputs[app.key] = name_input

        if existing:
            status_text = t("environment_app_existing")
            status_color = Theme.TEXT_MUTED
        elif installed_path:
            status_text = t("environment_app_installed")
            status_color = Theme.TEXT_SECONDARY
        else:
            status_text = t("environment_app_missing")
            status_color = Theme.TEXT_TERTIARY

        path_text = str(installed_path or app.default_path)
        detail = WrappingLabel(
            f"{status_text} · {path_text}",
            style=Pack(flex=1, font_size=11, color=status_color),
        )

        row = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=7))
        row.add(switch)
        row.add(name_input)
        row.add(detail)
        return row

    def _on_switch_change(self, key: str, widget: toga.Switch) -> None:
        name_input = self._name_inputs.get(key)
        if name_input is None:
            return
        writable = self._app_enabled.get(key, False) and widget.value
        name_input.readonly = not writable
        if writable and key not in self._name_edited:
            app = self.environment_service.app_for_key(key)
            if app is not None:
                name_input.value = self._default_clone_name(app)

    def _on_clone_name_change(self, key: str, widget: toga.TextInput) -> None:
        if not self._syncing_names:
            self._name_edited.add(key)

    def _build_layout(self) -> toga.Box:
        root = toga.Box(style=Pack(direction=COLUMN, margin=(18, 20, 18, 20), flex=1))

        root.add(
            toga.Label(
                t("environment_label_name"),
                style=Pack(font_size=13, font_weight="bold", margin_bottom=4),
            )
        )
        root.add(self.input_name)
        root.add(self.label_hint)

        root.add(
            toga.Label(
                t("environment_label_apps"),
                style=Pack(font_size=13, font_weight="bold", margin=(8, 0, 2, 0)),
            )
        )
        root.add(
            toga.Label(
                t("environment_clone_name_hint"),
                style=Pack(font_size=11, color=Theme.TEXT_MUTED, margin=(0, 0, 6, 0)),
            )
        )
        apps_scroll = toga.ScrollContainer(
            horizontal=False,
            style=Pack(flex=1, margin_bottom=6),
        )
        apps_box = toga.Box(style=Pack(direction=COLUMN, margin=(2, 4, 2, 0)))
        apps_box.add(self.app_box)
        apps_scroll.content = apps_box
        root.add(apps_scroll)

        root.add(
            toga.Label(
                t("env_browser_section"),
                style=Pack(font_size=13, font_weight="bold", margin=(8, 0, 2, 0)),
            )
        )
        root.add(self.select_browser_mode)
        root.add(self.browser_row)
        root.add(self.label_browser_hint)

        root.add(self.label_status)
        root.add(self.progress_bar)

        actions = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_top=6))
        actions.add(toga.Box(style=Pack(flex=1)))
        actions.add(self.btn_cancel)
        actions.add(self.btn_create)
        root.add(actions)
        return root

    def show(self) -> None:
        super().show()
        configure_cocoa_window(self, floating=False)

    def _on_name_change(self, widget: toga.TextInput) -> None:
        if not hasattr(self, "label_hint"):
            return
        name = widget.value.strip()
        existing = self.environment_service.environment(name) if name else None
        if existing:
            self.label_hint.text = t("environment_existing_hint")
        else:
            self.label_hint.text = ""

        if self._syncing_names or self._manage_mode:
            return
        self._syncing_names = True
        try:
            for key, name_input in self._name_inputs.items():
                if key in self._name_edited or name_input.readonly:
                    continue
                app = self.environment_service.app_for_key(key)
                if app is not None:
                    name_input.value = self._default_clone_name(app)
        finally:
            self._syncing_names = False

    def _on_browser_mode_change(self, widget: toga.Selection) -> None:
        external = widget.value == t("env_browser_mode_external")
        self.browser_row.style.visibility = VISIBLE if external else HIDDEN
        if external:
            self.label_browser_hint.text = t("env_browser_hint_external")
        elif widget.value == t("env_browser_mode_system"):
            self.label_browser_hint.text = t("env_browser_hint_system")
        else:
            self.label_browser_hint.text = t("env_browser_hint_chrome")

    async def _on_browse_browser(self) -> None:
        try:
            path = await self.dialog(
                toga.OpenFileDialog(
                    t("env_browser_browse"),
                    file_types=["app"],
                )
            )
        except Exception:
            return
        if path:
            self.input_browser_path.value = str(path)

    def _resolve_browser_path(self) -> tuple[Path | None, str | None]:
        """Return (browser_path, error_message_key) from the current selection."""
        mode = self.select_browser_mode.value
        if mode != t("env_browser_mode_external"):
            return None, None
        raw = self.input_browser_path.value.strip().strip('"')
        if not raw:
            return None, "env_browser_invalid"
        candidate = Path(raw).expanduser()
        if candidate.suffix != ".app" or not candidate.is_dir():
            return None, "env_browser_invalid"
        return candidate, None

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.input_name.readonly = busy or self._manage_mode
        self.btn_create.enabled = not busy
        self.btn_cancel.enabled = not busy
        for key, switch in self._app_switches.items():
            switch.enabled = self._app_enabled.get(key, False) and not busy
            name_input = self._name_inputs.get(key)
            if name_input is not None:
                name_input.readonly = not (
                    self._app_enabled.get(key, False) and bool(switch.value) and not busy
                )

    async def _on_create(self) -> None:
        if self._busy:
            return

        name = self.input_name.value.strip()
        if not name:
            await self.error_dialog(t("environment_error_title"), t("environment_name_required"))
            return
        try:
            validate_clone_name(name)
        except ValueError as exc:
            await self.error_dialog(
                t("environment_error_title"),
                t("environment_name_invalid", error=str(exc)),
            )
            return

        selected = [key for key, switch in self._app_switches.items() if switch.value]
        if not selected:
            await self.error_dialog(t("environment_error_title"), t("environment_select_one"))
            return

        clone_names: dict[str, str] = {}
        seen_names: dict[str, str] = {}
        for key in selected:
            app_def = self.environment_service.app_for_key(key)
            app_label = app_def.label if app_def else key
            name_input = self._name_inputs.get(key)
            clone_name = (name_input.value or "").strip() if name_input else ""
            if not clone_name:
                await self.error_dialog(
                    t("environment_error_title"),
                    t("environment_clone_name_required", app=app_label),
                )
                return
            try:
                validate_clone_name(clone_name)
            except ValueError as exc:
                await self.error_dialog(
                    t("environment_error_title"),
                    t("environment_clone_name_invalid", app=app_label, error=str(exc)),
                )
                return
            if clone_name in seen_names:
                await self.error_dialog(
                    t("environment_error_title"),
                    t("environment_clone_name_duplicate", name=clone_name),
                )
                return
            seen_names[clone_name] = app_label
            clone_names[key] = clone_name

        browser_path, browser_error = self._resolve_browser_path()
        if browser_error:
            await self.error_dialog(t("environment_error_title"), t(browser_error))
            return

        existing = self.environment_service.environment(name)
        existing_keys = existing.app_keys if existing else set()
        missing = [key for key in selected if key not in existing_keys]
        if existing and not missing:
            await self.info_dialog(t("environment_done_title"), t("environment_no_missing_apps"))
            return

        self._set_busy(True)
        self.progress_bar.max = len(selected)
        self.progress_bar.value = 0
        self.label_status.text = t("environment_creating", name=name)

        def on_progress(index: int, total: int, app: EnvironmentApp, status: str) -> None:
            if status in ("checking", "creating", "existing", "created"):
                self.label_status.text = t(
                    "environment_step",
                    app=app.label,
                    current=index,
                    total=total,
                )
            if status in ("existing", "created"):
                self.progress_bar.value = index

        try:
            created = await self.environment_service.create_environment(
                name,
                selected,
                on_progress=on_progress,
                clone_names=clone_names,
                browser_path=browser_path,
            )
            self.progress_bar.value = len(selected)
            env = self.environment_service.environment(name)
            path = env.env_dir if env else ""
            if created:
                await self.info_dialog(
                    t("environment_done_title"),
                    t("environment_done_msg", name=name, path=str(path)),
                )
            else:
                await self.info_dialog(
                    t("environment_done_title"),
                    t("environment_no_missing_apps"),
                )
            if self.on_complete_callback:
                await self.on_complete_callback()
            self.close()
        except Exception as exc:
            logger.exception("Environment creation failed")
            self.label_status.text = ""
            self._set_busy(False)
            if self.on_complete_callback:
                try:
                    await self.on_complete_callback()
                except Exception:
                    pass
            await self.error_dialog(t("environment_error_title"), str(exc))
