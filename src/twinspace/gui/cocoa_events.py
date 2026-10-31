"""Native macOS interactions for Toga widgets.

Toga exposes no double-click, right-click or hover events on generic widgets, so
the environment app tiles attach the AppKit primitives directly to the existing
``TogaView``: an ``NSClickGestureRecognizer`` for double clicks, ``NSMenu`` for
the context menu and ``NSTrackingArea`` for hover. The view itself is left
untouched, which keeps Toga's Auto Layout constraints intact.

Everything here must run on the main thread; AppKit raises and aborts the
process when layout or menus are touched from a worker thread.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import toga

from twinspace.core.logger import get_logger

logger = get_logger("gui.cocoa_events")

_MENU_TARGET_MARKER = "_twinspace_menu_target"

_APP_ICON_CACHE: dict[tuple[str, int, float], Any] = {}
_SYMBOL_CACHE: dict[tuple[str, float], Any] = {}

_NSTrackingMouseEnteredAndExited = 0x01
_NSTrackingActiveInActiveApp = 0x40
_NSTrackingInVisibleRect = 0x100

_appkit_ready = False

# Recognizers are installed on every view of a tile (icon, labels, tile frame).
# Nested views can both report the same click, so ignore repeats within this window.
_DOUBLE_CLICK_DEBOUNCE = 0.35
# Same idea for single clicks: one physical click can reach several recognizers,
# and a ⌘-click that toggles the selection twice would cancel itself out.
_SINGLE_CLICK_DEBOUNCE = 0.12

# NSGestureRecognizerState
GESTURE_BEGAN = 1
GESTURE_CHANGED = 2
GESTURE_ENDED = 3
GESTURE_CANCELLED = 4

# NSEventModifierFlags
_MODIFIER_SHIFT = 1 << 17
_MODIFIER_COMMAND = 1 << 20
SHIFT_MODIFIER = _MODIFIER_SHIFT
COMMAND_MODIFIER = _MODIFIER_COMMAND

# NSEventMask for key presses
_KEY_EVENT_MASK = 1 << 10

# NSAlertFirstButtonReturn, returned by ``confirm_with_labels``
_NS_ALERT_FIRST_BUTTON = 1000

# NSEventMask for right clicks
_RIGHT_CLICK_MASK = 1 << 3

# NSEventMask / NSEventType for the left button
_DRAG_EVENT_MASK = (1 << 1) | (1 << 2) | (1 << 6)  # down | up | dragged
_DRAG_EVENT_STATES = {
    1: GESTURE_BEGAN,  # NSEventTypeLeftMouseDown
    6: GESTURE_CHANGED,  # NSEventTypeLeftMouseDragged
    2: GESTURE_ENDED,  # NSEventTypeLeftMouseUp
}

# Selection intents reported to callers that own a multi-selection.
SELECT_REPLACE = "replace"
SELECT_TOGGLE = "toggle"
SELECT_EXTEND = "extend"


@dataclass(frozen=True)
class MenuEntry:
    """One item in a native context menu."""

    key: str
    label: str
    enabled: bool = True
    separator: bool = False


def is_available() -> bool:
    """True when native AppKit interactions can be installed."""
    return sys.platform == "darwin"


def _ensure_appkit() -> bool:
    global _appkit_ready
    if sys.platform != "darwin":
        return False
    if _appkit_ready:
        return True
    try:
        import toga_cocoa.libs.appkit  # noqa: F401  (loads AppKit into the runtime)

        _appkit_ready = True
    except Exception as exc:  # pragma: no cover - macOS only in practice
        logger.debug("AppKit unavailable for native interactions: %s", exc)
    return _appkit_ready


if sys.platform == "darwin":
    # ``objc_id`` is used in the block type hints of ``attach_drag_monitor``;
    # annotations are strings (PEP 563), so it must live in module globals for
    # rubicon's ``typing.get_type_hints`` lookup to succeed.
    from rubicon.objc import NSObject, objc_id, objc_method
    from rubicon.objc.types import NSInteger, NSPoint  # noqa: F401  (block type hints)

    class _MenuTarget(NSObject):
        @objc_method
        def invoke_(self, sender) -> None:
            handler = getattr(self, "_handler", None)
            if handler is None:
                return
            try:
                key = str(sender.representedObject or "")
            except Exception:
                key = ""
            if not key:
                return
            try:
                handler(key)
            except Exception:
                logger.exception("Native menu action failed: %s", key)

    class _SingleClickTarget(NSObject):
        @objc_method
        def handleSingleClick_(self, sender) -> None:
            callback = getattr(self, "_callback", None)
            if callback is None:
                return
            try:
                callback()
            except Exception:
                logger.exception("Click handler failed")

    class _DoubleClickTarget(NSObject):
        @objc_method
        def handleDoubleClick_(self, sender) -> None:
            callback = getattr(self, "_callback", None)
            if callback is None:
                return
            try:
                callback()
            except Exception:
                logger.exception("Double-click handler failed")

    class _HoverTarget(NSObject):
        @objc_method
        def mouseEntered_(self, event) -> None:
            callback = getattr(self, "_on_enter", None)
            if callback is not None:
                try:
                    callback()
                except Exception:
                    logger.debug("Hover enter handler failed", exc_info=True)

        @objc_method
        def mouseExited_(self, event) -> None:
            callback = getattr(self, "_on_exit", None)
            if callback is not None:
                try:
                    callback()
                except Exception:
                    logger.debug("Hover exit handler failed", exc_info=True)

else:  # pragma: no cover - TwinSpace GUI is macOS only
    objc_id = None
    objc_method = None
    NSPoint = None
    NSInteger = None
    _MenuTarget = None
    _SingleClickTarget = None
    _DoubleClickTarget = None
    _HoverTarget = None


def copy_text(text: str) -> bool:
    """Copy text to the macOS clipboard, with a pbcopy fallback."""
    if not text:
        return False
    if sys.platform == "darwin":
        try:
            from rubicon.objc import ObjCClass

            pasteboard = ObjCClass("NSPasteboard").generalPasteboard
            pasteboard.clearContents()
            pasteboard.setString_forType_(text, "public.utf8-plain-text")
            return True
        except Exception:
            logger.debug("NSPasteboard copy failed; falling back to pbcopy", exc_info=True)
    import subprocess

    for cmd in (["/usr/bin/pbcopy"], ["pbcopy"]):
        try:
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-8"))
            if process.returncode == 0:
                return True
        except Exception:
            continue
    return False


def native_of(widget: Any) -> Any | None:
    """Return the underlying NSView/NSControl for a Toga widget."""
    return getattr(getattr(widget, "_impl", None), "native", None)


def _native_views(widget: Any):
    """Yield the native view of a widget and all of its children."""
    native = native_of(widget)
    if native is not None:
        yield native
    for child in getattr(widget, "children", ()) or ():
        yield from _native_views(child)


def load_app_icon(app_path: str | Path, size: float = 64.0) -> Any | None:
    """Return the Finder icon for an app bundle as a cached ``toga.Image``."""
    if not _ensure_appkit():
        return None
    path = Path(app_path)
    try:
        stat = path.stat()
    except OSError:
        return None
    cache_key = (str(path), stat.st_mtime_ns, float(size))
    if cache_key in _APP_ICON_CACHE:
        return _APP_ICON_CACHE[cache_key]
    try:
        from rubicon.objc import ObjCClass
        from rubicon.objc.types import NSSize

        workspace = ObjCClass("NSWorkspace").sharedWorkspace
        native_image = workspace.iconForFile(str(path))
        if native_image is None:
            return None
        if size > 0:
            native_image.setSize_(NSSize(size, size))
        image = toga.Image(native_image)
        _APP_ICON_CACHE[cache_key] = image
        return image
    except Exception as exc:
        logger.debug("Could not load app icon for %s: %s", path, exc)
        return None


def system_symbol_image(name: str, point_size: float = 14.0) -> Any | None:
    """Return an SF Symbol as a native NSImage, or None when unavailable."""
    if not _ensure_appkit():
        return None
    cache_key = (name, float(point_size))
    if cache_key in _SYMBOL_CACHE:
        return _SYMBOL_CACHE[cache_key]
    try:
        from rubicon.objc import ObjCClass

        image_class = ObjCClass("NSImage")
        image = image_class.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if image is None:
            return None
        configuration_class = ObjCClass("NSImageSymbolConfiguration")
        configuration = configuration_class.configurationWithPointSize_weight_(float(point_size), 0)
        if configuration is not None:
            configured = image.imageWithSymbolConfiguration_(configuration)
            if configured is not None:
                image = configured
        _SYMBOL_CACHE[cache_key] = image
        return image
    except Exception as exc:
        logger.debug("Could not load SF Symbol %s: %s", name, exc)
        return None


def system_symbol_toga_image(name: str, point_size: float = 32.0) -> Any | None:
    """Return an SF Symbol wrapped in a ``toga.Image`` for ImageView use."""
    image = system_symbol_image(name, point_size)
    if image is None:
        return None
    try:
        return toga.Image(image)
    except Exception:
        return None


def configure_button_icon(
    button: Any,
    symbol_name: str,
    point_size: float = 14.0,
) -> None:
    """Attach an SF Symbol to a Toga Button while keeping its title."""
    native = native_of(button)
    image = system_symbol_image(symbol_name, point_size)
    if native is None or image is None:
        return
    try:
        image.setTemplate_(True)
        native.setImage_(image)
        native.setImagePosition_(2)  # NSImageLeft
        if hasattr(native, "setImageHugsTitle_"):
            native.setImageHugsTitle_(True)
        if hasattr(native, "setAlignment_"):
            native.setAlignment_(0)  # NSTextAlignmentLeft
    except Exception as exc:
        logger.debug("Could not attach symbol %s to button: %s", symbol_name, exc)


def fade_in(widget: Any, duration: float = 0.18) -> None:
    """Animate a widget from transparent to opaque when it enters the layout."""
    native = native_of(widget)
    if native is None:
        return
    try:
        from rubicon.objc import ObjCClass

        native.setWantsLayer_(True)
        layer = native.layer
        if layer is None:
            return
        animation = ObjCClass("CABasicAnimation").animationWithKeyPath_("opacity")
        animation.setFromValue_(0.0)
        animation.setToValue_(1.0)
        animation.setDuration_(float(duration))
        layer.addAnimation_forKey_(animation, "twinspaceFadeIn")
        layer.setOpacity_(1.0)
    except Exception:
        logger.debug("Could not animate widget", exc_info=True)


def style_primary_button(button: Any) -> None:
    """Tint a primary action button with the system accent color."""
    native = native_of(button)
    if native is None:
        return
    try:
        from rubicon.objc import ObjCClass

        accent = ObjCClass("NSColor").controlAccentColor
        if hasattr(native, "setContentTintColor_"):
            native.setContentTintColor_(accent)
    except Exception:
        logger.debug("Could not style primary button", exc_info=True)


def set_hover_background(
    widget: Any,
    active: bool,
    active_color: str,
    radius: float = 10.0,
) -> None:
    """Toggle a rounded hover surface on a widget's layer."""
    native = native_of(widget)
    if native is None:
        return
    try:
        native.setWantsLayer_(True)
        layer = native.layer
        if layer is None:
            return
        layer.setCornerRadius_(radius)
        if not active:
            layer.setBackgroundColor_(None)
            return
        color = _hex_to_ns_color(active_color)
        if color is not None:
            layer.setBackgroundColor_(color.CGColor)
    except Exception:
        logger.debug("Hover background update failed", exc_info=True)


def _hex_to_ns_color(value: str) -> Any | None:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        red = int(text[0:2], 16) / 255.0
        green = int(text[2:4], 16) / 255.0
        blue = int(text[4:6], 16) / 255.0
    except ValueError:
        return None
    from rubicon.objc import ObjCClass

    color_class = ObjCClass("NSColor")
    return color_class.colorWithSRGBRed_green_blue_alpha_(red, green, blue, 1.0)


def build_menu(
    entries: Sequence[MenuEntry],
    handler: Callable[[str], None],
) -> Any | None:
    """Build an NSMenu whose items dispatch ``handler(key)``."""
    if not entries or not _ensure_appkit():
        return None
    try:
        from rubicon.objc import SEL, ObjCClass

        menu_class = ObjCClass("NSMenu")
        item_class = ObjCClass("NSMenuItem")
        menu = menu_class.alloc().initWithTitle_("")
        menu.setAutoenablesItems_(False)
        target = _MenuTarget.alloc().init()
        target._handler = handler
        for entry in entries:
            if entry.separator:
                menu.addItem_(item_class.separatorItem())
            # The selector must be the full Objective-C form (with the colon);
            # ``SEL("invoke_")`` is a different, non-existent selector and makes
            # every menu item a silent no-op.
            item = item_class.alloc().initWithTitle_action_keyEquivalent_(
                entry.label, SEL("invoke:"), ""
            )
            item.setTarget_(target)
            item.setEnabled_(bool(entry.enabled))
            item.setRepresentedObject_(entry.key)
            menu.addItem_(item)
        menu._target = target
        return menu
    except Exception as exc:
        logger.debug("Could not build native menu: %s", exc)
        return None


def popup_menu(
    anchor_widget: Any,
    entries: Sequence[MenuEntry],
    handler: Callable[[str], None],
) -> None:
    """Show a native context menu anchored to a widget (for a `...` button)."""
    native = native_of(anchor_widget)
    menu = build_menu(entries, handler)
    if native is None or menu is None:
        return
    try:
        refs = list(getattr(anchor_widget, "_twinspace_cocoa_refs", []) or [])
        refs.append(menu)
        menu_target = getattr(menu, "_target", None)
        if menu_target is not None:
            refs.append(menu_target)
        anchor_widget._twinspace_cocoa_refs = refs
    except Exception:
        logger.debug("Could not retain popup menu references", exc_info=True)
    try:
        from rubicon.objc.types import NSMakePoint

        menu.popUpMenuPositioningItem_atLocation_inView_(None, NSMakePoint(0.0, 0.0), native)
    except Exception as exc:
        logger.debug("Could not show native menu: %s", exc)


def attach_activation_observer(owner: Any, on_activate: Callable[[], None]) -> None:
    """Call ``on_activate`` whenever the app becomes the active app again."""
    if not _ensure_appkit():
        return
    try:
        from rubicon.objc import ObjCClass
    except Exception:  # pragma: no cover - rubicon is a hard dependency
        return

    def _observer(notification: objc_id) -> None:
        try:
            on_activate()
        except Exception:
            logger.exception("Activation handler failed")

    try:
        center = ObjCClass("NSNotificationCenter").defaultCenter
        queue = ObjCClass("NSOperationQueue").mainQueue
        token = center.addObserverForName_object_queue_usingBlock_(
            "NSApplicationDidBecomeActiveNotification", None, queue, _observer
        )
    except Exception:
        logger.debug("Could not observe app activation", exc_info=True)
        return
    if token is None:
        return
    _retain(owner, [token, _observer])


async def confirm_with_labels(
    window: Any,
    title: str,
    message: str,
    ok_label: str,
    cancel_label: str,
) -> bool:
    """Confirm dialog with task specific button labels.

    Toga only exposes fixed "OK"/"Cancel" buttons. The alert is presented as a
    sheet on the host window (the same primitive ``toga_cocoa`` uses) and the
    result arrives through the completion block, so nothing blocks the loop.
    """
    if not _ensure_appkit():
        return bool(await window.confirm_dialog(title, message))
    try:
        import asyncio

        from rubicon.objc import ObjCClass

        host = getattr(getattr(window, "_impl", None), "native", None)
        if host is None:
            return bool(await window.confirm_dialog(title, message))

        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        alert = ObjCClass("NSAlert").alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(message)
        alert.addButtonWithTitle_(ok_label)
        alert.addButtonWithTitle_(cancel_label)

        def _completion(response: NSInteger) -> None:
            if not future.done():
                future.set_result(int(response) == _NS_ALERT_FIRST_BUTTON)

        # AppKit copies the block and keeps it until the sheet is dismissed.
        alert.beginSheetModalForWindow_completionHandler_(host, _completion)
    except Exception:
        logger.debug("Labelled confirm failed; using the default dialog", exc_info=True)
        return bool(await window.confirm_dialog(title, message))
    return bool(await future)


def attach_right_click_menu(
    owner: Any,
    entries_at: Callable[[tuple[float, float]], Sequence[MenuEntry]],
    handler: Callable[[str], None],
) -> None:
    """Pop a context menu for right clicks the owner claims.

    Toga flattens its widgets into sibling ``TogaView``s, so an ``NSMenu`` set on
    a container never reaches the blank areas between the children. ``entries_at``
    receives the click location (window coordinates) and returns the items for
    it — an empty result means "not mine", and the event is passed through.
    """
    if not _ensure_appkit():
        return
    try:
        from rubicon.objc import ObjCClass
    except Exception:  # pragma: no cover - rubicon is a hard dependency
        logger.debug("Could not import rubicon for the right-click menu", exc_info=True)
        return

    def _handler(event: objc_id) -> objc_id:
        handled = False
        try:
            handled = _popup_menu_for_event(event, owner, entries_at, handler)
        except Exception:
            logger.exception("Right-click menu handler failed")
        if handled:
            return None
        return event.value if hasattr(event, "value") else event

    try:
        token = ObjCClass("NSEvent").addLocalMonitorForEventsMatchingMask_handler_(
            _RIGHT_CLICK_MASK, _handler
        )
    except Exception:
        logger.debug("Could not install the right-click monitor", exc_info=True)
        return
    if token is None:
        return
    _retain(owner, [token, _handler])


def _popup_menu_for_event(
    event: Any,
    owner: Any,
    entries_at: Callable[[tuple[float, float]], Sequence[MenuEntry]],
    handler: Callable[[str], None],
) -> bool:
    """Show the owner's menu for this right click; True when it was consumed."""
    if event is None:
        return False
    try:
        from rubicon.objc import ObjCClass, ObjCInstance

        native_event = event if isinstance(event, ObjCInstance) else ObjCInstance(event)
        native = native_of(owner)
        window = native.window if native is not None else None
    except Exception:
        return False
    if window is None or native_event.window != window:
        return False
    try:
        point = native_event.locationInWindow
        location = (float(point.x), float(point.y))
    except Exception:
        return False
    entries = tuple(entries_at(location))
    if not entries:
        return False
    menu = build_menu(entries, handler)
    if menu is None:
        return False
    try:
        ObjCClass("NSMenu").popUpContextMenu_withEvent_forView_(
            menu, native_event, native
        )
    except Exception:
        logger.debug("Could not pop up the context menu", exc_info=True)
        return False
    references: list[Any] = [menu]
    menu_target = getattr(menu, "_target", None)
    if menu_target is not None:
        references.append(menu_target)
    _retain(owner, references)
    return True


def update_tile_menu(
    widget: Any,
    entries: Sequence[MenuEntry],
    handler: Callable[[str], None],
) -> None:
    """Rebuild the context menu of a widget after its state changed.

    ``attach_tile_interactions`` bakes the enabled state of every item into the
    native ``NSMenu``; tiles that switch between running/idle therefore need a
    fresh menu instead of a rebuilt tile widget.
    """
    if not _ensure_appkit():
        return
    if not entries:
        # Clearing is how a widget drops back to "no context menu".
        for view in _native_views(widget):
            try:
                view.setMenu_(None)
            except Exception:
                continue
        widget._twinspace_menu_refs = []
        return
    menu = build_menu(entries, handler)
    if menu is None:
        return
    references: list[Any] = [menu]
    menu_target = getattr(menu, "_target", None)
    if menu_target is not None:
        references.append(menu_target)
    for view in _native_views(widget):
        try:
            view.setMenu_(menu)
        except Exception:
            continue
    # Replacing the list releases the previous menu (and its dispatcher).
    try:
        widget._twinspace_menu_refs = references
    except Exception:
        logger.debug("Could not retain Cocoa menu references", exc_info=True)


def _debounced(callback: Callable[[], None], window: float) -> Callable[[], None]:
    """Ignore repeats of ``callback`` within ``window`` seconds.

    Toga flattens the layout, so one physical click reaches a recognizer on every
    view of the tile. Without this a ⌘-click toggles the selection twice and
    cancels itself out (and every click is logged two or three times).
    """
    last = 0.0

    def wrapper() -> None:
        nonlocal last
        now = time.monotonic()
        if now - last < window:
            return
        last = now
        callback()

    return wrapper


def attach_tile_interactions(
    widget: Any,
    *,
    on_click: Callable[[], None] | None = None,
    on_double_click: Callable[[], None] | None = None,
    on_hover: Callable[[bool], None] | None = None,
    menu_entries: Sequence[MenuEntry] = (),
    menu_handler: Callable[[str], None] | None = None,
    tooltip: str = "",
    accessibility_label: str = "",
) -> None:
    """Attach single/double click, hover and context-menu behaviour to a Toga widget."""
    if not _ensure_appkit():
        return
    native = native_of(widget)
    if native is None:
        return

    references: list[Any] = []

    # Toga lays every widget out as a sibling inside one container view, so a
    # tile's icon and labels are NOT subviews of the tile's own view. Anything
    # installed only on ``native`` therefore never sees a click that lands on the
    # icon or the caption — which is exactly where users click. Install the
    # interactions on every view of the tile instead.
    native_views = list(_native_views(widget))

    if on_click is not None:
        click_callback = _debounced(on_click, _SINGLE_CLICK_DEBOUNCE)
        for view in native_views:
            try:
                from rubicon.objc import SEL, ObjCClass

                gesture_class = ObjCClass("NSClickGestureRecognizer")
                target = _SingleClickTarget.alloc().init()
                target._callback = click_callback
                recognizer = gesture_class.alloc().initWithTarget_action_(
                    target, SEL("handleSingleClick:")
                )
                recognizer.setNumberOfClicksRequired_(1)
                view.addGestureRecognizer_(recognizer)
                references.extend([target, recognizer])
            except Exception:
                logger.debug("Could not attach click recognizer", exc_info=True)

    if on_double_click is not None:
        last_fired = 0.0

        def _fire_double_click() -> None:
            nonlocal last_fired
            now = time.monotonic()
            if now - last_fired < _DOUBLE_CLICK_DEBOUNCE:
                return
            last_fired = now
            on_double_click()

        for view in native_views:
            try:
                from rubicon.objc import SEL, ObjCClass

                gesture_class = ObjCClass("NSClickGestureRecognizer")
                target = _DoubleClickTarget.alloc().init()
                target._callback = _fire_double_click
                recognizer = gesture_class.alloc().initWithTarget_action_(
                    target, SEL("handleDoubleClick:")
                )
                recognizer.setNumberOfClicksRequired_(2)
                view.addGestureRecognizer_(recognizer)
                references.extend([target, recognizer])
            except Exception:
                logger.debug("Could not attach double-click recognizer", exc_info=True)

    if on_hover is not None:
        hovered_views = {"count": 0}

        def _enter() -> None:
            hovered_views["count"] += 1
            if hovered_views["count"] == 1:
                on_hover(True)

        def _exit() -> None:
            hovered_views["count"] = max(0, hovered_views["count"] - 1)
            if hovered_views["count"] == 0:
                on_hover(False)

        for view in native_views:
            try:
                from rubicon.objc import ObjCClass
                from rubicon.objc.types import NSMakeRect

                area_class = ObjCClass("NSTrackingArea")
                target = _HoverTarget.alloc().init()
                target._on_enter = _enter
                target._on_exit = _exit
                area = area_class.alloc().initWithRect_options_owner_userInfo_(
                    NSMakeRect(0.0, 0.0, 1.0, 1.0),
                    _NSTrackingMouseEnteredAndExited
                    | _NSTrackingActiveInActiveApp
                    | _NSTrackingInVisibleRect,
                    target,
                    None,
                )
                view.addTrackingArea_(area)
                references.extend([target, area])
            except Exception:
                logger.debug("Could not attach hover tracking area", exc_info=True)

    if menu_entries and menu_handler is not None:
        menu = build_menu(menu_entries, menu_handler)
        if menu is not None:
            attached = False
            for view in native_views:
                try:
                    view.setMenu_(menu)
                    attached = True
                except Exception:
                    continue
            if attached:
                references.append(menu)
                # NSMenuItem.target is a weak reference; keep the dispatcher
                # alive alongside the widget even if the menu is released.
                menu_target = getattr(menu, "_target", None)
                if menu_target is not None:
                    references.append(menu_target)

    if tooltip:
        for view in native_views:
            try:
                view.setToolTip_(tooltip)
            except Exception:
                continue

    label = accessibility_label or tooltip
    if label:
        try:
            native.setAccessibilityElement_(True)
            native.setAccessibilityRole_("AXButton")
            native.setAccessibilityLabel_(label)
        except Exception:
            logger.debug("Could not set accessibility metadata", exc_info=True)
        for view in native_views[1:]:
            try:
                # Keep VoiceOver focused on the tile itself, not its decorations.
                view.setAccessibilityElement_(False)
            except Exception:
                continue

    # NSGestureRecognizer/NSTrackingArea hold their target weakly; keep them alive
    # for as long as the Toga widget exists.
    try:
        widget._twinspace_cocoa_refs = references
    except Exception:
        logger.debug("Could not retain Cocoa interaction references", exc_info=True)


def _retain(widget: Any, references: Sequence[Any]) -> None:
    """Append native objects to the widget so AppKit does not release them."""
    try:
        existing = list(getattr(widget, "_twinspace_cocoa_refs", []) or [])
        existing.extend(references)
        widget._twinspace_cocoa_refs = existing
    except Exception:
        logger.debug("Could not retain Cocoa references", exc_info=True)


def current_modifier_flags() -> int:
    """Modifier keys held right now (0 when AppKit is unavailable)."""
    if not _ensure_appkit():
        return 0
    try:
        from rubicon.objc import ObjCClass

        return int(ObjCClass("NSEvent").modifierFlags)
    except Exception:
        return 0


def selection_intent() -> str:
    """Translate the current modifiers into a multi-selection intent."""
    flags = current_modifier_flags()
    if flags & _MODIFIER_COMMAND:
        return SELECT_TOGGLE
    if flags & _MODIFIER_SHIFT:
        return SELECT_EXTEND
    return SELECT_REPLACE


def window_frame(widget: Any) -> tuple[float, float, float, float] | None:
    """Return a widget's native frame in window base coordinates.

    Drag hit-testing works on window coordinates because the pointer leaves the
    widget it started on; ``(x, y, width, height)`` uses AppKit's bottom-left
    origin, which ``convertRect:toView:nil`` already accounts for.
    """
    native = native_of(widget)
    if native is None:
        return None
    try:
        rect = native.convertRect_toView_(native.bounds, None)
        origin = rect.origin
        size = rect.size
        return (float(origin.x), float(origin.y), float(size.width), float(size.height))
    except Exception:
        logger.debug("Could not resolve native frame", exc_info=True)
        return None


def configure_label_single_line(label: Any) -> None:
    """Keep a label on one line, truncating in the middle when it overflows.

    The tile caption is sized for one line; without this a longer app name (for
    example "WorkBuddy AI") wraps and the second line is clipped, hiding exactly
    the suffix that tells the builds apart.
    """
    native = native_of(label)
    if native is None:
        return
    try:
        cell = native.cell
        cell.setWraps_(False)
        cell.setLineBreakMode_(5)  # NSLineBreakByTruncatingMiddle
        native.setAttributedStringValue_(native.attributedStringValue)
    except Exception:
        logger.debug("Could not configure the label line mode", exc_info=True)


def frame_contains(frame: tuple[float, float, float, float], location: tuple[float, float]) -> bool:
    """True when ``location`` (window coordinates) falls inside ``frame``."""
    x, y, width, height = frame
    px, py = location
    return x <= px <= x + width and y <= py <= y + height


def frame_intersects(
    frame: tuple[float, float, float, float],
    other: tuple[float, float, float, float],
) -> bool:
    """True when two window-space rectangles overlap (rubber-band hit testing)."""
    x, y, width, height = frame
    ox, oy, owidth, oheight = other
    return x < ox + owidth and ox < x + width and y < oy + oheight and oy < y + height


def hit_test_view(owner: Any, location: tuple[float, float]) -> Any | None:
    """Native view under a window-space point (used to skip buttons)."""
    native = native_of(owner)
    if native is None:
        return None
    try:
        window = native.window
        content = window.contentView if window is not None else None
    except Exception:
        return None
    if content is None:
        return None
    try:
        from rubicon.objc.types import NSMakePoint

        point = content.convertPoint_fromView_(
            NSMakePoint(location[0], location[1]), None
        )
        return content.hitTest_(point)
    except Exception:
        logger.debug("Could not hit-test the window content", exc_info=True)
        return None


def is_control_view(view: Any) -> bool:
    """True when a native view is (or lives inside) a button-like ``NSControl``."""
    try:
        from rubicon.objc import ObjCClass

        control_class = ObjCClass("NSControl")
    except Exception:  # pragma: no cover - macOS only in practice
        return False
    current = view
    for _ in range(8):
        if current is None:
            return False
        try:
            if current.isKindOfClass_(control_class):
                return True
            current = current.superview
        except Exception:
            return False
    return False


def mouse_is_down() -> bool:
    """True while the primary mouse button is held.

    Rubber-band autoscroll uses this as a safety net: a native menu opened from
    a button runs its own tracking loop and can swallow the mouse-up, which
    leaves the drag monitor believing the sweep is still in progress. Returns
    ``True`` when the state cannot be read, so callers keep their old behaviour.
    """
    try:
        from rubicon.objc import ObjCClass

        event_class = ObjCClass("NSEvent")
        pressed = event_class.pressedMouseButtons
        mask = pressed() if callable(pressed) else pressed
        return bool(int(mask) & 0x1)
    except Exception:  # pragma: no cover - macOS only in practice
        return True


def drag_rect(
    start: tuple[float, float],
    end: tuple[float, float],
) -> tuple[float, float, float, float]:
    """Normalise the two corners of a drag into an ``(x, y, width, height)`` rect."""
    x1, y1 = start
    x2, y2 = end
    return (min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))


_MarqueeView = None


def _marquee_view_class() -> Any:
    """Create (once) the transparent overlay used to draw the rubber band."""
    global _MarqueeView
    if _MarqueeView is not None:
        return _MarqueeView
    try:
        from rubicon.objc import ObjCClass

        base = ObjCClass("NSView")

        class MarqueeView(base):
            @objc_method
            def hitTest_(self, point: NSPoint) -> objc_id:
                # Returning nil keeps the overlay transparent to the mouse, so
                # clicks, drags and right-clicks still reach the tiles beneath.
                return None

        _MarqueeView = MarqueeView
    except Exception:  # pragma: no cover - macOS only in practice
        logger.debug("Could not create the marquee overlay view", exc_info=True)
    return _MarqueeView


class Marquee:
    """Rubber-band rectangle drawn above the window content during a drag."""

    def __init__(self, owner: Any) -> None:
        self._view = None
        self._content = None
        if not _ensure_appkit():
            return
        view_class = _marquee_view_class()
        if view_class is None:
            return
        try:
            native = native_of(owner)
            window = native.window if native is not None else None
            content = window.contentView if window is not None else None
            if content is None:
                return
            from rubicon.objc import ObjCClass

            view = view_class.alloc().initWithFrame_(content.bounds)
            view.setWantsLayer_(True)
            color_class = ObjCClass("NSColor")
            fill = color_class.colorWithSRGBRed_green_blue_alpha_(0.0, 0.48, 1.0, 0.14)
            stroke = color_class.colorWithSRGBRed_green_blue_alpha_(0.0, 0.48, 1.0, 0.70)
            layer = view.layer
            layer.setBackgroundColor_(fill.CGColor)
            layer.setBorderColor_(stroke.CGColor)
            layer.setBorderWidth_(1.0)
            layer.setCornerRadius_(2.0)
            content.addSubview_(view)
            self._view = view
            self._content = content
        except Exception:  # pragma: no cover - macOS only in practice
            logger.debug("Could not create the marquee overlay", exc_info=True)

    @property
    def active(self) -> bool:
        return self._view is not None

    def set_rect(self, rect: tuple[float, float, float, float]) -> None:
        """Move the rubber band; ``rect`` is in window base coordinates."""
        if self._view is None or self._content is None:
            return
        try:
            from rubicon.objc.types import NSMakeRect

            converted = self._content.convertRect_fromView_(
                NSMakeRect(rect[0], rect[1], rect[2], rect[3]), None
            )
            self._view.setFrame_(converted)
        except Exception:
            logger.debug("Could not move the marquee overlay", exc_info=True)

    def close(self) -> None:
        view = self._view
        self._view = None
        self._content = None
        if view is None:
            return
        try:
            view.removeFromSuperview()
        except Exception:
            logger.debug("Could not remove the marquee overlay", exc_info=True)


def set_tooltip(widget: Any, text: str) -> None:
    """Update the native tooltip of a widget and all of its views."""
    if not text:
        return
    for view in _native_views(widget):
        try:
            view.setToolTip_(text)
        except Exception:
            continue


def attach_drag_monitor(
    owner: Any,
    on_drag: Callable[[int, tuple[float, float]], None],
) -> None:
    """Report left-button press / drag / release in window coordinates.

    A local event monitor is used instead of a gesture recognizer on purpose:
    an ``NSPanGestureRecognizer`` competes with the click / double-click
    recognizers the tiles already install (a small movement would cancel the
    double-click that opens an app). The monitor only observes events and always
    hands them back untouched, so existing interactions keep working.
    """
    if not _ensure_appkit():
        return
    try:
        from rubicon.objc import ObjCClass
    except Exception:  # pragma: no cover - rubicon is a hard dependency
        logger.debug("Could not import rubicon for the drag monitor", exc_info=True)
        return

    def _handler(event: objc_id) -> objc_id:
        try:
            _dispatch_drag_event(event, owner, on_drag)
        except Exception:
            logger.exception("Drag selection handler failed")
        # AppKit expects the very same NSEvent back so the event keeps flowing.
        # rubicon rejects ObjC wrappers as block return values, but a plain
        # integer address is converted back to the pointer by ctypes.
        return event.value if hasattr(event, "value") else event

    try:
        event_class = ObjCClass("NSEvent")
        token = event_class.addLocalMonitorForEventsMatchingMask_handler_(
            _DRAG_EVENT_MASK, _handler
        )
    except Exception:
        logger.debug("Could not install the drag monitor", exc_info=True)
        return
    if token is None:
        return
    _retain(owner, [token, _handler])


def _dispatch_drag_event(
    event: Any,
    owner: Any,
    on_drag: Callable[[int, tuple[float, float]], None],
) -> None:
    """Forward one left-button event to ``on_drag`` when it targets our view."""
    if event is None:
        return
    # Block callbacks receive a raw pointer, not an object wrapper.
    try:
        from rubicon.objc import ObjCInstance

        native_event = event if isinstance(event, ObjCInstance) else ObjCInstance(event)
    except Exception:
        logger.debug("Could not wrap the drag event", exc_info=True)
        return
    try:
        state = _DRAG_EVENT_STATES.get(int(native_event.type))
    except Exception:
        return
    if state is None:
        return
    native = native_of(owner)
    if native is None:
        return
    try:
        window = native.window
    except Exception:
        return
    # ``window is None`` means the view is not mounted (the page was switched).
    if window is None or native_event.window != window:
        return
    try:
        location = native_event.locationInWindow
        on_drag(state, (float(location.x), float(location.y)))
    except Exception:
        logger.debug("Could not dispatch a drag event", exc_info=True)


def attach_key_monitor(owner: Any, on_key: Callable[[str, int], bool]) -> None:
    """Observe key presses while ``owner``'s window is key.

    ``on_key`` receives the typed character (modifiers stripped) plus the
    ``NSEventModifierFlags`` and returns ``True`` when it consumed the key, in
    which case the event is swallowed (otherwise AppKit beeps).
    """
    if not _ensure_appkit():
        return
    try:
        from rubicon.objc import ObjCClass
    except Exception:  # pragma: no cover - rubicon is a hard dependency
        logger.debug("Could not import rubicon for the key monitor", exc_info=True)
        return

    def _handler(event: objc_id) -> objc_id:
        handled = False
        try:
            handled = _dispatch_key_event(event, owner, on_key)
        except Exception:
            logger.exception("Key handler failed")
        if handled:
            return None
        return event.value if hasattr(event, "value") else event

    try:
        token = ObjCClass("NSEvent").addLocalMonitorForEventsMatchingMask_handler_(
            _KEY_EVENT_MASK, _handler
        )
    except Exception:
        logger.debug("Could not install the key monitor", exc_info=True)
        return
    if token is None:
        return
    _retain(owner, [token, _handler])


def _dispatch_key_event(
    event: Any,
    owner: Any,
    on_key: Callable[[str, int], bool],
) -> bool:
    """Forward one key press to ``on_key`` when it belongs to our window."""
    if event is None:
        return False
    try:
        from rubicon.objc import ObjCInstance

        native_event = event if isinstance(event, ObjCInstance) else ObjCInstance(event)
        native = native_of(owner)
        window = native.window if native is not None else None
    except Exception:
        return False
    if window is None or native_event.window != window:
        return False
    try:
        # Never steal keystrokes from a focused text field / text view.
        responder = window.firstResponder
        if responder is not None and responder.isKindOfClass_(_text_view_class()):
            return False
        key = str(native_event.charactersIgnoringModifiers or "")
        flags = int(native_event.modifierFlags)
    except Exception:
        return False
    if not key:
        return False
    return bool(on_key(key, flags))


def _text_view_class() -> Any:
    """``NSTextView``, used to leave typed input alone."""
    from rubicon.objc import ObjCClass

    return ObjCClass("NSTextView")


def scroll_content(widget: Any, amount: float) -> bool:
    """Scroll the scroll view of ``widget`` by ``amount`` content points.

    Positive values scroll towards the end of the content. Returns True when the
    offset actually moved (the view may already be at an edge).
    """
    native = native_of(widget)
    if native is None:
        return False
    try:
        from rubicon.objc.types import NSMakePoint

        clip = native.contentView
        document = clip.documentView
        if document is None:
            return False
        bounds = clip.bounds
        origin = bounds.origin
        flipped = bool(document.isFlipped)
        max_offset = max(0.0, float(document.frame.size.height) - float(bounds.size.height))
        offset = float(origin.y) if flipped else max_offset - float(origin.y)
        new_offset = min(max(offset + float(amount), 0.0), max_offset)
        if abs(new_offset - offset) < 0.5:
            return False
        target_y = new_offset if flipped else max_offset - new_offset
        clip.scrollToPoint_(NSMakePoint(float(origin.x), target_y))
        native.reflectScrolledClipView_(clip)
        return True
    except Exception:
        logger.debug("Could not scroll the content view", exc_info=True)
        return False


def attach_click_selection(
    widget: Any,
    on_click: Callable[[str], None],
) -> None:
    """Single-click recognizer that reports the current selection intent."""
    if not _ensure_appkit():
        return
    references: list[Any] = []
    click_callback = _debounced(
        lambda: on_click(selection_intent()), _SINGLE_CLICK_DEBOUNCE
    )
    for view in list(_native_views(widget)):
        try:
            from rubicon.objc import SEL, ObjCClass

            gesture_class = ObjCClass("NSClickGestureRecognizer")
            target = _SingleClickTarget.alloc().init()
            target._callback = click_callback
            recognizer = gesture_class.alloc().initWithTarget_action_(
                target, SEL("handleSingleClick:")
            )
            recognizer.setNumberOfClicksRequired_(1)
            view.addGestureRecognizer_(recognizer)
            references.extend([target, recognizer])
        except Exception:
            logger.debug("Could not attach click recognizer", exc_info=True)
    _retain(widget, references)
