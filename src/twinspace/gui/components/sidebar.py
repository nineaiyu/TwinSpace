import asyncio
import os
import re
from typing import Callable, Dict

import requests
import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, HIDDEN, ROW, VISIBLE

from twinspace import __version__
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.resources import get_app_icon_path
from twinspace.gui.patch_cocoa import (
    configure_cocoa_sidebar_active,
    configure_cocoa_single_line_label,
)
from twinspace.gui.services.update_service import UpdateService
from twinspace.gui.theme import Theme

logger = get_logger("gui.sidebar")


def format_update_error(exc: Exception) -> str:
    """Format an update check exception into a concise, localized, single-line error message."""
    exc_str = str(exc).lower()

    # 1. Timeout detection
    if "timeout" in exc_str or "timed out" in exc_str:
        return t("update_error_timeout")

    # 2. Connection / DNS / Network error detection
    network_keywords = ("connection", "nodename", "servname", "dns", "network", "socket", "unreachable")
    if any(k in exc_str for k in network_keywords):
        return t("update_error_network")

    # 3. HTTP error detection (e.g. HTTP 404, 500, 502)
    resp = getattr(exc, "response", None)
    status_code = getattr(resp, "status_code", None)
    if status_code:
        return t("update_error_http", code=status_code)
    if isinstance(exc, (requests.HTTPError, requests.exceptions.HTTPError)) or "httperror" in type(exc).__name__.lower():
        m = re.search(r"\b([45]\d{2})\b", exc_str)
        if m:
            return t("update_error_http", code=m.group(1))
    m = re.search(r"\b(?:http\s+|status\s+|error\s+)([45]\d{2})\b", exc_str)
    if m:
        return t("update_error_http", code=m.group(1))

    # 4. Fallback to concise error message
    return t("update_error_short")


class SidebarNav(toga.Box):
    """Sidebar navigation bar with branding, main sections, and bottom auxiliary items."""

    MAIN_NAV_KEYS = ["clones", "environments", "recipes", "probe", "doctor"]
    BOTTOM_NAV_KEYS = ["logs", "settings"]

    def __init__(
        self,
        on_select: Callable[[str], None],
        active_key: str = "clones",
        app: toga.App | None = None,
    ):
        super().__init__(style=Pack(direction=COLUMN, width=240, margin=0, background_color=Theme.BG_SIDEBAR))
        self.app_instance = app
        self.on_select = on_select
        self.active_key = active_key
        self.buttons: Dict[str, toga.Button] = {}
        self.update_service = UpdateService()

        # Brand header with logo icon
        header_box = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin=(20, 14, 16, 14)))

        logo_path = get_app_icon_path("png")
        if logo_path and logo_path.exists():
            try:
                logo_img = toga.Image(logo_path)
                logo_view = toga.ImageView(logo_img, style=Pack(width=28, height=28, margin_right=10))
                header_box.add(logo_view)
            except Exception:
                pass

        title_box = toga.Box(style=Pack(direction=COLUMN))
        title_label = toga.Label("TwinSpace", style=Pack(font_weight="bold", font_size=15.5, color=Theme.TEXT_PRIMARY))
        ver_label = toga.Label(f"v{__version__} App Cloner", style=Pack(font_size=11, color=Theme.TEXT_TERTIARY, margin_top=2))
        title_box.add(title_label)
        title_box.add(ver_label)
        header_box.add(title_box)
        self.add(header_box)

        # Main Navigation Section
        self.main_box = toga.Box(style=Pack(direction=COLUMN, margin=(4, 10, 4, 10)))
        for key in self.MAIN_NAV_KEYS:
            btn = toga.Button(
                t(f"nav_{key}"),
                on_press=self._create_select_handler(key),
                style=Pack(margin_bottom=5, height=30, font_size=13),
            )
            self.buttons[key] = btn
            self.main_box.add(btn)
        self.add(self.main_box)

        # Flexible spacer to push the fixed navigation to the bottom
        self.add(toga.Box(style=Pack(flex=1)))

        # Bottom Fixed Navigation Section
        self.bottom_box = toga.Box(style=Pack(direction=COLUMN, margin=(4, 10, 16, 10)))
        for key in self.BOTTOM_NAV_KEYS:
            btn = toga.Button(
                t(f"nav_{key}"),
                on_press=self._create_select_handler(key),
                style=Pack(margin_bottom=4, height=28, font_size=13),
            )
            self.buttons[key] = btn
            self.bottom_box.add(btn)

        # Check for Updates Section (below Settings)
        self.btn_check_update = toga.Button(
            t("settings_btn_check_update"),
            on_press=self.on_check_update,
            style=Pack(margin_top=2, margin_bottom=4, height=28, font_size=13),
        )
        self.bottom_box.add(self.btn_check_update)

        # Progress bar: hidden initially
        self.progress_bar = toga.ProgressBar(
            max=100,
            value=0,
            style=Pack(margin_top=2, margin_bottom=2, visibility=HIDDEN),
        )
        self.bottom_box.add(self.progress_bar)

        # Update status feedback label: single-line fixed height to prevent vertical layout shifts
        self.lbl_update_status = toga.Label(
            "",
            style=Pack(font_size=11, color=Theme.TEXT_MUTED, margin_top=2, height=18),
        )
        try:
            native_lbl = getattr(getattr(self.lbl_update_status, "_impl", None), "native", None)
            configure_cocoa_single_line_label(native_lbl)
        except Exception:
            pass
        self.bottom_box.add(self.lbl_update_status)

        self.add(self.bottom_box)

        self._update_button_styles()

    def retranslate(self):
        """Update button texts dynamically after language change."""
        for key in self.MAIN_NAV_KEYS + self.BOTTOM_NAV_KEYS:
            if key in self.buttons:
                self.buttons[key].text = t(f"nav_{key}")
        if hasattr(self, "btn_check_update") and self.btn_check_update:
            self.btn_check_update.text = t("settings_btn_check_update")

    async def on_check_update(self, widget: toga.Button | None = None) -> None:
        """Handle Check for Updates button press in sidebar."""
        self.btn_check_update.enabled = False
        self.lbl_update_status.text = t("update_checking")
        self.progress_bar.style.visibility = VISIBLE
        self.progress_bar.max = None
        self.progress_bar.start()
        logger.info("User initiated check for updates from sidebar")

        try:
            info = await self.update_service.check_for_updates()
            if not info:
                self.progress_bar.stop()
                self.progress_bar.style.visibility = HIDDEN
                self.lbl_update_status.text = t("update_already_latest", ver=__version__)
                self.btn_check_update.enabled = True

                async def _auto_clear():
                    await asyncio.sleep(5)
                    if self.lbl_update_status.text == t("update_already_latest", ver=__version__):
                        self.lbl_update_status.text = ""

                try:
                    asyncio.create_task(_auto_clear())
                except RuntimeError:
                    pass
                return

            self.progress_bar.stop()
            self.progress_bar.max = 100
            self.progress_bar.value = 0
            self.progress_bar.style.visibility = VISIBLE
            self.lbl_update_status.text = t("update_found", ver=info.version)
            logger.info(f"Update found: v{info.version}, starting download and install")

            loop = asyncio.get_running_loop()

            def _on_progress(downloaded: int, total: int) -> None:
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    msg = t("update_downloading", pct=pct)
                else:
                    pct = 0
                    msg = t("update_downloading", pct=0)

                def _ui_update():
                    self.lbl_update_status.text = msg
                    self.progress_bar.value = pct

                loop.call_soon_threadsafe(_ui_update)

            def _on_status(status_key: str) -> None:
                if status_key == "downloading":
                    msg = t("update_downloading", pct=0)
                elif status_key == "verifying":
                    msg = t("update_verifying")
                elif status_key == "installing":
                    msg = t("update_installing")
                else:
                    return

                def _ui_status():
                    self.lbl_update_status.text = msg

                loop.call_soon_threadsafe(_ui_status)

            await self.update_service.download_and_install(
                info,
                on_progress=_on_progress,
                on_status=_on_status,
            )

            self.progress_bar.stop()
            self.progress_bar.style.visibility = HIDDEN
            self.lbl_update_status.text = t("update_done_title")
            if self.app_instance and hasattr(self.app_instance, "main_window") and self.app_instance.main_window:
                await self.app_instance.main_window.info_dialog(
                    t("update_done_title"),
                    t("update_done_msg", ver=info.version),
                )
            os._exit(0)

        except Exception as e:
            logger.exception("Update error")
            self.progress_bar.stop()
            self.progress_bar.style.visibility = HIDDEN
            err_msg = format_update_error(e)
            self.lbl_update_status.text = err_msg
            self.btn_check_update.enabled = True

            async def _auto_clear_err():
                await asyncio.sleep(5)
                if self.lbl_update_status.text == err_msg:
                    self.lbl_update_status.text = ""

            try:
                asyncio.create_task(_auto_clear_err())
            except RuntimeError:
                pass

    def _create_select_handler(self, key: str):
        return lambda widget: self.select_item(key)

    def select_item(self, key: str):
        self.active_key = key
        self._update_button_styles()
        if self.on_select:
            self.on_select(key)

    def _update_button_styles(self):
        for key, btn in self.buttons.items():
            is_active = (key == self.active_key)
            btn.style.font_weight = "bold" if is_active else "normal"
            try:
                native_btn = getattr(getattr(btn, "_impl", None), "native", None)
                configure_cocoa_sidebar_active(native_btn, is_active)
            except Exception:
                pass

