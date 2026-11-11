"""Copy-environment dialog: derive clones from an existing environment."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.i18n import t
from twinspace.gui.patch_cocoa import configure_cocoa_window
from twinspace.gui.theme import Theme

_STAGE_KEYS = {
    "creating": "env_clone_stage_create",
    "copying": "env_clone_stage_copy",
    "planning": "env_clone_stage_plan",
    "done": "env_clone_stage_done",
}


class EnvironmentCloneWindow(toga.Window):
    """Small dialog that duplicates one environment (optionally with data)."""

    def __init__(
        self,
        app: Any,
        environment_service: Any,
        source_name: str,
        app_count: int,
        on_complete: Optional[Callable[[], Any]] = None,
    ):
        super().__init__(title=t("env_clone_title", name=source_name), size=(480, 230))
        configure_cocoa_window(self, floating=True)
        self._app = app
        self._service = environment_service
        self._source = source_name
        self._on_complete = on_complete
        self._busy = False

        root = toga.Box(
            style=Pack(
                direction=COLUMN,
                margin=(16, 18, 14, 18),
                background_color=Theme.BG_WINDOW,
            )
        )
        root.add(
            toga.Label(
                t("env_clone_intro", name=source_name, count=app_count),
                style=Pack(
                    font_size=12.5, color=Theme.TEXT_MUTED, margin_bottom=10, flex=1
                ),
            )
        )

        row = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=8))
        row.add(
            toga.Label(
                t("env_clone_name_label"),
                style=Pack(font_size=13, margin_right=10),
            )
        )
        self.input_name = toga.TextInput(
            value=f"{source_name}-copy",
            style=Pack(flex=1, height=28),
        )
        row.add(self.input_name)
        root.add(row)

        self.switch_data = toga.Switch(
            t("env_clone_switch_data"),
            value=True,
            style=Pack(margin_bottom=12, font_size=13),
        )
        root.add(self.switch_data)

        self.label_status = toga.Label(
            "",
            style=Pack(font_size=12, color=Theme.TEXT_MUTED, margin_bottom=8),
        )
        root.add(self.label_status)

        self.btn_create = toga.Button(
            t("env_clone_btn_create"),
            on_press=self._on_create,
            style=Pack(height=30, font_weight="bold"),
        )
        root.add(self.btn_create)
        self.content = root

    def _on_create(self, widget: toga.Button) -> None:
        if self._busy:
            return
        name = self.input_name.value.strip()
        if not name:
            self.label_status.text = t("env_clone_err_name")
            return
        self._busy = True
        self.btn_create.enabled = False
        include_data = bool(self.switch_data.value)
        task = self._run(name, include_data)
        try:
            asyncio.get_running_loop().create_task(task)
        except RuntimeError:
            self.label_status.text = t("env_clone_err_no_loop")

    async def _run(self, name: str, include_data: bool) -> None:
        def progress(index: int, total: int, key: str, stage: str) -> None:
            stage_label = t(_STAGE_KEYS.get(stage, "env_clone_stage_plan"))
            try:
                self.label_status.text = t(
                    "env_clone_progress",
                    index=index,
                    total=total,
                    name=key,
                    stage=stage_label,
                )
            except Exception:
                pass

        try:
            records = await self._service.clone_environment(
                self._source,
                name,
                include_data=include_data,
                on_progress=progress,
            )
        except Exception as exc:
            self.label_status.text = str(exc)
            self._busy = False
            self.btn_create.enabled = True
            return
        self.label_status.text = t("env_clone_done", count=len(records))
        if self._on_complete is not None:
            try:
                result = self._on_complete()
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                pass
        self.close()
