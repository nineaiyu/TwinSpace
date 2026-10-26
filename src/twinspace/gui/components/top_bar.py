"""Unified Top Header Bar component matching modern macOS layout specifications."""

from typing import Callable, List, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.i18n import t
from twinspace.gui import cocoa_events
from twinspace.gui.patch_cocoa import configure_cocoa_sidebar_active
from twinspace.gui.theme import Theme


class TopHeaderBar(toga.Box):
    """Top header panel with a large section title and a compact pinned action toolbar."""

    def __init__(
        self,
        title: Optional[str] = None,
        action_label: Optional[str] = None,
        on_action: Optional[Callable[[toga.Button], None]] = None,
        action_symbol: Optional[str] = None,
        secondary_action_label: Optional[str] = None,
        on_secondary_action: Optional[Callable[[toga.Button], None]] = None,
        secondary_action_symbol: Optional[str] = None,
        refresh_symbol: Optional[str] = None,
        search_placeholder: Optional[str] = None,
        on_search: Optional[Callable[[str], None]] = None,
        filter_items: Optional[List[str]] = None,
        on_filter_change: Optional[Callable[[str], None]] = None,
        sort_items: Optional[List[str]] = None,
        on_sort_change: Optional[Callable[[str], None]] = None,
        view_modes: Optional[List[str]] = None,
        on_view_change: Optional[Callable[[str], None]] = None,
        on_refresh: Optional[Callable[[toga.Button], None]] = None,
    ):
        super().__init__(style=Pack(direction=COLUMN, margin=(26, 28, 14, 28)))
        self.on_search_cb = on_search
        self.on_view_change_cb = on_view_change
        self.on_filter_cb = on_filter_change
        self.on_sort_cb = on_sort_change
        self.current_view_mode: str = "list"

        if action_label is None and on_action:
            action_label = t("btn_new_clone")
        if search_placeholder is None:
            search_placeholder = t("topbar_search_placeholder")

        # 1. Big Feature Area Section Title Row (大标题 + 紧随其后的新建/操作主按钮)
        title_row = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=12))
        if title:
            self.label_title = toga.Label(
                title,
                style=Pack(font_weight="bold", font_size=24, margin_right=12, color=Theme.TEXT_PRIMARY),
            )
            title_row.add(self.label_title)
        else:
            self.label_title = None

        if on_action and action_label:
            self.btn_action = toga.Button(
                action_label,
                on_press=on_action,
                style=Pack(font_weight="bold", font_size=13, height=30),
            )
            if action_symbol:
                cocoa_events.configure_button_icon(self.btn_action, action_symbol)
            cocoa_events.style_primary_button(self.btn_action)
            title_row.add(self.btn_action)
        else:
            self.btn_action = None

        if on_secondary_action and secondary_action_label:
            self.btn_secondary = toga.Button(
                secondary_action_label,
                on_press=on_secondary_action,
                style=Pack(font_size=13, height=30, margin_left=8),
            )
            if secondary_action_symbol:
                cocoa_events.configure_button_icon(
                    self.btn_secondary, secondary_action_symbol
                )
            title_row.add(self.btn_secondary)
        else:
            self.btn_secondary = None

        self.add(title_row)

        # Hairline separating the large title from the action toolbar.
        self.divider = toga.Box(
            style=Pack(
                height=1,
                margin=(0, 0, 12, 0),
                background_color=Theme.BORDER_SUBTLE,
            )
        )
        self.add(self.divider)

        # 2. Pinned Compact Action Toolbar Row
        toolbar_row = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=2))

        # (a) Search input (only add when on_search callback is provided)
        if on_search:
            self.input_search = toga.TextInput(
                placeholder=search_placeholder,
                on_change=self._handle_search,
                style=Pack(
                    width=240,
                    height=28,
                    margin_right=10,
                    background_color=Theme.BG_CARD,
                    color=Theme.TEXT_PRIMARY,
                ),
            )
            toolbar_row.add(self.input_search)
        else:
            self.input_search = None

        # (b) Filter dropdown
        if filter_items and on_filter_change:
            self.select_filter = toga.Selection(
                items=filter_items,
                on_change=self._handle_filter,
                style=Pack(width=150, margin_right=10),
            )
            toolbar_row.add(self.select_filter)

        # (c) Sort dropdown
        if sort_items and on_sort_change:
            self.select_sort = toga.Selection(
                items=sort_items,
                on_change=self._handle_sort,
                style=Pack(width=160, margin_right=10),
            )
            toolbar_row.add(self.select_sort)

        # (d) View mode toggle: a segmented-style pair of buttons, always visible
        if on_view_change:
            view_items = view_modes or [t("topbar_view_list"), t("topbar_view_grid")]
            self._view_labels = {"list": view_items[0], "grid": view_items[-1]}
            self.btn_view_list = toga.Button(
                self._view_labels["list"],
                on_press=lambda w: self._set_view_mode("list"),
                style=Pack(height=28, font_size=12.5, margin_right=4),
            )
            self.btn_view_grid = toga.Button(
                self._view_labels["grid"],
                on_press=lambda w: self._set_view_mode("grid"),
                style=Pack(height=28, font_size=12.5, margin_right=10),
            )
            toolbar_row.add(self.btn_view_list)
            toolbar_row.add(self.btn_view_grid)
            self._refresh_view_toggle()
        else:
            self.btn_view_list = None
            self.btn_view_grid = None

        # (e) Flexible horizontal spacer
        toolbar_row.add(toga.Box(style=Pack(flex=1)))

        # (f) Refresh Button at far right
        if on_refresh:
            self.btn_refresh = toga.Button(t("topbar_btn_refresh"), on_press=on_refresh, style=Pack(height=28, font_size=13))
            if refresh_symbol:
                cocoa_events.configure_button_icon(self.btn_refresh, refresh_symbol)
            toolbar_row.add(self.btn_refresh)

        if len(toolbar_row.children) > 1 or (len(toolbar_row.children) == 1 and on_refresh):
            self.add(toolbar_row)

    def _handle_search(self, widget: toga.TextInput):
        if self.on_search_cb:
            self.on_search_cb(widget.value.strip())

    def _handle_filter(self, widget: toga.Selection):
        if self.on_filter_cb and widget.value is not None:
            self.on_filter_cb(str(widget.value))

    def _handle_sort(self, widget: toga.Selection):
        if self.on_sort_cb and widget.value is not None:
            self.on_sort_cb(str(widget.value))

    def _set_view_mode(self, mode: str):
        self.current_view_mode = mode
        self._refresh_view_toggle()
        if self.on_view_change_cb:
            self.on_view_change_cb(mode)

    def _refresh_view_toggle(self):
        """Highlight the active side of the segmented view toggle."""
        for mode, btn in (("list", self.btn_view_list), ("grid", self.btn_view_grid)):
            if btn is None:
                continue
            active = mode == self.current_view_mode
            btn.style.font_weight = "bold" if active else "normal"
            try:
                native_btn = getattr(getattr(btn, "_impl", None), "native", None)
                configure_cocoa_sidebar_active(native_btn, active)
            except Exception:
                pass

    def set_view_mode(self, mode: str):
        """Programmatically switch view mode."""
        self._set_view_mode(mode)

    def update_title(self, new_title: str):
        if self.label_title:
            self.label_title.text = new_title

    def update_filter_items(self, items: list[str]) -> None:
        """Refresh the filter dropdown, preserving the current selection when possible."""
        select = getattr(self, "select_filter", None)
        if select is None:
            return
        current = select.value
        select.items = list(items)
        if current in items:
            select.value = current

