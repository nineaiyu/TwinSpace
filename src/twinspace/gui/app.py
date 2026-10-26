"""TwinSpace Main Application (BeeWare Toga) with Modern GUI Architecture."""

import asyncio
import sys
from pathlib import Path
from typing import Any, Optional

import toga
from toga.constants import WindowState
from toga.style import Pack
from toga.style.pack import COLUMN, ROW

from twinspace import __version__
from twinspace.core.config import get_config_value
from twinspace.core.logger import get_logger
from twinspace.core.resources import get_app_icon_path

logger = get_logger("gui.app")
from twinspace.gui.components.sidebar import SidebarNav
from twinspace.gui.patch_cocoa import (
    apply_cocoa_appearance,
    apply_cocoa_sidebar_material,
    configure_cocoa_window_chrome,
    configure_cocoa_window_movable,
    drain_pending_cocoa_work,
    is_dark_mode,
    patch_cocoa_widgets,
    refresh_dark_mode_cache,
    set_window_min_size,
    update_cocoa_sidebar_material,
)
from twinspace.gui.services.clone_service import CloneService
from twinspace.gui.services.doctor_service import DoctorService
from twinspace.gui.services.environment_service import EnvironmentService
from twinspace.gui.services.probe_service import ProbeService
from twinspace.gui.services.recipe_service import RecipeService
from twinspace.gui.services.tray_service import TrayService
from twinspace.gui.theme import Theme
from twinspace.gui.views.clone_list import CloneListView
from twinspace.gui.views.doctor_view import DoctorView
from twinspace.gui.views.environment_list import EnvironmentListView
from twinspace.gui.views.logs_view import LogsView
from twinspace.gui.views.probe_view import ProbeView
from twinspace.gui.views.recipe_list import RecipeListView
from twinspace.gui.views.settings_view import SettingsView
from twinspace.gui.windows.wizard import WizardWindow


def set_macos_dock_icon(icon_path: Optional[Path] = None) -> bool:
    """Explicitly set application icon on macOS Dock via Cocoa AppKit."""
    if icon_path is None:
        icon_path = get_app_icon_path("png")
    if not icon_path or not icon_path.exists():
        return False
    try:
        from toga_cocoa.libs.appkit import NSApplication, NSImage
        ns_img = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
        if ns_img:
            NSApplication.sharedApplication.setApplicationIconImage_(ns_img)
            return True
    except Exception:
        # Graceful fallback for non-macOS or headless test environments
        pass
    return False


def set_macos_dock_visible(visible: bool) -> bool:
    """Show or hide the application icon on macOS Dock via Cocoa AppKit activation policy.

    - visible=True: Sets NSApplicationActivationPolicyRegular (0) to show Dock icon and standard UI.
    - visible=False: Sets NSApplicationActivationPolicyAccessory (1) to hide Dock icon.
    """
    if sys.platform != "darwin":
        return False
    try:
        from toga_cocoa.libs.appkit import (
            NSApplication,
            NSApplicationActivationPolicyAccessory,
            NSApplicationActivationPolicyRegular,
        )
        if NSApplication is not None and hasattr(NSApplication, "sharedApplication"):
            ns_app = NSApplication.sharedApplication
            if hasattr(ns_app, "setActivationPolicy_"):
                policy = NSApplicationActivationPolicyRegular if visible else NSApplicationActivationPolicyAccessory
                ns_app.setActivationPolicy_(policy)
                if visible:
                    set_macos_dock_icon()
                return True
    except Exception as e:
        logger.debug(f"Failed setting macOS dock visibility to {visible}: {e}")
    return False


class TwinSpaceApp(toga.App):
    """Main BeeWare Toga application entry point and view coordinator."""

    def __init__(
        self,
        formal_name: str = "TwinSpace",
        app_id: str = "com.twinspace.app",
        app_name: str = "twinspace",
        version: Optional[str] = None,
        author: str = "TwinSpace Contributors",
        description: str = "macOS App Cloning Engine",
        home_page: str = "https://github.com/nineaiyu/TwinSpace",
        **kwargs,
    ):
        patch_cocoa_widgets()
        if "icon" not in kwargs or kwargs["icon"] is None:
            icon_path = get_app_icon_path("png")
            if icon_path:
                kwargs["icon"] = icon_path
        if version is None:
            version = __version__
        # Guard flag to prevent _on_window_close from blocking a deliberate exit
        self._is_exiting: bool = False
        super().__init__(
            formal_name=formal_name,
            app_id=app_id,
            app_name=app_name,
            version=version,
            author=author,
            description=description,
            home_page=home_page,
            **kwargs,
        )


    def safe_create_task(self, coro):
        """Safely schedule a coroutine if an event loop is running."""
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(coro)
        except RuntimeError:
            if hasattr(self, "loop") and self.loop and self.loop.is_running():
                return self.loop.create_task(coro)
            coro.close()
            return None

    def startup(self):
        # Apply correct color palette before constructing any widgets
        dark_mode = is_dark_mode()
        Theme.apply_mode(dark_mode)
        apply_cocoa_appearance(dark_mode)

        # Set macOS Dock icon immediately on app launch
        set_macos_dock_icon(get_app_icon_path("png"))

        # Initialize services
        self.clone_service = CloneService()
        self.environment_service = EnvironmentService(clone_service=self.clone_service)
        self.recipe_service = RecipeService()
        self.probe_service = ProbeService()
        self.doctor_service = DoctorService()

        # Initialize all views
        self.clone_view = CloneListView(clone_service=self.clone_service, app=self)
        self.environment_view = EnvironmentListView(
            environment_service=self.environment_service,
            app=self,
        )
        self.recipe_view = RecipeListView(recipe_service=self.recipe_service, app=self)
        self.probe_view = ProbeView(probe_service=self.probe_service, recipe_service=self.recipe_service, app=self)
        self.doctor_view = DoctorView(doctor_service=self.doctor_service, app=self)
        self.logs_view = LogsView(app=self)
        self.settings_view = SettingsView(app=self)

        self.current_view_name = "clones"

        # Main window setup
        self.main_window = toga.MainWindow(
            title=self.formal_name,
            size=(1300, 760),
        )

        # Left Sidebar Navigation
        self.sidebar = SidebarNav(on_select=self.switch_view, active_key="clones", app=self)
        apply_cocoa_sidebar_material(self.sidebar)

        # Right-side dynamic view container
        self.content_container = toga.Box(style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_WINDOW))
        self.content_container.add(self.clone_view)

        # Root layout box
        self.root_box = toga.Box(style=Pack(direction=ROW, flex=1))
        self.root_box.add(self.sidebar)
        self.root_box.add(self.content_container)

        self.main_window.content = self.root_box
        set_window_min_size(self.main_window, 980, 640)
        self.main_window.on_hide = self._on_window_hide
        self.main_window.on_close = self._on_window_close
        self.main_window.on_resize = self._on_window_resize
        self._resize_debounce = None
        self.on_exit = self._on_app_exit
        self.main_window.show()
        # Modern full-height chrome (content under a transparent titlebar).
        configure_cocoa_window_chrome(self.main_window)
        # The sidebar bounds are only known after the first layout pass.
        async def _refresh_sidebar_material() -> None:
            await asyncio.sleep(0.2)
            update_cocoa_sidebar_material(self.sidebar)

        self.safe_create_task(_refresh_sidebar_material())
        # Enable window drag from top bar background (macOS HIG drag zone)
        configure_cocoa_window_movable(self.main_window)

        # Initialize native system tray service
        self.tray_service = TrayService(app=self)
        if bool(get_config_value("minimize_to_tray", False)):
            self.tray_service.enable()

        # Initial refresh
        self.safe_create_task(self.clone_view.refresh_clones())

        # Defensive startup check, then land brand-new users on Environments
        async def _startup_checks():
            ok = await self._startup_environment_check()
            if ok:
                await self._maybe_first_run_redirect()

        self.safe_create_task(_startup_checks())

        # Replay Cocoa teardown deferred by worker threads onto the main thread.
        self.safe_create_task(self._drain_deferred_cocoa_work())

    async def _drain_deferred_cocoa_work(self) -> None:
        """Flush queued AppKit cleanup from the main thread.

        Toga finalizers can run during a garbage collection on a background
        thread; removing Auto Layout constraints off the main thread aborts the
        process, so the work is queued and replayed here.
        """
        while True:
            await asyncio.sleep(0.2)
            drain_pending_cocoa_work()

    async def _startup_environment_check(self) -> bool:
        """Defensively verify xcode-select toolchain on startup and auto-navigate to Doctor if missing."""
        try:
            logger.info("Executing defensive startup check for Xcode Command Line Tools...")
            is_installed = await self.doctor_service.check_xcode_select_installed()
            if not is_installed:
                logger.warning("Xcode Command Line Tools missing or unconfigured! Redirecting to doctor view.")
                if hasattr(self, "sidebar") and self.sidebar:
                    self.sidebar.select_item("doctor")
                else:
                    self.switch_view("doctor")
                return False
            return True
        except Exception as e:
            logger.warning(f"Unexpected error in _startup_environment_check: {e}")
            return True

    async def _maybe_first_run_redirect(self) -> None:
        """Land brand-new users on the Environments page — the product's core workflow."""
        try:
            loop = asyncio.get_running_loop()
            clones = await self.clone_service.list_clones()
            envs = await loop.run_in_executor(None, self.environment_service.list_environments)
            if not clones and not envs:
                logger.info("First run detected (no clones, no environments); starting on Environments.")
                if hasattr(self, "sidebar") and self.sidebar:
                    self.sidebar.select_item("environments")
                else:
                    self.switch_view("environments")
        except Exception as e:
            logger.debug(f"First-run redirect skipped: {e}")

    def _on_window_resize(self, *args):
        """Debounce window resizes, then forward the new width to the active view."""
        try:
            if self._resize_debounce is not None:
                self._resize_debounce.cancel()
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._resize_debounce = loop.call_later(0.25, self._dispatch_window_resize)

    def _dispatch_window_resize(self):
        self._resize_debounce = None
        view_names = {
            "clones": "clone_view",
            "environments": "environment_view",
            "recipes": "recipe_view",
            "probe": "probe_view",
            "doctor": "doctor_view",
            "logs": "logs_view",
            "settings": "settings_view",
        }
        attr = view_names.get(self.current_view_name)
        view = getattr(self, attr, None) if attr else None
        if view is None or not hasattr(view, "on_window_resize"):
            return
        try:
            width = int(self.main_window.size[0])
        except Exception:
            return
        update_cocoa_sidebar_material(self.sidebar)
        view.on_window_resize(width)

    def _maybe_refresh_appearance(self) -> bool:
        """Re-check the system appearance; rebuild the UI if Dark Mode toggled since startup."""
        try:
            previous = is_dark_mode()
            current = refresh_dark_mode_cache()
        except Exception:
            return False
        if current == previous:
            return False
        logger.info("System appearance changed; rebuilding UI with the new palette.")
        Theme.apply_mode(current)
        apply_cocoa_appearance(current)
        self.retranslate_ui()
        return True

    def _on_window_hide(self, window: Any) -> None:
        """Handle window minimize/hide event when tray mode is active."""
        if hasattr(self, "tray_service") and self.tray_service and self.tray_service.is_enabled:
            try:
                native_win = getattr(getattr(window, "_impl", None), "native", None)
                if native_win and hasattr(native_win, "orderOut_"):
                    native_win.orderOut_(None)
                set_macos_dock_visible(False)
            except Exception as e:
                logger.debug(f"Error hiding window to tray: {e}")

    def _on_window_close(self, window: Any) -> bool:
        """Handle window close event: hide to tray if minimize_to_tray is enabled, else allow exit."""
        # If we are already in the process of exiting, allow the close unconditionally.
        if self._is_exiting:
            return True
        if hasattr(self, "tray_service") and self.tray_service and self.tray_service.is_enabled:
            try:
                native_win = getattr(getattr(window, "_impl", None), "native", None)
                if native_win and hasattr(native_win, "orderOut_"):
                    native_win.orderOut_(None)
                set_macos_dock_visible(False)
                return False
            except Exception as e:
                logger.debug(f"Error intercepting window close for tray: {e}")
        return True

    def _on_app_exit(self, app: Any) -> bool:
        """Handle application exit event: teardown tray icon, restore dock, and allow shutdown."""
        logger.info("Application shutdown initiated via on_exit hook.")
        # Mark as exiting so that any pending on_close handlers don't block the exit.
        self._is_exiting = True
        try:
            if hasattr(self, "tray_service") and self.tray_service:
                self.tray_service.disable()
            set_macos_dock_visible(True)
        except Exception as e:
            logger.warning(f"Error during on_app_exit cleanup: {e}")
        # Deregister live log listener to avoid dangling reference in logger._listeners
        try:
            if hasattr(self, "logs_view") and self.logs_view and hasattr(self.logs_view, "cleanup"):
                self.logs_view.cleanup()
        except Exception:
            pass
        return True

    def show_main_window(self) -> None:
        """Bring main window to front and activate application from tray or background."""
        try:
            if not hasattr(self, "main_window") or not self.main_window:
                return

            # 0. Ensure Dock icon is visible when restoring main window
            set_macos_dock_visible(True)

            # 1. Cocoa native unhide and activate application
            if sys.platform == "darwin":
                try:
                    from toga_cocoa.libs.appkit import NSApplication
                    if NSApplication is not None and hasattr(NSApplication, "sharedApplication"):
                        ns_app = NSApplication.sharedApplication
                        if hasattr(ns_app, "unhide_"):
                            ns_app.unhide_(None)
                        if hasattr(ns_app, "activateIgnoringOtherApps_"):
                            ns_app.activateIgnoringOtherApps_(True)
                        elif hasattr(ns_app, "activate"):
                            ns_app.activate()
                except Exception as e:
                    logger.debug(f"Failed activating NSApplication: {e}")

            # 2. Reset any pending state transition in Toga
            impl = getattr(self.main_window, "_impl", None)
            if impl and hasattr(impl, "_pending_state_transition"):
                impl._pending_state_transition = None

            # 3. Cocoa native deminiaturize & bring window to front
            if sys.platform == "darwin" and impl:
                native_win = getattr(impl, "native", None)
                if native_win is not None:
                    try:
                        if getattr(native_win, "isMiniaturized", False):
                            if hasattr(native_win, "deminiaturize_"):
                                native_win.deminiaturize_(None)
                        if hasattr(native_win, "setIsVisible_"):
                            native_win.setIsVisible_(True)
                        if hasattr(native_win, "makeKeyAndOrderFront_"):
                            native_win.makeKeyAndOrderFront_(None)
                        if hasattr(native_win, "orderFrontRegardless"):
                            native_win.orderFrontRegardless()
                        if hasattr(native_win, "makeMainWindow"):
                            native_win.makeMainWindow()
                        if hasattr(native_win, "makeKeyWindow"):
                            native_win.makeKeyWindow()
                    except Exception as e:
                        logger.debug(f"Failed native window restore: {e}")

            # 4. Toga window state synchronization
            try:
                if self.main_window.state != WindowState.NORMAL:
                    if impl and hasattr(impl, "_apply_state"):
                        impl._apply_state(WindowState.NORMAL)
            except Exception:
                pass

            # 5. Toga show fallback if still not visible
            try:
                if not self.main_window.visible:
                    self.main_window.show()
            except Exception:
                pass

            # 6. Re-activate app again to ensure key window focus
            if sys.platform == "darwin":
                try:
                    from toga_cocoa.libs.appkit import NSApplication
                    if NSApplication is not None and hasattr(NSApplication, "sharedApplication"):
                        ns_app = NSApplication.sharedApplication
                        if hasattr(ns_app, "activateIgnoringOtherApps_"):
                            ns_app.activateIgnoringOtherApps_(True)
                except Exception:
                    pass

        except Exception as e:
            logger.warning(f"Error restoring main window: {e}")

    def exit_application(self) -> None:
        """Cleanly terminate the application and remove status tray icon."""
        logger.info("exit_application called — beginning forced shutdown sequence.")
        # Set the exiting flag first so that _on_window_close never blocks the shutdown.
        self._is_exiting = True
        try:
            if hasattr(self, "tray_service") and self.tray_service:
                self.tray_service.disable()
        except Exception as e:
            logger.warning(f"Error disabling tray during exit: {e}")
        # Do NOT call set_macos_dock_visible(True) here: restoring the Dock activation
        # policy just before loop.stop() can cause the run loop to process additional
        # events that block the exit. The Dock icon vanishes automatically on process end.
        self.exit()

    def switch_view(self, view_name: str):
        """Switch right content area between feature views."""
        if self._maybe_refresh_appearance():
            # retranslate_ui() already rebuilt and re-mounted the active view.
            return
        self.current_view_name = view_name

        # Clear content container
        while len(self.content_container.children) > 0:
            self.content_container.remove(self.content_container.children[0])

        if view_name == "clones":
            self.content_container.add(self.clone_view)
            self.safe_create_task(self.clone_view.refresh_clones())
        elif view_name == "environments":
            self.content_container.add(self.environment_view)
            self.safe_create_task(self.environment_view.refresh_environments())
        elif view_name == "recipes":
            self.content_container.add(self.recipe_view)
            self.safe_create_task(self.recipe_view.refresh_recipes())
        elif view_name == "probe":
            self.content_container.add(self.probe_view)
        elif view_name == "doctor":
            self.content_container.add(self.doctor_view)
            self.safe_create_task(self.doctor_view.run_checks())
        elif view_name == "logs":
            self.content_container.add(self.logs_view)
            self.logs_view.reload_from_disk()
        elif view_name == "settings":
            self.content_container.add(self.settings_view)

    def action_new_clone(self, widget: Any):
        async def _on_complete():
            await self.clone_view.refresh_clones()
            self.logs_view.log_info("Cloning wizard finished successfully.")

        wizard = WizardWindow(
            clone_service=self.clone_service,
            probe_service=self.probe_service,
            on_complete=_on_complete,
        )
        wizard.show()

    def action_refresh_current(self, widget: Any):
        if self.current_view_name == "clones":
            self.safe_create_task(self.clone_view.refresh_clones())
        elif self.current_view_name == "environments":
            self.safe_create_task(self.environment_view.refresh_environments())
        elif self.current_view_name == "recipes":
            self.safe_create_task(self.recipe_view.refresh_recipes())
        elif self.current_view_name == "doctor":
            self.safe_create_task(self.doctor_view.run_checks())

    def retranslate_ui(self):
        """Dynamically refresh all UI components and views after language change."""
        if hasattr(self, "sidebar") and self.sidebar:
            self.sidebar.retranslate()

        if hasattr(self, "tray_service") and self.tray_service:
            self.tray_service.retranslate()

        # Clean up existing views before recreating to avoid memory/listener leaks
        if hasattr(self, "logs_view") and self.logs_view and hasattr(self.logs_view, "cleanup"):
            self.logs_view.cleanup()

        # Re-initialize views with updated localized strings
        self.clone_view = CloneListView(clone_service=self.clone_service, app=self)
        self.environment_view = EnvironmentListView(
            environment_service=self.environment_service,
            app=self,
        )
        self.recipe_view = RecipeListView(recipe_service=self.recipe_service, app=self)
        self.probe_view = ProbeView(probe_service=self.probe_service, recipe_service=self.recipe_service, app=self)
        self.doctor_view = DoctorView(doctor_service=self.doctor_service, app=self)
        self.logs_view = LogsView(app=self)
        self.settings_view = SettingsView(app=self)

        # Re-mount currently active view
        self.switch_view(self.current_view_name)

