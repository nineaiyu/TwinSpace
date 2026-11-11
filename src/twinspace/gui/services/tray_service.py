"""macOS Cocoa native menu bar status item (tray) service for TwinSpace."""

import asyncio
import sys
from pathlib import Path
from typing import Any

from twinspace.core.config import get_config_value
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.resources import get_app_icon_path
from twinspace.core.state import CloneRecord
from twinspace.core.timestamps import parse_iso_timestamp

logger = get_logger("gui.tray")


def _tray_launch_interval() -> float:
    """Configured stagger between environment app launches, clamped to 0-30s."""
    try:
        return max(0.0, min(float(get_config_value("launch_interval", 2.0) or 0), 30.0))
    except (TypeError, ValueError):
        return 2.0


def _tray_recent_key(record: CloneRecord) -> tuple[int, float]:
    """Sort value by last-opened recency; never-opened clones rank lowest."""
    stamp = parse_iso_timestamp(getattr(record, "last_opened_at", ""))
    if stamp is None:
        return (0, 0.0)
    try:
        return (1, stamp.timestamp())
    except (OSError, OverflowError, ValueError):
        return (1, 0.0)

try:
    from rubicon.objc import SEL, NSObject, NSSize, objc_method
    from toga_cocoa.libs.appkit import (
        NSApplication,
        NSImage,
        NSMenu,
        NSMenuItem,
        NSStatusBar,
    )
except Exception:
    NSApplication = None
    NSStatusBar = None
    NSMenu = None
    NSMenuItem = None
    NSImage = None
    NSObject = object
    objc_method = lambda fn: fn
    NSSize = None
    SEL = lambda name: name


class TrayCallbackTarget(NSObject):
    """Objective-C target object to receive Cocoa NSStatusBarButton click events."""

    @objc_method
    def onTrayClicked_(self, sender) -> None:
        if hasattr(self, "_tray_service") and self._tray_service:
            self._tray_service._handle_click(sender)

    @objc_method
    def onMenuShow_(self, sender) -> None:
        if hasattr(self, "_tray_service") and self._tray_service:
            self._tray_service.on_menu_show()

    @objc_method
    def onMenuLaunchClone_(self, sender) -> None:
        if hasattr(self, "_tray_service") and self._tray_service:
            self._tray_service.on_menu_launch_clone(sender)

    @objc_method
    def onMenuEnvOpen_(self, sender) -> None:
        if hasattr(self, "_tray_service") and self._tray_service:
            self._tray_service.on_menu_env_action(sender, "open")

    @objc_method
    def onMenuEnvQuit_(self, sender) -> None:
        if hasattr(self, "_tray_service") and self._tray_service:
            self._tray_service.on_menu_env_action(sender, "quit")

    @objc_method
    def onMenuEnvSwitch_(self, sender) -> None:
        if hasattr(self, "_tray_service") and self._tray_service:
            self._tray_service.on_menu_env_action(sender, "switch")

    @objc_method
    def onMenuQuit_(self, sender) -> None:
        if hasattr(self, "_tray_service") and self._tray_service:
            self._tray_service.on_menu_quit()


class TrayService:
    """Manages the lifecycle, appearance, and event dispatch of the macOS status tray icon."""

    def __init__(self, app: Any):
        self._menu = None
        self.app = app
        self._status_item: Any = None
        self._target: Any = None
        self._is_enabled: bool = False

    @property
    def is_enabled(self) -> bool:
        return self._is_enabled

    def enable(self) -> bool:
        if self._is_enabled or sys.platform != "darwin" or NSStatusBar is None:
            return False
        try:
            # -2 represents NSSquareStatusItemLength; -1 represents NSVariableStatusItemLength
            self._status_item = NSStatusBar.systemStatusBar.statusItemWithLength_(-2)
            button = getattr(self._status_item, "button", None)
            if button is not None:
                icon_path = get_app_icon_path("png")
                if icon_path and Path(icon_path).exists() and NSImage is not None:
                    try:
                        img = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
                        if img:
                            if NSSize is not None:
                                img.setSize_(NSSize(18, 18))
                            if hasattr(button, "setImage_"):
                                button.setImage_(img)
                    except Exception as e:
                        logger.debug(f"Could not set tray icon image: {e}")

                if hasattr(button, "setToolTip_"):
                    button.setToolTip_("TwinSpace")

                if NSObject is not object and hasattr(TrayCallbackTarget, "alloc"):
                    self._target = TrayCallbackTarget.alloc().init()
                    self._target._tray_service = self

                    if hasattr(button, "setTarget_"):
                        button.setTarget_(self._target)
                    if hasattr(button, "setAction_"):
                        button.setAction_(SEL("onTrayClicked:"))
                    # NSEventMaskLeftMouseDown = 1 << 1, NSEventMaskLeftMouseUp = 1 << 2, NSEventMaskRightMouseDown = 1 << 3, NSEventMaskRightMouseUp = 1 << 4
                    if hasattr(button, "sendActionOn_"):
                        button.sendActionOn_((1 << 1) | (1 << 2) | (1 << 3) | (1 << 4))

            self._is_enabled = True
            logger.info("System tray icon enabled successfully.")
            return True
        except Exception as e:
            logger.warning(f"Failed to enable system tray icon: {e}")
            self._status_item = None
            self._is_enabled = False
            return False

    def disable(self) -> None:
        if not self._is_enabled or self._status_item is None:
            self._is_enabled = False
            return
        try:
            button = getattr(self._status_item, "button", None)
            if button is not None:
                if hasattr(button, "setTarget_"):
                    button.setTarget_(None)
                if hasattr(button, "setAction_"):
                    button.setAction_(None)
            if NSStatusBar is not None and hasattr(NSStatusBar, "systemStatusBar"):
                NSStatusBar.systemStatusBar.removeStatusItem_(self._status_item)
        except Exception as e:
            logger.warning(f"Error removing status item: {e}")
        self._status_item = None
        self._target = None
        self._menu = None
        self._is_enabled = False
        logger.info("System tray icon disabled.")

    def _handle_click(self, sender: Any) -> None:
        """Handle left vs right mouse button click events."""
        try:
            current_event = None
            if NSApplication is not None and hasattr(NSApplication, "sharedApplication"):
                app = NSApplication.sharedApplication
                if hasattr(app, "currentEvent"):
                    ce = app.currentEvent
                    current_event = ce() if callable(ce) else ce

            is_right_click = False
            if current_event is not None:
                event_type = getattr(current_event, "type", None)
                type_val = getattr(event_type, "value", event_type)
                # NSEventTypeRightMouseDown = 3, NSEventTypeRightMouseUp = 4
                if type_val in (3, 4):
                    is_right_click = True
                else:
                    # Check for Control + Click modifier (NSEventModifierFlagControl = 0x40000)
                    mod_flags = getattr(current_event, "modifierFlags", 0)
                    mod_val = getattr(mod_flags, "value", mod_flags)
                    if isinstance(mod_val, int) and (mod_val & 0x40000):
                        is_right_click = True

            logger.info(f"Tray clicked, is_right_click={is_right_click}")

            if is_right_click:
                self.show_context_menu()
            else:
                self.on_menu_show()
        except Exception as e:
            logger.warning(f"Error determining click event type: {e}")
            self.on_menu_show()

    def show_context_menu(self) -> None:
        """Build and popup the context NSMenu for right-click."""
        if not self._status_item or NSMenu is None or NSMenuItem is None:
            return
        try:
            self._menu = NSMenu.alloc().init()
            if hasattr(self._menu, "setAutoenablesItems_"):
                self._menu.setAutoenablesItems_(True)

            item_show = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                t("tray_menu_show"),
                SEL("onMenuShow:"),
                "",
            )
            if self._target and hasattr(item_show, "setTarget_"):
                item_show.setTarget_(self._target)
            self._menu.addItem_(item_show)

            if hasattr(NSMenuItem, "separatorItem"):
                sep = NSMenuItem.separatorItem()
                self._menu.addItem_(sep)

            self._add_quick_launch_items()

            self._add_environment_items()

            item_quit = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                t("tray_menu_quit"),
                SEL("onMenuQuit:"),
                "",
            )
            if self._target and hasattr(item_quit, "setTarget_"):
                item_quit.setTarget_(self._target)
            self._menu.addItem_(item_quit)

            if hasattr(self._status_item, "popUpStatusItemMenu_"):
                self._status_item.popUpStatusItemMenu_(self._menu)
        except Exception as e:
            logger.warning(f"Failed to popup context menu: {e}")

    def on_menu_show(self) -> None:
        if self.app and hasattr(self.app, "show_main_window"):
            self.app.show_main_window()

    def _add_quick_launch_items(self) -> None:
        """List the most recently used clones for one-click launching."""
        if NSMenuItem is None:
            return
        try:
            state_manager = getattr(
                getattr(self.app, "clone_service", None), "state_manager", None
            )
            if state_manager is None:
                return
            records = state_manager.load()
            records.sort(key=_tray_recent_key, reverse=True)

            header = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                t("tray_menu_quick_launch"),
                None,
                "",
            )
            if hasattr(header, "setEnabled_"):
                header.setEnabled_(False)
            self._menu.addItem_(header)

            shown = 0
            for record in records:
                if shown >= 8:
                    break
                item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    record.clone_name,
                    SEL("onMenuLaunchClone:"),
                    "",
                )
                if hasattr(item, "setRepresentedObject_"):
                    item.setRepresentedObject_(record.clone_name)
                if self._target and hasattr(item, "setTarget_"):
                    item.setTarget_(self._target)
                self._menu.addItem_(item)
                shown += 1
            if shown and hasattr(NSMenuItem, "separatorItem"):
                self._menu.addItem_(NSMenuItem.separatorItem())
        except Exception as e:
            logger.debug(f"Tray quick-launch items failed: {e}")

    def _add_environment_items(self) -> None:
        """One submenu per environment: open all / quit all / switch here."""
        if NSMenu is None or NSMenuItem is None or not self._target:
            return
        try:
            service = getattr(self.app, "environment_service", None)
            if service is None:
                return
            environments = service.list_environments()
            if not environments:
                return

            header = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                t("tray_menu_environments"),
                None,
                "",
            )
            if hasattr(header, "setEnabled_"):
                header.setEnabled_(False)
            self._menu.addItem_(header)

            for env in environments:
                env_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    env.name,
                    None,
                    "",
                )
                submenu = NSMenu.alloc().initWithTitle_(env.name)
                for selector, label_key in (
                    ("onMenuEnvOpen:", "tray_env_open"),
                    ("onMenuEnvQuit:", "tray_env_quit"),
                    ("onMenuEnvSwitch:", "tray_env_switch"),
                ):
                    sub_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        t(label_key),
                        SEL(selector),
                        "",
                    )
                    if hasattr(sub_item, "setRepresentedObject_"):
                        sub_item.setRepresentedObject_(env.name)
                    if hasattr(sub_item, "setTarget_"):
                        sub_item.setTarget_(self._target)
                    submenu.addItem_(sub_item)
                if hasattr(env_item, "setSubmenu_"):
                    env_item.setSubmenu_(submenu)
                self._menu.addItem_(env_item)

            if hasattr(NSMenuItem, "separatorItem"):
                self._menu.addItem_(NSMenuItem.separatorItem())
        except Exception as e:
            logger.debug(f"Tray environment items failed: {e}")

    def on_menu_env_action(self, sender: Any, action: str) -> None:
        """Open/quit/switch an environment chosen from the tray menu."""
        try:
            env_name = str(getattr(sender, "representedObject", "") or "")
            if not env_name:
                return
            service = getattr(self.app, "environment_service", None)
            if service is None:
                return
            interval = _tray_launch_interval()
            if action == "open":
                worker = lambda: service.open_environment(  # noqa: E731
                    env_name, interval=interval
                )
            elif action == "quit":
                worker = lambda: service.quit_environment(env_name)  # noqa: E731
            else:
                worker = lambda: service.switch_environment(  # noqa: E731
                    env_name, interval=interval
                )
            loop = getattr(self.app, "loop", None)
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(self._run_env_action(worker), loop)
            else:
                worker()
        except Exception as e:
            logger.warning(f"Tray environment action failed: {e}")

    async def _run_env_action(self, worker) -> None:
        try:
            await asyncio.get_running_loop().run_in_executor(None, worker)
        except Exception as e:
            logger.warning(f"Tray environment action error: {e}")
        # Both pages hold running-state caches; refresh them in place.
        try:
            env_view = getattr(self.app, "environment_view", None)
            if env_view is not None:
                await env_view.refresh_environments(show_loading=False)
        except Exception:
            pass
        try:
            clone_view = getattr(self.app, "clone_view", None)
            if clone_view is not None:
                await clone_view.refresh_clones()
        except Exception:
            pass

    def on_menu_launch_clone(self, sender: Any) -> None:
        """Launch (or bring to front) the clone chosen from the tray menu."""
        try:
            import asyncio
            import subprocess

            clone_name = str(getattr(sender, "representedObject", "") or "")
            if not clone_name:
                return
            clone_view = getattr(self.app, "clone_view", None)
            state_manager = getattr(
                getattr(self.app, "clone_service", None), "state_manager", None
            )
            record = None
            if state_manager is not None:
                record = next(
                    (
                        item
                        for item in state_manager.load()
                        if item.clone_name == clone_name
                    ),
                    None,
                )
            if record is None:
                return
            loop = getattr(self.app, "loop", None)
            if clone_view is not None and loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    clone_view.on_launch_clone(record), loop
                )
            else:
                subprocess.Popen(["open", str(record.dest_path)])
        except Exception as e:
            logger.warning(f"Tray quick launch failed: {e}")

    def on_menu_quit(self) -> None:
        if self.app and hasattr(self.app, "exit_application"):
            self.app.exit_application()

    def retranslate(self) -> None:
        """Context menu is dynamically generated with localized strings on popup."""
        pass
