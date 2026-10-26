"""Guard tests for the native tile interactions.

Toga flattens every widget into a single container view, so a tile's icon and
caption are siblings rather than subviews. Clicks therefore never reach a
recognizer that is installed on the tile's own view only — these tests pin the
"interactions live on every view of the tile" contract.

They also pin the Objective-C selector *spelling*: ``SEL("invoke_")`` is not the
same selector as ``invoke:``, so a menu item wired with the former appears in the
menu but silently does nothing when clicked.
"""

from toga_cocoa.libs import NSImage, NSSize

from twinspace.gui import cocoa_events
from twinspace.gui.components.app_tile import AppTile
from twinspace.gui.patch_cocoa import (
    TABLE_ICON_SIZE,
    TABLE_ROW_HEIGHT,
    patch_cocoa_widgets,
)


def _make_tile(**kwargs) -> AppTile:
    defaults = {
        "label": "ZCode",
        "clone_name": "ZCode-phone1",
        "running": False,
        "tooltip": "ZCode · ZCode-phone1",
    }
    defaults.update(kwargs)
    return AppTile(**defaults)


def _tile_views(tile: AppTile) -> list:
    return [
        tile._impl.native,
        tile.pill._impl.native,
        tile.icon_view._impl.native,
        tile.name_label._impl.native,
        tile.status_label._impl.native,
    ]


def _recognizers(view, clicks: int) -> list:
    return [
        recognizer
        for recognizer in (view.gestureRecognizers or ())
        if recognizer.numberOfClicksRequired == clicks
    ]


def test_tile_views_handle_single_and_double_click(toga_app):
    tile = _make_tile(on_open=lambda: None, on_select=lambda t: None)

    for view in _tile_views(tile):
        assert len(_recognizers(view, 1)) >= 1, view
        assert len(_recognizers(view, 2)) >= 1, view


def test_recognizer_selectors_are_real_objc_selectors(toga_app):
    tile = _make_tile(on_open=lambda: None, on_select=lambda t: None)

    for view in _tile_views(tile):
        single = _recognizers(view, 1)[0]
        double = _recognizers(view, 2)[0]
        assert single.action.name == b"handleSingleClick:"
        assert double.action.name == b"handleDoubleClick:"
        assert single.target.respondsToSelector_(single.action) is True
        assert double.target.respondsToSelector_(double.action) is True


def test_context_menu_is_installed_on_every_tile_view(toga_app):
    tile = _make_tile(on_reveal=lambda: None)

    for view in _tile_views(tile):
        assert view.menu is not None, view


def test_menu_items_use_a_dispatchable_selector(toga_app):
    called: list[str] = []
    menu = cocoa_events.build_menu(
        [cocoa_events.MenuEntry("reveal", "Reveal")],
        called.append,
    )

    item = menu.itemAtIndex_(0)
    assert item.action.name == b"invoke:"
    assert item.target.respondsToSelector_(item.action) is True


def test_hover_tracking_area_is_installed_on_every_tile_view(toga_app):
    tile = _make_tile(on_open=lambda: None)

    for view in _tile_views(tile):
        assert len(list(view.trackingAreas or ())) >= 1, view


def test_double_click_is_debounced_across_tile_views(toga_app):
    calls: list[str] = []
    tile = _make_tile(on_open=lambda: calls.append("open"))

    targets = []
    for view in _tile_views(tile):
        targets.extend(recognizer.target for recognizer in _recognizers(view, 2))
    assert len(targets) == len(_tile_views(tile))

    for target in targets:
        target.handleDoubleClick_(None)

    assert calls == ["open"]


def test_single_click_selects_exactly_once_per_view_set(toga_app):
    selected: list[str] = []
    tile = _make_tile(on_select=lambda t: selected.append(t.clone_name))

    for view in _tile_views(tile):
        for recognizer in _recognizers(view, 1):
            recognizer.target.handleSingleClick_(None)

    assert selected and set(selected) == {"ZCode-phone1"}


def test_pill_height_keeps_vertical_padding_symmetric(toga_app):
    from twinspace.gui.components import app_tile as module

    assert module.PILL_HEIGHT == (
        2 * module.PILL_PADDING
        + module.ICON_SIZE
        + module.PILL_GAP
        + module.CAPTION_HEIGHT
    )

    tile = _make_tile()
    assert tile.icon_view.style.margin_top == module.PILL_PADDING
    assert tile.name_label.style.margin_top == module.PILL_GAP
    # The pill must stay inside the tile with room for the status row.
    assert module.TILE_HEIGHT >= module.PILL_HEIGHT + module.PILL_PADDING + 14


def test_pill_and_status_row_are_horizontally_centred(toga_app):
    from twinspace.gui.components import app_tile as module

    tile = _make_tile()
    offset = (module.TILE_WIDTH - module.PILL_WIDTH) // 2

    # Toga lays children out from the tile's left edge, so the centring is done
    # with an explicit margin instead of align_items.
    assert tile.pill.style.margin_left == offset
    assert tile.status_label.style.margin_left == offset
    assert tile.status_label.style.text_align == "center"
    assert tile.name_label.style.text_align == "center"


def test_selected_tile_keeps_its_pill_on_hover(toga_app):
    tile = _make_tile(on_open=lambda: None)

    tile.set_selected(True)
    assert tile.selected is True
    tile._handle_hover(False)
    assert tile.selected is True

    tile.set_selected(False)
    assert tile.selected is False


def test_table_cells_use_the_enlarged_icon_metrics(toga_app):
    patch_cocoa_widgets()
    from toga_cocoa.widgets import table as table_module
    from toga_cocoa.widgets.internal import cells

    # The table module imported TogaIconView by name, so both bindings must move.
    assert table_module.TogaIconView is cells.TogaIconView
    assert cells.TogaIconView.__name__ == "TwinSpaceIconView"

    cell = cells.TogaIconView.alloc().init()
    cell.setText("ZCode-phone1")
    cell.setImage_(NSImage.alloc().initWithSize_(NSSize(TABLE_ICON_SIZE, TABLE_ICON_SIZE)))

    assert cell.iv_width_constraint.constant == TABLE_ICON_SIZE
    assert cell.tv_left_constraint.constant > 0
    assert TABLE_ICON_SIZE > 16
    assert TABLE_ROW_HEIGHT >= TABLE_ICON_SIZE + 8
