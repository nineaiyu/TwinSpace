"""Track when clone bundles were last opened.

Launch timestamps live in the state file, so the "All Clones" page and the
environment cards can show them again after a restart. Explicit open actions
record the launch themselves; NSWorkspace notifications cover bundles started
from Finder, the Dock or another app.
"""

from __future__ import annotations

import weakref
from typing import Any

from twinspace.core.logger import get_logger
from twinspace.core.state import StateManager

from .app_monitor import AppLifecycleMonitor

logger = get_logger("gui.launch_history")

# One recorder per state file: every view bound to the same clones.yaml shares
# it, so a launch notification is persisted and broadcast exactly once.
_INSTANCES: weakref.WeakValueDictionary[str, "LaunchHistory"] = weakref.WeakValueDictionary()


def launch_history_for(state_manager: StateManager) -> "LaunchHistory":
    """Return the recorder shared by the views bound to ``state_manager``."""
    key = str(state_manager.state_file)
    history = _INSTANCES.get(key)
    if history is None:
        history = LaunchHistory(state_manager)
        _INSTANCES[key] = history
    return history


class LaunchHistory:
    """Persist last-opened timestamps and broadcast them to the GUI."""

    def __init__(self, state_manager: StateManager):
        self.state_manager = state_manager
        self._listeners: weakref.WeakSet[Any] = weakref.WeakSet()
        AppLifecycleMonitor.shared().subscribe(self)

    # -- subscriptions ---------------------------------------------------
    def subscribe(self, owner: Any) -> None:
        """Listeners expose ``handle_clone_opened(clone_name, timestamp)``."""
        try:
            self._listeners.add(owner)
        except TypeError:
            logger.debug("Launch listener is not weak-referenceable: %r", owner)

    def unsubscribe(self, owner: Any) -> None:
        self._listeners.discard(owner)

    # -- recording -------------------------------------------------------
    def mark_opened(self, clone_name: str, timestamp: str | None = None) -> str | None:
        """Persist a launch; safe to call off the UI thread.

        Returns the stored timestamp, or ``None`` when the clone is unknown.
        """
        try:
            result = self.state_manager.mark_opened(clone_name, timestamp=timestamp)
        except Exception:
            logger.debug("Could not record launch of %s", clone_name, exc_info=True)
            return None
        return result[1] if result else None

    def handle_app_state_change(self, bundle_path: str, running: bool) -> None:
        """NSWorkspace reported a bundle launching or terminating."""
        if not running:
            return
        try:
            result = self.state_manager.mark_opened(dest_path=bundle_path)
        except Exception:
            logger.debug("Could not record launch of %s", bundle_path, exc_info=True)
            return
        if result is None:
            return
        clone_name, timestamp = result
        self._notify(clone_name, timestamp)

    def _notify(self, clone_name: str, timestamp: str) -> None:
        for owner in list(self._listeners):
            handler = getattr(owner, "handle_clone_opened", None)
            if handler is None:
                continue
            try:
                handler(clone_name, timestamp)
            except Exception:
                logger.debug("Launch listener failed", exc_info=True)
