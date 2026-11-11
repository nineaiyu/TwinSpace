"""Right-click Dock menu: environments and the most recently used clones.

The menu is rebuilt on every Dock interaction (macOS calls the
``applicationDockMenu:`` delegate each time), so entries always reflect the
current environments and launch history.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import Any

import toga

from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.state import CloneRecord
from twinspace.core.timestamps import parse_iso_timestamp

logger = get_logger("gui.dock_menu")

try:
    from rubicon.objc import SEL, NSObject, objc_method
    from toga_cocoa.libs.appkit import NSMenu, NSMenuItem
except Exception:  # pragma: no cover - non-macOS tooling
    NSObject = object
    objc_method = lambda fn: fn  # noqa: E731
    NSMenu = None
    NSMenuItem = None

_MAX_DOCK_CLONES = 5


def _app() -> toga.App | None:
    try:
        return toga.App.app
    except Exception:
        return None


def _recent_key(record: CloneRecord) -> tuple[int, float]:
    stamp = parse_iso_timestamp(getattr(record, "last_opened_at", ""))
    if stamp is None:
        return (0, 0.0)
    try:
        return (1, stamp.timestamp())
    except (OSError, OverflowError, ValueError):
        return (1, 0.0)


def _launch_clone(clone_name: str) -> None:
    app = _app()
    if app is None:
        return
    try:
        records = app.clone_service.state_manager.load()
        record = next(
            (item for item in records if item.clone_name == clone_name), None
        )
        if record is None:
            return
        clone_view = getattr(app, "clone_view", None)
        loop = getattr(app, "loop", None)
        if clone_view is not None and loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(clone_view.on_launch_clone(record), loop)
        else:
            subprocess.Popen(["open", str(record.dest_path)])
    except Exception as exc:
        logger.warning("Dock quick launch failed for %s: %s", clone_name, exc)


def _env_action(env_name: str, action: str) -> None:
    app = _app()
    if app is None:
        return
    try:
        service = getattr(app, "environment_service", None)
        if service is None:
            return
        from twinspace.gui.services.tray_service import _tray_launch_interval

        interval = _tray_launch_interval()
        if action == "open":
            worker = lambda: service.open_environment(  # noqa: E731
                env_name, interval=interval
            )
        else:
            worker = lambda: service.switch_environment(  # noqa: E731
                env_name, interval=interval
            )
        loop = getattr(app, "loop", None)
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(
                _run_and_refresh(app, worker), loop
            )
        else:
            worker()
    except Exception as exc:
        logger.warning("Dock environment action failed for %s: %s", env_name, exc)


async def _run_and_refresh(app: Any, worker) -> None:  # noqa: ANN401
    try:
        await asyncio.get_running_loop().run_in_executor(None, worker)
    except Exception as exc:
        logger.warning("Dock environment action error: %s", exc)
    try:
        env_view = getattr(app, "environment_view", None)
        if env_view is not None:
            await env_view.refresh_environments(show_loading=False)
    except Exception:
        pass
    try:
        clone_view = getattr(app, "clone_view", None)
        if clone_view is not None:
            await clone_view.refresh_clones()
    except Exception:
        pass


class DockMenuTarget(NSObject):
    """Action target for Dock menu items; survives via a module-level ref."""

    @objc_method
    def openClone_(self, sender) -> None:
        _launch_clone(str(sender.representedObject() or ""))

    @objc_method
    def envOpen_(self, sender) -> None:
        _env_action(str(sender.representedObject() or ""), "open")

    @objc_method
    def envSwitch_(self, sender) -> None:
        _env_action(str(sender.representedObject() or ""), "switch")


_TARGET: DockMenuTarget | None = None


def _target() -> "DockMenuTarget | None":
    global _TARGET
    if _TARGET is None and NSObject is not object:
        try:
            _TARGET = DockMenuTarget.alloc().init()
        except Exception:
            logger.debug("Could not create dock menu target", exc_info=True)
    return _TARGET


def _add_section_header(menu, label: str) -> None:
    if NSMenuItem is None:
        return
    header = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, None, "")
    if hasattr(header, "setEnabled_"):
        header.setEnabled_(False)
    menu.addItem_(header)


def build_dock_menu():
    """Build the Dock menu; returns an NSMenu or None when unavailable."""
    if NSMenu is None or NSMenuItem is None:
        return None
    try:
        app = _app()
        if app is None:
            return None
        menu = NSMenu.alloc().init()
        target = _target()
        if target is None:
            return None

        service = getattr(app, "environment_service", None)
        environments = service.list_environments() if service else []
        if environments:
            _add_section_header(menu, t("tray_menu_environments"))
            for env in environments:
                env_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    env.name, None, ""
                )
                submenu = NSMenu.alloc().initWithTitle_(env.name)
                for selector, label_key, action in (
                    ("envOpen:", "tray_env_open", "open"),
                    ("envSwitch:", "tray_env_switch", "switch"),
                ):
                    sub_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        t(label_key), SEL(selector), ""
                    )
                    sub_item.setRepresentedObject_(env.name)
                    sub_item.setTarget_(target)
                    submenu.addItem_(sub_item)
                env_item.setSubmenu_(submenu)
                menu.addItem_(env_item)
            menu.addItem_(NSMenuItem.separatorItem())

        state_manager = getattr(getattr(app, "clone_service", None), "state_manager", None)
        if state_manager is not None:
            records = state_manager.load()
            records.sort(key=_recent_key, reverse=True)
            recent = [r for r in records if _recent_key(r)[0]][:_MAX_DOCK_CLONES]
            if recent:
                _add_section_header(menu, t("tray_menu_quick_launch"))
                for record in recent:
                    item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                        record.clone_name, SEL("openClone:"), ""
                    )
                    item.setRepresentedObject_(record.clone_name)
                    item.setTarget_(target)
                    menu.addItem_(item)
        return menu
    except Exception:
        logger.debug("Dock menu build failed", exc_info=True)
        return None
