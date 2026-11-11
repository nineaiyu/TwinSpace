"""Doctor Environment Check View with modern TopHeaderBar."""

import asyncio
from typing import Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.doctor import DoctorCheckItem
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.gui import cocoa_events
from twinspace.gui.components.form_card import FormCard
from twinspace.gui.components.top_bar import TopHeaderBar
from twinspace.gui.components.wrapping_label import WrappingLabel
from twinspace.gui.services.doctor_service import DoctorService
from twinspace.gui.theme import Theme

logger = get_logger("gui.doctor_view")

# Checks whose failure means the tool is absent rather than misconfigured.
_MISSING_TOOLS = ("codesign", "xcode-select", "plistbuddy")
# Checks whose failure the one-click Xcode installer can fix.
_XCODE_REPAIRABLE = ("codesign", "xcode-select")


class DoctorView(toga.Box):
    """View presenting system prerequisites, toolchain availability, and diagnostic advice."""

    def __init__(self, doctor_service: Optional[DoctorService] = None, app: Optional[toga.App] = None):
        super().__init__(style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_WINDOW))
        self.doctor_service = doctor_service or DoctorService()
        self.app_instance = app
        self._checking = False

        # Top Header Bar
        self.top_bar = TopHeaderBar(
            title=t("nav_doctor"),
            action_label=t("doctor_btn_recheck"),
            on_action=lambda w: self.app_instance.safe_create_task(self.run_checks()) if (self.app_instance and hasattr(self.app_instance, "safe_create_task")) else asyncio.create_task(self.run_checks()),
            action_symbol="arrow.clockwise",
        )
        self.add(self.top_bar)

        content_box = toga.Box(style=Pack(direction=COLUMN, margin=(0, 24, 20, 24), flex=1))
        self.add(content_box)

        # Summary badge card
        self.card_summary = FormCard()
        inner_summary = toga.Box(style=Pack(direction=ROW, align_items=CENTER, flex=1))
        # Entering the page auto-triggers a check, so start in checking state.
        self.label_summary = toga.Label(t("doctor_summary_checking"), style=Pack(font_weight="bold", font_size=Theme.FONT_SUBHEADER, flex=1, color=Theme.TEXT_PRIMARY))
        self.loading_indicator = toga.ActivityIndicator(style=Pack(width=20, height=20, margin_left=10))
        inner_summary.add(self.label_summary)
        inner_summary.add(self.loading_indicator)

        # One-click install Xcode Command Line Tools button
        self.btn_install_xcode = toga.Button(
            t("doctor_btn_install_xcode"),
            on_press=lambda w: self.app_instance.safe_create_task(self.action_install_xcode(w)) if (self.app_instance and hasattr(self.app_instance, "safe_create_task")) else asyncio.create_task(self.action_install_xcode(w)),
            style=Pack(
                height=32,
                font_size=13,
                font_weight="bold",
                margin_left=12,
                visibility="hidden",
            ),
        )
        cocoa_events.configure_button_icon(self.btn_install_xcode, "arrow.down.circle")
        inner_summary.add(self.btn_install_xcode)

        self.card_summary.add(inner_summary)
        content_box.add(self.card_summary)

        # Diagnostics card: one status block per check item
        self.card_results = FormCard(t("doctor_card_results"))
        self.results_box = toga.Box(style=Pack(direction=COLUMN))
        self.card_results.add(self.results_box)
        content_box.add(self.card_results)

    async def action_install_xcode(self, widget: Optional[toga.Button] = None):
        """Invoke macOS native Xcode Command Line Tools installer dialog with user guidance."""
        if self.btn_install_xcode:
            self.btn_install_xcode.enabled = False
        try:
            success, status = await self.doctor_service.trigger_xcode_install()
            title = t("doctor_dialog_install_title")
            if success:
                if status == "already_installed":
                    msg = t("doctor_dialog_install_already_msg")
                else:
                    msg = t("doctor_dialog_install_msg")
            else:
                msg = t("doctor_dialog_install_error_msg", error=status)

            if self.app_instance and hasattr(self.app_instance, "main_window") and self.app_instance.main_window:
                await self.app_instance.main_window.info_dialog(title, msg)
        except Exception as e:
            logger.error(f"Error executing action_install_xcode: {e}")
            if self.app_instance and hasattr(self.app_instance, "main_window") and self.app_instance.main_window:
                await self.app_instance.main_window.info_dialog(
                    t("doctor_dialog_install_title"),
                    t("doctor_dialog_install_error_msg", error=str(e)),
                )
        finally:
            if self.btn_install_xcode:
                self.btn_install_xcode.enabled = True

    @staticmethod
    def _status_text(item: DoctorCheckItem) -> str:
        """Missing tools read as「缺失」; misconfigurations read as「未通过」."""
        key = item.key or item.name.lower()
        if item.passed:
            return t("doctor_status_ok")
        if key in _MISSING_TOOLS or item.name in ("codesign", "xcode-select", "PlistBuddy"):
            return t("doctor_status_missing")
        return t("doctor_status_failed")

    def _clear_results(self) -> None:
        while len(self.results_box.children) > 0:
            self.results_box.remove(self.results_box.children[0])

    def _render_items(self, items: list[DoctorCheckItem]) -> None:
        self._clear_results()

        passed_count = 0
        toolchain_failed = False
        for index, item in enumerate(items):
            if index:
                self.results_box.add(toga.Box(
                    style=Pack(height=1, margin=(6, 0, 10, 0), background_color=Theme.BORDER_SUBTLE),
                ))

            passed = item.passed
            if passed:
                passed_count += 1
                status_color = Theme.BTN_SUCCESS
            else:
                status_color = Theme.BTN_WARNING
                if (item.key or item.name.lower()) in _XCODE_REPAIRABLE:
                    toolchain_failed = True

            head_row = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=3))
            head_row.add(toga.Label(
                self._status_text(item),
                style=Pack(font_size=13, color=status_color, margin_right=8),
            ))
            head_row.add(toga.Label(
                item.name,
                style=Pack(font_size=13, font_weight="bold", color=Theme.TEXT_PRIMARY),
            ))
            self.results_box.add(head_row)

            if item.details:
                self.results_box.add(WrappingLabel(
                    item.details,
                    style=Pack(font_size=Theme.FONT_CAPTION, color=Theme.TEXT_MUTED, margin_bottom=2),
                ))
            if not passed and item.hint:
                self.results_box.add(WrappingLabel(
                    item.hint,
                    style=Pack(font_size=Theme.FONT_CAPTION, color=Theme.BTN_WARNING, margin_bottom=2),
                ))

        total_count = len(items)
        if total_count and passed_count == total_count:
            self.label_summary.text = t("doctor_summary_all_passed", passed=passed_count, total=total_count)
            self.label_summary.style.color = Theme.BTN_SUCCESS
            self.btn_install_xcode.style.visibility = "hidden"
        elif total_count:
            self.label_summary.text = t("doctor_summary_issues_found", count=total_count - passed_count)
            self.label_summary.style.color = Theme.BTN_WARNING
            if toolchain_failed:
                self.btn_install_xcode.style.visibility = "visible"
            else:
                self.btn_install_xcode.style.visibility = "hidden"

    async def run_checks(self):
        # Re-entrancy guard: rapid clicks must not stack concurrent check runs.
        if self._checking:
            return
        self._checking = True
        if self.top_bar.btn_action:
            self.top_bar.btn_action.enabled = False
        self.label_summary.text = t("doctor_summary_checking")
        self.label_summary.style.color = Theme.TEXT_PRIMARY
        self.btn_install_xcode.style.visibility = "hidden"
        self.loading_indicator.start()
        try:
            items = await self.doctor_service.check_environment()
        except Exception as e:
            logger.error(f"Environment check crashed: {e}")
            self._clear_results()
            self.label_summary.text = t("doctor_summary_failed", error=str(e))
            self.label_summary.style.color = Theme.BTN_WARNING
            return
        finally:
            self.loading_indicator.stop()
            if self.top_bar.btn_action:
                self.top_bar.btn_action.enabled = True
            self._checking = False
        self._render_items(items)
