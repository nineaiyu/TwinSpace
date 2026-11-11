"""Application Prober View with modern card-based analysis."""

import asyncio
from pathlib import Path
from typing import Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.app_prober import ProbeResult
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.gui import cocoa_events
from twinspace.gui.components.form_card import FormCard
from twinspace.gui.components.top_bar import TopHeaderBar
from twinspace.gui.components.wrapping_label import WrappingLabel
from twinspace.gui.services.probe_service import ProbeService
from twinspace.gui.services.recipe_service import RecipeService
from twinspace.gui.theme import Theme

logger = get_logger("gui.probe_view")


class ProbeView(toga.Box):
    """View providing deep binary, sandbox, and framework analysis for macOS applications."""

    def __init__(
        self,
        probe_service: Optional[ProbeService] = None,
        recipe_service: Optional[RecipeService] = None,
        app: Optional[toga.App] = None,
    ):
        super().__init__(style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_WINDOW))
        self.probe_service = probe_service or ProbeService()
        self.recipe_service = recipe_service or RecipeService()
        self.app_instance = app
        self.current_result: Optional[ProbeResult] = None
        self._probing = False

        # Top Header Bar
        self.top_bar = TopHeaderBar(
            title=t("nav_probe"),
            action_label=t("probe_btn_start"),
            on_action=lambda w: asyncio.create_task(self.do_probe()),
            action_symbol="magnifyingglass",
        )
        self.add(self.top_bar)

        content_box = toga.Box(style=Pack(direction=COLUMN, margin=(0, 24, 24, 24), flex=1))
        self.add(content_box)

        # ── Card 1: Target App Selection ───────────────────────────────────── #
        card_target = FormCard(t("probe_card_target"))

        row_input = toga.Box(style=Pack(direction=ROW, align_items=CENTER))
        self.input_path = toga.TextInput(
            placeholder=t("probe_input_placeholder"),
            on_confirm=lambda w: asyncio.create_task(self.do_probe()),
            style=Pack(flex=1, margin_right=8, font_size=13.5),
        )
        self.btn_browse = toga.Button(t("btn_browse_app"), on_press=self.on_browse_press, style=Pack(height=30, font_size=13))
        cocoa_events.configure_button_icon(self.btn_browse, "folder")
        row_input.add(self.input_path)
        row_input.add(self.btn_browse)
        card_target.add(row_input)
        content_box.add(card_target)

        # ── Card 2: Analysis Results Panel ─────────────────────────────────── #
        self.card_results = FormCard(t("probe_card_results"))

        self.label_app_name = WrappingLabel(f"{t('probe_row_app_name')}: —", style=Pack(font_size=13, color=Theme.TEXT_MUTED))
        self.label_bundle_id = WrappingLabel(f"{t('probe_row_bundle_id')}: —", style=Pack(font_size=13, color=Theme.TEXT_MUTED))
        self.label_sandbox = WrappingLabel(f"{t('probe_row_sandbox')}: —", style=Pack(font_size=13, color=Theme.TEXT_MUTED))
        self.label_frameworks = WrappingLabel(f"{t('probe_row_frameworks')}: —", style=Pack(font_size=13, color=Theme.TEXT_MUTED))
        self.label_reason = WrappingLabel(f"{t('probe_row_reason')}: —", style=Pack(font_size=13, color=Theme.TEXT_MUTED))
        self.label_strategy = WrappingLabel(f"{t('probe_row_strategy')}: —", style=Pack(font_size=13.5, font_weight="bold", color=Theme.ACCENT_BLUE))
        self.label_ios_warning = WrappingLabel(
            t("probe_warning_ios_unsupported"),
            style=Pack(font_size=13, color=Theme.BTN_WARNING, margin_top=8, visibility="hidden"),
        )

        self.card_results.add_row(t("probe_row_app_name"), self.label_app_name)
        self.card_results.add_row(t("probe_row_bundle_id"), self.label_bundle_id)
        self.card_results.add_row(t("probe_row_sandbox"), self.label_sandbox)
        self.card_results.add_row(t("probe_row_frameworks"), self.label_frameworks)
        self.card_results.add_row(t("probe_row_reason"), self.label_reason)
        self.card_results.add_row(t("probe_row_strategy"), self.label_strategy, margin_bottom=0)
        self.card_results.add(self.label_ios_warning)

        # Action: Save as custom recipe + jump to the recipes page
        self.probe_indicator = toga.ActivityIndicator(style=Pack(width=20, height=20, margin_right=8, visibility="hidden"))
        self.btn_save_recipe = toga.Button(
            t("probe_btn_save_recipe"),
            on_press=lambda w: asyncio.create_task(self.save_probed_recipe()),
            enabled=False,
            style=Pack(font_weight="bold", font_size=13, height=30),
        )
        cocoa_events.configure_button_icon(
            self.btn_save_recipe, "square.and.arrow.down"
        )
        self.btn_view_recipes = toga.Button(
            t("probe_btn_view_recipes"),
            on_press=self._go_recipes,
            style=Pack(font_size=13, height=30, margin_left=8, visibility="hidden"),
        )
        cocoa_events.configure_button_icon(self.btn_view_recipes, "list.bullet")
        self.card_results.add_action_row(self.probe_indicator, self.btn_save_recipe, self.btn_view_recipes, margin_top=14)
        content_box.add(self.card_results)

    async def _show_error(self, title: str, message: str) -> None:
        window = getattr(self.app_instance, "main_window", None)
        if window is not None:
            await window.error_dialog(title, message)

    def _set_busy(self, busy: bool) -> None:
        self._probing = busy
        if self.top_bar.btn_action:
            self.top_bar.btn_action.enabled = not busy
        self.btn_save_recipe.enabled = self.btn_save_recipe.enabled and not busy
        if busy:
            self.probe_indicator.style.visibility = "visible"
            self.probe_indicator.start()
        else:
            self.probe_indicator.stop()
            self.probe_indicator.style.visibility = "hidden"

    async def on_browse_press(self, widget: toga.Button):
        if self.app_instance and hasattr(self.app_instance, "main_window"):
            try:
                selected_file = await self.app_instance.main_window.open_file_dialog(
                    title=t("dialog_select_app_title"),
                    file_types=["app"],
                    initial_directory=Path("/Applications"),
                )
                if selected_file:
                    self.input_path.value = str(selected_file)
            except Exception as e:
                logger.debug(f"Browse dialog cancelled or failed: {e}")

    async def do_probe(self):
        # Re-entrancy guard: rapid clicks must not stack concurrent probes.
        if self._probing:
            return
        path_str = self.input_path.value.strip()
        if not path_str:
            await self._show_error(t("dialog_info_title"), t("dialog_probe_input_required"))
            return

        app_path = Path(path_str)
        if not app_path.exists() or not str(app_path).lower().endswith(".app"):
            await self._show_error(t("dialog_probe_failed_title"), t("dialog_probe_invalid_app", path=path_str))
            return

        self._set_busy(True)
        try:
            res = await self.probe_service.probe_app(app_path)
        except Exception as e:
            logger.error(f"Probe failed for '{path_str}': {e}")
            await self._show_error(t("dialog_probe_failed_title"), t("dialog_probe_failed_msg", error=str(e)))
            return
        finally:
            self._set_busy(False)

        self.current_result = res
        self._render_result(res)

    def _render_result(self, res: ProbeResult) -> None:
        self.label_app_name.text = f"{t('probe_row_app_name')}: {res.app_info.app_name}"
        self.label_bundle_id.text = f"{t('probe_row_bundle_id')}: {res.app_info.bundle_id}"
        sandbox_str = t("probe_sandbox_yes") if res.has_sandbox else t("probe_sandbox_no")
        self.label_sandbox.text = f"{t('probe_row_sandbox')}: {sandbox_str}"
        fw_str = ", ".join(res.frameworks) if res.frameworks else t("probe_frameworks_none")
        self.label_frameworks.text = f"{t('probe_row_frameworks')}: {fw_str}"
        self.label_reason.text = f"{t('probe_row_reason')}: {res.reason}"
        strat_label = t("card_strategy_hard") if res.strategy == "hard_clone" else t("card_strategy_soft")
        self.label_strategy.text = f"{t('probe_row_strategy')}: {strat_label}"

        # iOS/iPadOS wrapper apps cannot be cloned; surface it inline instead of
        # silently offering a strategy that the wizard/CLI would refuse.
        is_ios = bool(getattr(res.app_info, "is_ios_app", False))
        self.label_ios_warning.style.visibility = "visible" if is_ios else "hidden"
        self.btn_save_recipe.enabled = not is_ios
        self.btn_save_recipe.text = t("probe_btn_save_recipe")

    async def save_probed_recipe(self):
        if not self.current_result:
            return
        try:
            await self.recipe_service.save_custom_recipe(self.current_result.recipe)
        except Exception as e:
            logger.error(f"Saving probed recipe failed: {e}")
            await self._show_error(t("dialog_probe_failed_title"), t("dialog_recipe_save_failed", error=str(e)))
            return
        self.btn_save_recipe.text = t("probe_saved_success")
        self.btn_save_recipe.enabled = False
        self.btn_view_recipes.style.visibility = "visible"
        recipe_view = getattr(self.app_instance, "recipe_view", None)
        if recipe_view is not None:
            try:
                await recipe_view.refresh_recipes()
            except Exception as e:
                logger.debug(f"Refreshing recipe list after save failed: {e}")

    def _go_recipes(self, widget: toga.Button):
        if self.app_instance and hasattr(self.app_instance, "switch_view"):
            self.app_instance.switch_view("recipes")
