"""Live running-state tracking for cloned application bundles.

Refreshing the environment page used to fork ``ps -axo command=`` and scan the
whole process table just to colour a few status dots. NSWorkspace already knows
which application bundles are running and posts launch/terminate notifications,
so the GUI can stay accurate with zero subprocess work and react to an app
opening or closing the moment it happens.
"""

from __future__ import annotations

import ctypes
import sys
import weakref
from typing import Any

from twinspace.core.logger import get_logger

logger = get_logger("gui.app_monitor")

LAUNCH_NOTIFICATION = "NSWorkspaceDidLaunchApplicationNotification"
TERMINATE_NOTIFICATION = "NSWorkspaceDidTerminateApplicationNotification"
APPLICATION_KEY = "NSWorkspaceApplicationKey"

# Resolved `NSString * const` values, keyed by symbol name.
_CONSTANTS: dict[str, Any] = {}


def _appkit_constant(name: str) -> Any:
    """Resolve an exported AppKit ``NSString * const``.

    The literal value of these constants matches the symbol name, so falling
    back to the name keeps notification matching working on older runtimes.
    """
    if name in _CONSTANTS:
        return _CONSTANTS[name]
    value: Any = name
    try:
        from rubicon.objc import ObjCInstance
        from rubicon.objc.runtime import load_library

        address = ctypes.c_void_p.in_dll(load_library("AppKit"), name).value
        if address:
            value = ObjCInstance(address)
    except Exception:
        logger.debug("Could not resolve AppKit constant %s", name, exc_info=True)
    _CONSTANTS[name] = value
    return value


if sys.platform == "darwin":
    from rubicon.objc import NSObject, objc_method

    class _WorkspaceObserver(NSObject):
        """Forwards NSWorkspace launch/terminate notifications to a monitor.

        Everything reaches the monitor through instance attributes: rubicon
        resolves attribute access on the Objective-C side, so plain Python
        methods defined on this class are not visible from the callbacks.
        """

        @objc_method
        def handleLaunch_(self, notification) -> None:
            monitor = getattr(self, "_monitor", None)
            if monitor is not None:
                monitor.handle_notification(notification, True)

        @objc_method
        def handleTerminate_(self, notification) -> None:
            monitor = getattr(self, "_monitor", None)
            if monitor is not None:
                monitor.handle_notification(notification, False)

else:  # pragma: no cover - the GUI only ships on macOS
    _WorkspaceObserver = None


class AppLifecycleMonitor:
    """Watch NSWorkspace for launches and terminations of app bundles.

    Subscribers are weak-referenced objects exposing
    ``handle_app_state_change(bundle_path: str, running: bool)``; they are
    called on the thread that delivered the notification (AppKit's main
    thread).
    """

    _shared: "AppLifecycleMonitor | None" = None

    @classmethod
    def shared(cls) -> "AppLifecycleMonitor":
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def __init__(self) -> None:
        self.available = False
        self._subscribers: "weakref.WeakSet[Any]" = weakref.WeakSet()
        self._workspace: Any = None
        self._center: Any = None
        self._observer: Any = None
        self._install()

    # -- subscriptions ---------------------------------------------------
    def subscribe(self, owner: Any) -> None:
        try:
            self._subscribers.add(owner)
        except TypeError:
            logger.debug("App state subscriber is not weak-referenceable: %r", owner)

    def unsubscribe(self, owner: Any) -> None:
        self._subscribers.discard(owner)

    # -- queries ---------------------------------------------------------
    def running_paths(self) -> set[str] | None:
        """Bundle paths of the running applications, or None when unavailable.

        This is a pure AppKit call: no process is forked and the process table
        is not scanned, which keeps a full refresh in the low milliseconds.
        """
        workspace = self._workspace
        if workspace is None:
            return None
        try:
            paths: set[str] = set()
            for application in workspace.runningApplications():
                try:
                    url = application.bundleURL
                except Exception:
                    continue
                if url is None:
                    continue
                path = str(url.path)
                if path:
                    paths.add(path)
            return paths
        except Exception:
            logger.debug("NSWorkspace running-app snapshot failed", exc_info=True)
            return None

    # -- notifications ---------------------------------------------------
    def _install(self) -> None:
        if sys.platform != "darwin" or _WorkspaceObserver is None:
            return
        try:
            import toga_cocoa.libs.appkit  # noqa: F401  (loads AppKit)
            from rubicon.objc import SEL, ObjCClass

            workspace = ObjCClass("NSWorkspace").sharedWorkspace
            center = workspace.notificationCenter
            observer = _WorkspaceObserver.alloc().init()
            observer._monitor = self
            for selector, name in (
                ("handleLaunch:", LAUNCH_NOTIFICATION),
                ("handleTerminate:", TERMINATE_NOTIFICATION),
            ):
                center.addObserver_selector_name_object_(
                    observer, SEL(selector), _appkit_constant(name), None
                )
            self._workspace = workspace
            self._center = center
            self._observer = observer
            self.available = True
        except Exception as exc:  # pragma: no cover - macOS only in practice
            logger.debug("NSWorkspace lifecycle monitoring unavailable: %s", exc)

    def handle_notification(self, notification: Any, running: bool) -> None:
        """Translate one NSWorkspace notification into a bundle-path event."""
        path = ""
        try:
            info = notification.userInfo
            if info is not None:
                application = info.objectForKey_(_appkit_constant(APPLICATION_KEY))
                url = application.bundleURL if application is not None else None
                if url is not None:
                    path = str(url.path)
        except Exception:
            logger.debug("Could not read workspace notification payload", exc_info=True)
        if path:
            self._notify(path, running)

    def _notify(self, bundle_path: str, running: bool) -> None:
        for owner in list(self._subscribers):
            handler = getattr(owner, "handle_app_state_change", None)
            if handler is None:
                continue
            try:
                handler(bundle_path, running)
            except Exception:
                logger.debug("App state subscriber failed", exc_info=True)

    def close(self) -> None:
        """Stop observing (process exit cleans this up anyway)."""
        if self._center is not None and self._observer is not None:
            try:
                self._center.removeObserver_(self._observer)
            except Exception:
                logger.debug("Could not remove workspace observer", exc_info=True)
        self._center = None
        self._observer = None
        self._workspace = None
        self.available = False
        self._subscribers.clear()
