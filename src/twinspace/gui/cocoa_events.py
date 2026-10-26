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
    from rubicon.objc import NSObject, objc_method

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
        for view in native_views:
            try:
                from rubicon.objc import SEL, ObjCClass

                gesture_class = ObjCClass("NSClickGestureRecognizer")
                target = _SingleClickTarget.alloc().init()
                target._callback = on_click
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
