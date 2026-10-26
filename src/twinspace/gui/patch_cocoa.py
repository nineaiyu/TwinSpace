"""macOS Cocoa native widget patches and tweaks for BeeWare Toga."""

import sys
import threading
from collections import deque
from typing import Any

from twinspace.gui.theme import Theme

_is_patched = False
_dark_mode_cache: bool | None = None

# Flattened table metrics shared with the clone list: 44pt rows leave room for a
# 22pt app icon, which reads far better than Toga's hardcoded 16pt cell icon.
TABLE_ROW_HEIGHT = 44.0
TABLE_ICON_SIZE = 22.0
TABLE_ICON_TEXT_GAP = 8.0

_MAIN_THREAD = threading.main_thread()

# Toga removes Auto Layout constraints (and purges window toolbars) from Python
# finalizers. When such an object is collected by the cyclic garbage collector
# on a worker thread, AppKit is touched off the main thread, which raises an
# ObjC exception and aborts the process. Queue that work instead and replay it
# from the main thread via drain_pending_cocoa_work().
_pending_cocoa_work: deque[tuple[str, Any]] = deque()
_pending_cocoa_lock = threading.Lock()

_CONSTRAINT_CLEANUP = "constraints"
_TOOLBAR_CLEANUP = "toolbar"

_original_remove_constraints: Any = None
_original_main_window_del: Any = None


def _queue_cocoa_work(kind: str, target: Any) -> None:
    """Record Cocoa teardown that must be replayed on the main thread."""
    with _pending_cocoa_lock:
        _pending_cocoa_work.append((kind, target))


def pending_cocoa_work_count() -> int:
    """Number of Cocoa cleanup callbacks waiting for the main thread."""
    with _pending_cocoa_lock:
        return len(_pending_cocoa_work)


def drain_pending_cocoa_work() -> int:
    """Replay queued Cocoa cleanup on the main thread.

    Returns the number of callbacks processed. Calls from a background thread
    are ignored so that AppKit is never touched off the main thread.
    """
    if threading.current_thread() is not _MAIN_THREAD:
        return 0
    if _original_remove_constraints is None and _original_main_window_del is None:
        return 0

    processed = 0
    while True:
        with _pending_cocoa_lock:
            if not _pending_cocoa_work:
                break
            kind, target = _pending_cocoa_work.popleft()
        try:
            if kind == _CONSTRAINT_CLEANUP and _original_remove_constraints is not None:
                _original_remove_constraints(target)
            elif kind == _TOOLBAR_CLEANUP and _original_main_window_del is not None:
                _original_main_window_del(target)
        except Exception:
            # Teardown during garbage collection must never raise.
            pass
        processed += 1
    return processed


def _install_main_thread_finalizer_patch() -> None:
    """Keep Toga's Cocoa finalizers on the main thread.

    ``toga_cocoa.constraints.Constraints.__del__`` calls ``removeConstraint`` and
    ``toga_cocoa.window.MainWindow.__del__`` purges native toolbar items. Both
    crash with ``_AssertAutoLayoutOnAllowedThreadsOnly`` when triggered by a GC
    pass on a worker thread, so the AppKit part is deferred to the main thread.
    """
    global _original_remove_constraints, _original_main_window_del

    try:
        from toga_cocoa.constraints import Constraints
    except Exception:
        return

    if not getattr(Constraints._remove_constraints, "_twinspace_main_thread_safe", False):
        original_remove = Constraints._remove_constraints

        def _patched_remove_constraints(self: Any) -> Any:
            if threading.current_thread() is _MAIN_THREAD:
                return original_remove(self)
            _queue_cocoa_work(_CONSTRAINT_CLEANUP, self)
            return None

        _patched_remove_constraints._twinspace_main_thread_safe = True  # type: ignore[attr-defined]
        _original_remove_constraints = original_remove
        Constraints._remove_constraints = _patched_remove_constraints

    try:
        from toga_cocoa.window import MainWindow
    except Exception:
        return

    try:
        original_del = MainWindow.__del__
    except AttributeError:
        return

    if not getattr(original_del, "_twinspace_main_thread_safe", False):
        def _patched_main_window_del(self: Any) -> Any:
            if threading.current_thread() is _MAIN_THREAD:
                return original_del(self)
            _queue_cocoa_work(_TOOLBAR_CLEANUP, self)
            return None

        _patched_main_window_del._twinspace_main_thread_safe = True  # type: ignore[attr-defined]
        _original_main_window_del = original_del
        MainWindow.__del__ = _patched_main_window_del


def _detect_dark_mode() -> bool:
    if sys.platform != "darwin":
        return False
    try:
        import subprocess

        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return "dark" in result.stdout.strip().lower()
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        from toga_cocoa.libs.appkit import NSApplication
        ns_app = NSApplication.sharedApplication
        appearance = getattr(ns_app, "effectiveAppearance", None)
        if appearance is None:
            return False
        name = str(getattr(appearance, "name", "") or "")
        return "Dark" in name
    except Exception:
        return False


def is_dark_mode() -> bool:
    """Detect whether macOS system appearance is currently Dark Mode.

    The result is cached because this helper is called from per-widget styling
    paths. NSApp.effectiveAppearance is not reliable during very early startup,
    so the system-wide preference is preferred and Cocoa is the fallback.
    """
    global _dark_mode_cache
    if _dark_mode_cache is None:
        _dark_mode_cache = _detect_dark_mode()
    return _dark_mode_cache


def refresh_dark_mode_cache() -> bool:
    """Re-detect the system appearance and update the cached value.

    Returns the freshly detected mode so callers can compare against the
    previously applied palette and rebuild the UI when it changed.
    """
    global _dark_mode_cache
    _dark_mode_cache = _detect_dark_mode()
    return _dark_mode_cache


def configure_cocoa_danger_button(widget: Any) -> None:
    """Tint a button's label red for destructive actions (NSButton contentTintColor)."""
    if sys.platform != "darwin":
        return
    native_btn = getattr(getattr(widget, "_impl", None), "native", None)
    if native_btn is None:
        return
    try:
        from rubicon.objc import ObjCClass

        ns_color = ObjCClass("NSColor").systemRedColor()
        if native_btn.respondsToSelector("setContentTintColor:"):
            native_btn.setContentTintColor_(ns_color)
    except Exception:
        pass


def set_window_min_size(window: Any, min_width: int, min_height: int) -> None:
    """Enforce a minimum window size so toolbar rows and tables never collapse."""
    if sys.platform != "darwin":
        return
    native_win = getattr(getattr(window, "_impl", None), "native", None)
    if native_win is None:
        return
    try:
        from rubicon.objc import CGSize

        native_win.setContentMinSize_(CGSize(min_width, min_height))
    except Exception:
        pass


def apply_cocoa_appearance(is_dark: bool) -> None:
    """Force native AppKit controls to match the Toga color palette.

    Toga paints explicit background colors, but NSScrollView/NSTableView/NSTextField
    otherwise follow the process appearance. Forcing NSApp.appearance avoids the
    light Toga surface + dark native control mixture seen in early startup.
    """
    if sys.platform != "darwin":
        return
    try:
        import toga_cocoa.libs.appkit  # noqa: F401  (loads AppKit into the ObjC runtime)
        from rubicon.objc import ObjCClass

        appearance_name = (
            "NSAppearanceNameDarkAqua" if is_dark else "NSAppearanceNameAqua"
        )
        ns_appearance = ObjCClass("NSAppearance").appearanceNamed_(appearance_name)
        if ns_appearance is not None:
            ObjCClass("NSApplication").sharedApplication.setAppearance_(ns_appearance)
    except Exception:
        pass


def configure_cocoa_text_field(native_text_field: Any, font_size: float = 13.5) -> None:
    """Configure an NSTextField for smooth single-line text editing, horizontal scrolling, and clear typography.

    By default, Toga Cocoa NSTextFieldCell has wraps=True and isScrollable=False.
    When long text (e.g. file paths) exceeds the text field width, Cocoa wraps the text
    vertically into line 2 (which is hidden/clipped in a single-line frame) instead of
    scrolling horizontally, causing cursor jumps and unexpected text displacement.

    This helper configures:
    - cell.setScrollable_(True)
    - cell.setWraps_(False)
    - cell.setLineBreakMode_(2)  # NSLineBreakByClipping
    - native.setUsesSingleLineMode_(True)
    - native.setFont_(NSFont.systemFontOfSize_(font_size))
    """
    if sys.platform != "darwin" or native_text_field is None:
        return
    try:
        cell = getattr(native_text_field, "cell", None)
        if cell is not None:
            if hasattr(cell, "setScrollable_"):
                cell.setScrollable_(True)
            if hasattr(cell, "setWraps_"):
                cell.setWraps_(False)
            if hasattr(cell, "setLineBreakMode_"):
                cell.setLineBreakMode_(2)  # NSLineBreakByClipping
        if hasattr(native_text_field, "setUsesSingleLineMode_"):
            native_text_field.setUsesSingleLineMode_(True)
        if hasattr(native_text_field, "setFont_"):
            from toga_cocoa.libs import NSFont
            native_text_field.setFont_(NSFont.systemFontOfSize_(font_size))
    except Exception:
        pass


def configure_cocoa_table(native_table: Any, row_height: float = 34.0) -> None:
    """Configure an NSTableView with comfortable row height (34px) and crisp 12.5px header fonts."""
    if sys.platform != "darwin" or native_table is None:
        return
    try:
        if hasattr(native_table, "setRowHeight_"):
            native_table.setRowHeight_(row_height)
        if hasattr(native_table, "setUsesAlternatingRowBackgroundColors_"):
            native_table.setUsesAlternatingRowBackgroundColors_(False)
        from toga_cocoa.libs import NSFont
        if hasattr(native_table, "tableColumns"):
            for col in native_table.tableColumns:
                header_cell = getattr(col, "headerCell", None)
                if header_cell and hasattr(header_cell, "setFont_"):
                    header_cell.setFont_(NSFont.boldSystemFontOfSize_(12.5))
    except Exception:
        pass


def configure_cocoa_wrapping_label(native_label: Any, selectable: bool = True) -> None:
    """Configure an NSTextField for multiline text wrapping, selectable text, word breaking, and natural bounds calculation."""
    if sys.platform != "darwin" or native_label is None:
        return
    try:
        cell = getattr(native_label, "cell", None)
        if cell is not None:
            if hasattr(cell, "setWraps_"):
                cell.setWraps_(True)
            if hasattr(cell, "setLineBreakMode_"):
                cell.setLineBreakMode_(0)  # NSLineBreakByWordWrapping
            if hasattr(cell, "setScrollable_"):
                cell.setScrollable_(False)
            if hasattr(cell, "setSelectable_"):
                cell.setSelectable_(selectable)
        if hasattr(native_label, "setMaximumNumberOfLines_"):
            native_label.setMaximumNumberOfLines_(0)
    except Exception:
        pass


def configure_cocoa_single_line_label(native_label: Any, selectable: bool = False) -> None:
    """Configure an NSTextField to be strictly single-line with tail ellipsis truncation."""
    if sys.platform != "darwin" or native_label is None:
        return
    try:
        cell = getattr(native_label, "cell", None)
        if cell is not None:
            if hasattr(cell, "setWraps_"):
                cell.setWraps_(False)
            if hasattr(cell, "setLineBreakMode_"):
                cell.setLineBreakMode_(4)  # NSLineBreakByTruncatingTail
            if hasattr(cell, "setScrollable_"):
                cell.setScrollable_(False)
            if hasattr(cell, "setSelectable_"):
                cell.setSelectable_(selectable)
        if hasattr(native_label, "setMaximumNumberOfLines_"):
            native_label.setMaximumNumberOfLines_(1)
        if hasattr(native_label, "setUsesSingleLineMode_"):
            native_label.setUsesSingleLineMode_(True)
    except Exception:
        pass


def configure_cocoa_multiline_text_view(native_scroll_view: Any, font_size: float = 12.5, readonly: bool = False) -> None:
    """Configure an NSTextView inside an NSScrollView for crisp typography, selection, and readonly support."""
    if sys.platform != "darwin" or native_scroll_view is None:
        return
    try:
        tv = getattr(native_scroll_view, "documentView", None)
        if tv is not None:
            if hasattr(tv, "setUsesAdaptiveColorMappingForDarkAppearance_"):
                tv.setUsesAdaptiveColorMappingForDarkAppearance_(False)
            elif hasattr(tv, "usesAdaptiveColorMappingForDarkAppearance"):
                tv.usesAdaptiveColorMappingForDarkAppearance = False
            if hasattr(tv, "setSelectable_"):
                tv.setSelectable_(True)
            if hasattr(tv, "setEditable_"):
                tv.setEditable_(not readonly)
            from toga_cocoa.libs import NSFont
            if hasattr(tv, "setFont_"):
                try:
                    tv.setFont_(NSFont.monospacedSystemFontOfSize_weight_(font_size, 0.0))
                except Exception:
                    try:
                        tv.setFont_(NSFont.userFixedPitchFontOfSize_(font_size))
                    except Exception:
                        pass
    except Exception:
        pass


def configure_cocoa_card(native_view: Any, corner_radius: float = 10.0, border_width: float = 0.5) -> None:
    """Configure an NSView container to display as an elevated macOS card with rounded corners and hairline border."""
    if sys.platform != "darwin" or native_view is None:
        return
    try:
        from toga_cocoa.libs.appkit import NSColor
        if hasattr(native_view, "setWantsLayer_"):
            native_view.setWantsLayer_(True)
        elif hasattr(native_view, "wantsLayer"):
            native_view.wantsLayer = True
        layer = getattr(native_view, "layer", None)
        if layer is not None:
            if hasattr(layer, "setCornerRadius_"):
                layer.setCornerRadius_(corner_radius)
            elif hasattr(layer, "cornerRadius"):
                layer.cornerRadius = corner_radius
            if hasattr(layer, "setMasksToBounds_"):
                layer.setMasksToBounds_(True)
            elif hasattr(layer, "masksToBounds"):
                layer.masksToBounds = True
            if hasattr(layer, "setBorderWidth_"):
                layer.setBorderWidth_(border_width)
            elif hasattr(layer, "borderWidth"):
                layer.borderWidth = border_width

            if is_dark_mode():
                border_color = NSColor.colorWithRed_green_blue_alpha_(0.25, 0.25, 0.28, 1.0)
            else:
                border_color = NSColor.colorWithRed_green_blue_alpha_(0.88, 0.88, 0.90, 1.0)
            if hasattr(border_color, "CGColor"):
                cg_color = border_color.CGColor
                if hasattr(layer, "setBorderColor_"):
                    layer.setBorderColor_(cg_color)
                elif hasattr(layer, "borderColor"):
                    layer.borderColor = cg_color

            # Subtle drop shadow for visual depth (macOS card style)
            if hasattr(native_view, "setShadow_"):
                try:
                    from rubicon.objc import ObjCClass
                    NSShadow = ObjCClass("NSShadow")
                    shadow = NSShadow.alloc().init()
                    shadow.shadowOffset = (0, -2)
                    shadow.shadowBlurRadius = 10.0
                    if hasattr(NSColor, "colorWithRed_green_blue_alpha_"):
                        shadow_alpha = 0.38 if is_dark_mode() else 0.07
                        shadow.shadowColor = NSColor.colorWithRed_green_blue_alpha_(0.0, 0.0, 0.0, shadow_alpha)
                    native_view.setShadow_(shadow)
                except Exception:
                    pass
    except Exception:
        pass


def _ns_color_from_hex(value: str) -> Any | None:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        return None
    try:
        red = int(text[0:2], 16) / 255.0
        green = int(text[2:4], 16) / 255.0
        blue = int(text[4:6], 16) / 255.0
    except ValueError:
        return None
    try:
        from rubicon.objc import ObjCClass

        return ObjCClass("NSColor").colorWithSRGBRed_green_blue_alpha_(
            red, green, blue, 1.0
        )
    except Exception:
        return None


def configure_cocoa_sidebar_active(native_btn: Any, active: bool) -> None:
    """Paint a rounded accent-tinted pill behind the active navigation item."""
    if sys.platform != "darwin" or native_btn is None:
        return
    try:
        from toga_cocoa.libs.appkit import NSColor

        if hasattr(native_btn, "setWantsLayer_"):
            native_btn.setWantsLayer_(True)
        layer = getattr(native_btn, "layer", None)
        if layer is None:
            return
        if active:
            bg = _ns_color_from_hex(Theme.BG_SIDEBAR_ACTIVE)
            if bg is not None and hasattr(bg, "CGColor"):
                layer.setBackgroundColor_(bg.CGColor)
            if hasattr(layer, "setCornerRadius_"):
                layer.setCornerRadius_(8.0)
            if hasattr(native_btn, "setContentTintColor_"):
                native_btn.setContentTintColor_(NSColor.controlAccentColor)
        else:
            if hasattr(layer, "setBackgroundColor_"):
                layer.setBackgroundColor_(None)
            if hasattr(layer, "setCornerRadius_"):
                layer.setCornerRadius_(0.0)
            if hasattr(native_btn, "setContentTintColor_"):
                native_btn.setContentTintColor_(None)
    except Exception:
        pass


def configure_cocoa_window_chrome(window: Any) -> None:
    """Adopt the modern full-height window chrome used by current macOS apps.

    Extends the content view under the titlebar, hides the title text and keeps
    the traffic lights, matching Finder / Notes / Arc style layouts.
    """
    if sys.platform != "darwin" or window is None:
        return
    native = getattr(getattr(window, "_impl", None), "native", None)
    if native is None:
        return
    try:
        style_mask = native.styleMask
        full_size_content = 1 << 15  # NSWindowStyleMaskFullSizeContentView
        native.setStyleMask_(style_mask | full_size_content)
        if hasattr(native, "setTitlebarAppearsTransparent_"):
            native.setTitlebarAppearsTransparent_(True)
        if hasattr(native, "setTitleVisibility_"):
            native.setTitleVisibility_(1)  # NSWindowTitleHidden
        if hasattr(native, "setMovableByWindowBackground_"):
            native.setMovableByWindowBackground_(True)
    except Exception:
        pass


def apply_cocoa_sidebar_material(sidebar_widget: Any) -> None:
    """Place a native vibrant material behind the sidebar content."""
    if sys.platform != "darwin" or sidebar_widget is None:
        return
    native = getattr(getattr(sidebar_widget, "_impl", None), "native", None)
    if native is None:
        return
    try:
        from rubicon.objc import ObjCClass

        effect_class = ObjCClass("NSVisualEffectView")
        effect = effect_class.alloc().initWithFrame_(native.bounds)
        effect.setMaterial_(3)  # NSVisualEffectMaterialSidebar
        effect.setBlendingMode_(0)  # NSVisualEffectBlendingModeBehindWindow
        effect.setState_(1)  # NSVisualEffectStateActive
        effect.setAutoresizingMask_(2 | 16)  # WidthSizable | HeightSizable
        effect.setFrame_(native.bounds)
        subviews = native.subviews
        if subviews and len(subviews) > 0:
            native.addSubview_positioned_relativeTo_(effect, -1, subviews[0])
        else:
            native.addSubview_(effect)
        sidebar_widget._twinspace_sidebar_effect = effect
    except Exception:
        pass


def update_cocoa_sidebar_material(sidebar_widget: Any) -> None:
    """Resize the vibrant sidebar backdrop after layout or window resizing."""
    if sys.platform != "darwin" or sidebar_widget is None:
        return
    effect = getattr(sidebar_widget, "_twinspace_sidebar_effect", None)
    native = getattr(getattr(sidebar_widget, "_impl", None), "native", None)
    if effect is None or native is None:
        return
    try:
        effect.setFrame_(native.bounds)
    except Exception:
        pass


def configure_cocoa_window_movable(window: Any) -> None:
    """Enable window drag from any background area (movableByWindowBackground) on the NSWindow.

    This allows users to drag the window by clicking and dragging in the top bar or content
    area — matching standard macOS single-pane utility app behavior.
    """
    if sys.platform != "darwin" or window is None:
        return
    try:
        native = getattr(getattr(window, "_impl", None), "native", None)
        if native is None:
            native = getattr(window, "native", None)
        if native is not None and hasattr(native, "setMovableByWindowBackground_"):
            native.setMovableByWindowBackground_(True)
    except Exception:
        pass


if sys.platform == "darwin":
    try:
        from rubicon.objc import objc_method
        from toga_cocoa.libs import NSImage, NSIndexSet
        from toga_cocoa.widgets.table import TogaTable

        class TwinSpaceTable(TogaTable):
            @objc_method
            def tableView_didClickTableColumn_(self, tableView, tableColumn) -> None:
                try:
                    table_columns = list(self.tableColumns)
                    col_index = -1
                    for idx, col in enumerate(table_columns):
                        if col == tableColumn or str(col.identifier) == str(tableColumn.identifier):
                            col_index = idx
                            break
                    if col_index == -1:
                        return

                    toga_col = getattr(tableColumn, "toga_column", None)
                    if toga_col is None and hasattr(self.interface, "columns") and col_index < len(self.interface.columns):
                        toga_col = self.interface.columns[col_index]

                    clicked_id = str(tableColumn.identifier)
                    curr_id = getattr(self, "_sort_col_id", None)
                    if curr_id == clicked_id:
                        ascending = not getattr(self, "_sort_ascending", True)
                    else:
                        ascending = True

                    self._sort_col_id = clicked_id
                    self._sort_ascending = ascending

                    # Update macOS sort indicator chevrons
                    indicator_name = "NSAscendingSortIndicator" if ascending else "NSDescendingSortIndicator"
                    indicator_img = NSImage.imageNamed_(indicator_name)
                    for col in table_columns:
                        if str(col.identifier) == clicked_id:
                            self.setIndicatorImage_inTableColumn_(indicator_img, col)
                        else:
                            self.setIndicatorImage_inTableColumn_(None, col)

                    if hasattr(self, "setHighlightedTableColumn_"):
                        self.setHighlightedTableColumn_(tableColumn)

                    # If interface has custom handler, invoke it
                    if hasattr(self.interface, "on_header_sort") and callable(self.interface.on_header_sort):
                        self.interface.on_header_sort(col_index, toga_col, ascending)
                        return

                    # Default safe auto-sorting
                    if hasattr(self.interface, "data") and self.interface.data is not None:
                        col_accessor = getattr(toga_col, "accessor", None) or str(col_index)

                        def _safe_sort_key(row):
                            val = None
                            if hasattr(row, col_accessor):
                                val = getattr(row, col_accessor)
                            elif hasattr(toga_col, "value"):
                                try:
                                    val = toga_col.value(row)
                                except Exception:
                                    pass
                            elif isinstance(row, (tuple, list)) and col_index < len(row):
                                val = row[col_index]
                            elif isinstance(row, dict) and col_accessor in row:
                                val = row[col_accessor]

                            if val is None:
                                return (2, "")
                            if isinstance(val, (int, float)):
                                return (0, val)
                            if isinstance(val, bool):
                                return (0, int(val))
                            return (1, str(val).lower())

                        # Preserve selection if any
                        selected_item = getattr(self.interface, "selection", None)

                        if hasattr(self.interface.data, "_data") and isinstance(self.interface.data._data, list):
                            self.interface.data._data.sort(key=_safe_sort_key, reverse=not ascending)
                            self.reloadData()
                            if selected_item is not None and selected_item in self.interface.data._data:
                                new_idx = self.interface.data._data.index(selected_item)
                                self.selectRowIndexes_byExtendingSelection_(NSIndexSet.indexSetWithIndex(new_idx), False)
                        elif isinstance(self.interface.data, list):
                            self.interface.data.sort(key=_safe_sort_key, reverse=not ascending)
                            self.reloadData()
                        else:
                            try:
                                rows = list(self.interface.data)
                                rows.sort(key=_safe_sort_key, reverse=not ascending)
                                self.interface.data = rows
                            except Exception:
                                pass
                except Exception:
                    pass
    except Exception:
        TwinSpaceTable = None
else:
    TwinSpaceTable = None


def patch_cocoa_widgets() -> None:
    """Apply monkeypatches to toga_cocoa widget implementations on macOS.

    Ensures:
    - All single-line TextInput widgets support horizontal scrolling, clipping mode, and readable 13.5px fonts.
    - All multiline TextInput widgets use their explicit theme colors instead of Cocoa's adaptive inversion.
    - All Switch (checkbox) widgets have comfortable 13.5px label fonts.
    - All Selection (dropdown) widgets have comfortable 12.0px option fonts and support set_font.
    - All Table widgets have comfortable row height (34px), crisp 12.5px headers, readable 13.0px cell fonts, and native header sorting.
    - Cocoa finalizers (Auto Layout constraint removal, toolbar purge) are replayed on the main thread.
    """
    global _is_patched
    if sys.platform != "darwin":
        return

    _install_main_thread_finalizer_patch()

    if _is_patched:
        return

    try:
        import toga_cocoa.libs.appkit
        from toga_cocoa.libs import NSFont
        from toga_cocoa.widgets.internal.cells import TogaIconView
        from toga_cocoa.widgets.multilinetextinput import (
            MultilineTextInput as CocoaMultilineTextInput,
        )
        from toga_cocoa.widgets.selection import Selection as CocoaSelection
        from toga_cocoa.widgets.switch import Switch as CocoaSwitch
        from toga_cocoa.widgets.table import Table as CocoaTable
        from toga_cocoa.widgets.textinput import TextInput as CocoaTextInput

        # 1. TextInput Patch
        _orig_create = CocoaTextInput.create

        def _patched_create(self):
            _orig_create(self)
            configure_cocoa_text_field(self.native, font_size=13.5)

        CocoaTextInput.create = _patched_create

        # 2. MultilineTextInput Patch
        # Cocoa remaps explicit colors to their opposite appearance when this is
        # enabled, turning dark log surfaces into light ones in Dark Mode.
        _orig_multiline_create = CocoaMultilineTextInput.create

        def _patched_multiline_create(self):
            _orig_multiline_create(self)
            try:
                self.native_text.usesAdaptiveColorMappingForDarkAppearance = False
            except Exception:
                pass

        CocoaMultilineTextInput.create = _patched_multiline_create

        # 3. Switch (Checkbox) Patch
        _orig_switch_create = CocoaSwitch.create

        def _patched_switch_create(self):
            _orig_switch_create(self)
            try:
                if hasattr(self, "native") and self.native is not None:
                    self.native.setFont_(NSFont.systemFontOfSize_(13.5))
            except Exception:
                pass

        CocoaSwitch.create = _patched_switch_create

        # 4. Selection (Dropdown) Patch
        _orig_selection_create = CocoaSelection.create

        def _patched_selection_create(self):
            _orig_selection_create(self)
            try:
                if hasattr(self, "native") and self.native is not None:
                    self.native.setFont_(NSFont.systemFontOfSize_(12.0))
            except Exception:
                pass

        def _patched_selection_set_font(self, font):
            try:
                if font and hasattr(font, "_impl") and hasattr(font._impl, "native"):
                    self.native.font = font._impl.native
            except Exception:
                pass

        CocoaSelection.create = _patched_selection_create
        CocoaSelection.set_font = _patched_selection_set_font

        # 5. Table & IconView Patch
        if TwinSpaceTable is not None:
            try:
                from toga_cocoa.libs import (
                    SEL,
                    NSScrollView,
                    NSTableViewColumnAutoresizingStyle,
                )
                from toga_cocoa.libs.appkit import NSColor

                def _patched_table_create(self):
                    self.native = NSScrollView.alloc().init()
                    self.native.hasVerticalScroller = True
                    self.native.hasHorizontalScroller = False
                    self.native.autohidesScrollers = True
                    self.native.borderType = 0  # NSNoBorder
                    self.native.drawsBackground = False

                    self.native_table = TwinSpaceTable.alloc().init()
                    self.native_table.interface = self.interface
                    self.native_table.impl = self
                    self.native_table.columnAutoresizingStyle = (
                        NSTableViewColumnAutoresizingStyle.Uniform
                    )
                    self.native_table.usesAlternatingRowBackgroundColors = False
                    self.native_table.allowsMultipleSelection = self.interface.multiple_select
                    self.native_table.allowsColumnReordering = False
                    try:
                        self.native_table.backgroundColor = NSColor.clearColor
                        if hasattr(self.native_table, "setStyle_"):
                            self.native_table.setStyle_(1)  # NSTableViewStyleFullWidth
                        if hasattr(self.native_table, "setGridStyleMask_"):
                            self.native_table.setGridStyleMask_(0)
                        # Match the table surface to the surrounding card instead
                        # of the default clip view control background (pure black).
                        card_color = _ns_color_from_hex(Theme.BG_CARD)
                        if card_color is not None:
                            self.native.drawsBackground = True
                            if hasattr(self.native, "setBackgroundColor_"):
                                self.native.setBackgroundColor_(card_color)
                            clip_view = self.native.contentView
                            if hasattr(clip_view, "setBackgroundColor_"):
                                clip_view.setBackgroundColor_(card_color)
                            if hasattr(clip_view, "setDrawsBackground_"):
                                clip_view.setDrawsBackground_(True)
                    except Exception:
                        pass

                    self.columns = []
                    if not self.interface._show_headings:
                        self.native_table.setHeaderView(None)
                    for index, toga_column in enumerate(self.interface._columns):
                        self._insert_column(index, toga_column)

                    self.native_table.delegate = self.native_table
                    self.native_table.dataSource = self.native_table
                    self.native_table.target = self.native_table
                    self.native_table.doubleAction = SEL("onDoubleClick:")

                    self.native.documentView = self.native_table
                    self.add_constraints()

                    configure_cocoa_table(
                        self.native_table, row_height=TABLE_ROW_HEIGHT
                    )

                CocoaTable.create = _patched_table_create
            except Exception:
                pass

        _orig_icon_setup = getattr(TogaIconView, "setup", None)
        if _orig_icon_setup is not None:

            def _patched_icon_setup(self):
                _orig_icon_setup(self)
                try:
                    if hasattr(self, "textField") and self.textField is not None:
                        self.textField.setFont_(NSFont.systemFontOfSize_(13.0))
                except Exception:
                    pass

            TogaIconView.setup = _patched_icon_setup

        # 5b. Table icon cells: Toga hardcodes a 16pt icon width (cells.py
        # setImage_ sets iv_width_constraint.constant = 16), which looks cramped
        # next to taller rows. Swap in a subclass with our metrics.
        try:
            from rubicon.objc import objc_method
            from toga_cocoa.widgets import table as _cocoa_table_module
            from toga_cocoa.widgets.internal import cells as _cocoa_cells

            class TwinSpaceIconView(_cocoa_cells.TogaIconView):
                @objc_method
                def setImage_(self, image):
                    if not self.imageView:  # pragma: no cover - defensive
                        self.setup()
                    if image:
                        self.imageView.image = image
                        self.iv_width_constraint.constant = TABLE_ICON_SIZE
                        self.tv_left_constraint.constant = TABLE_ICON_TEXT_GAP
                        if hasattr(self.imageView, "setImageScaling_"):
                            # NSImageScaleProportionallyUpOrDown
                            self.imageView.setImageScaling_(3)
                    else:
                        self.imageView.image = None
                        self.iv_width_constraint.constant = 0
                        self.tv_left_constraint.constant = 0

            _cocoa_cells.TogaIconView = TwinSpaceIconView
            _cocoa_table_module.TogaIconView = TwinSpaceIconView
        except Exception:
            pass

        # 6. Box / Card Surface Patch
        try:
            from toga_cocoa.widgets.box import Box as CocoaBox
            _orig_box_set_bg = CocoaBox.set_background_color

            def _patched_box_set_bg(self, color):
                _orig_box_set_bg(self, color)
                if color is None:
                    return
                try:
                    from toga.colors import Color

                    parsed = Color.parse(color)
                    card = Color.parse(Theme.BG_CARD)
                    is_card = (parsed.r, parsed.g, parsed.b) == (
                        card.r,
                        card.g,
                        card.b,
                    )
                except Exception:
                    is_card = False
                if is_card:
                    configure_cocoa_card(
                        self.native, corner_radius=14.0, border_width=0.5
                    )

            CocoaBox.set_background_color = _patched_box_set_bg
        except Exception:
            pass

        # 7. AppDelegate reopen patch (clicking Dock icon restores window)
        try:
            import toga_cocoa.libs.appkit  # noqa: F401  (loads AppKit) 
            from rubicon.objc import objc_method
            from toga_cocoa.app import AppDelegate

            @objc_method
            def _applicationShouldHandleReopen_hasVisibleWindows_(self, sender, flag: bool) -> bool:
                if hasattr(self, "interface") and hasattr(self.interface, "show_main_window"):
                    self.interface.show_main_window()
                return True

            AppDelegate.applicationShouldHandleReopen_hasVisibleWindows_ = _applicationShouldHandleReopen_hasVisibleWindows_
        except Exception:
            pass

        # 8. About Dialog Patch (ensure version and copyright information are always populated)
        try:
            from toga_cocoa.app import App as CocoaApp
            from toga_cocoa.libs import (
                NSAboutPanelOptionApplicationIcon,
                NSAboutPanelOptionApplicationName,
                NSAboutPanelOptionApplicationVersion,
                NSAboutPanelOptionVersion,
                NSMutableDictionary,
            )

            def _patched_show_about_dialog(self):
                from twinspace import __version__
                options = NSMutableDictionary.alloc().init()

                if (
                    self.interface.icon
                    and hasattr(self.interface.icon, "_impl")
                    and getattr(self.interface.icon._impl, "native", None)
                ):
                    options[NSAboutPanelOptionApplicationIcon] = self.interface.icon._impl.native
                options[NSAboutPanelOptionApplicationName] = self.interface.formal_name or "TwinSpace"

                app_ver = self.interface.version or __version__
                options[NSAboutPanelOptionApplicationVersion] = app_ver
                options[NSAboutPanelOptionVersion] = "1"

                author = self.interface.author or "TwinSpace Contributors"
                options["Copyright"] = f"Copyright © {author}"

                self.native.orderFrontStandardAboutPanelWithOptions(options)

            CocoaApp.show_about_dialog = _patched_show_about_dialog
        except Exception:
            pass

        _is_patched = True
    except (ImportError, AttributeError, Exception):
        pass


def configure_cocoa_window(window: Any, floating: bool = False, parent_window: Any = None) -> None:
    """Ensure Cocoa NSWindow is brought forward and remains key/active during transitions.

    - floating=False (default): normal window level (NSNormalWindowLevel=0). Does not float above other apps.
    - floating=True: sets window level to NSFloatingWindowLevel (3) for utility/overlay panels.
    - parent_window: optionally attaches as child window to parent window.
    - makeKeyAndOrderFront: brings window to foreground and gives it focus.
    """
    if sys.platform != "darwin" or window is None:
        return
    try:
        native = getattr(getattr(window, "_impl", None), "native", None)
        if native is not None:
            if hasattr(native, "setLevel_"):
                # 0 = NSNormalWindowLevel, 3 = NSFloatingWindowLevel
                native.setLevel_(3 if floating else 0)
            if hasattr(native, "makeKeyAndOrderFront_"):
                native.makeKeyAndOrderFront_(None)

            if parent_window is not None:
                parent_native = getattr(getattr(parent_window, "_impl", None), "native", None)
                if parent_native is not None and hasattr(parent_native, "addChildWindow_ordered_"):
                    # NSWindowAbove = 1
                    parent_native.addChildWindow_ordered_(native, 1)
    except Exception:
        pass

