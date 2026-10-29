"""Icon-and-label app tile used by the environment cards."""

from __future__ import annotations

import inspect
from typing import Any, Callable, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN

from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.timestamps import format_last_opened
from twinspace.gui import cocoa_events
from twinspace.gui.patch_cocoa import configure_cocoa_card
from twinspace.gui.theme import Theme

logger = get_logger("gui.app_tile")

TILE_WIDTH = 144
TILE_HEIGHT = 149
ICON_SIZE = 56
TILE_GAP = 12
# "Today 5:30" caption sits between the name and the running-status row.
LAST_OPENED_HEIGHT = 13
# "⬆ 1.2.3" badge row: appears when the source app moved past the clone version.
UPDATE_BADGE_HEIGHT = 14

# Hover/selection pill: hugs the icon and caption instead of filling the tile.
# The height is derived from its content so the vertical padding stays symmetric:
# 8pt pad + 56pt icon + 4pt gap + 19pt caption + 8pt pad.
PILL_WIDTH = 136
PILL_PADDING = 8
PILL_GAP = 4
CAPTION_HEIGHT = 19
PILL_HEIGHT = 2 * PILL_PADDING + ICON_SIZE + PILL_GAP + CAPTION_HEIGHT
PILL_CORNER_RADIUS = 12.0

TILE_COLUMNS_MIN = 2
TILE_COLUMNS_MAX = 6
CARD_HORIZONTAL_PADDING = 32.0


def compute_tile_columns(available_width: float) -> int:
    """Return how many app tiles fit in one row of an environment card."""
    usable = max(0.0, float(available_width) - CARD_HORIZONTAL_PADDING)
    columns = int((usable + TILE_GAP) // (TILE_WIDTH + TILE_GAP))
    return max(TILE_COLUMNS_MIN, min(TILE_COLUMNS_MAX, columns))


def _accepts_selection_intent(callback: Any) -> bool:
    """True when a select callback takes ``(tile, intent)`` rather than ``(tile)``."""
    if callback is None:
        return False
    try:
        parameters = list(inspect.signature(callback).parameters.values())
    except (TypeError, ValueError):  # pragma: no cover - builtins / C callables
        return False
    positional = [
        parameter
        for parameter in parameters
        if parameter.kind
        in (parameter.POSITIONAL_ONLY, parameter.POSITIONAL_OR_KEYWORD)
    ]
    return len(positional) >= 2 or any(
        parameter.kind is parameter.VAR_POSITIONAL for parameter in parameters
    )


class AppTile(toga.Box):
    """A Finder-style app tile: icon on top, name below, native interactions."""

    def __init__(
        self,
        *,
        label: str,
        clone_name: str,
        icon: Any | None = None,
        running: bool = False,
        last_opened: str = "",
        tooltip: str = "",
        update_available: bool = False,
        current_version: str = "",
        latest_version: str = "",
        on_open: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
        on_edit: Optional[Callable[[], None]] = None,
        on_reveal: Optional[Callable[[], None]] = None,
        on_update: Optional[Callable[[], None]] = None,
        on_select: Optional[Callable[["AppTile", str], None]] = None,
        on_batch_action: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(
            style=Pack(
                direction=COLUMN,
                width=TILE_WIDTH,
                height=TILE_HEIGHT,
                align_items=CENTER,
                margin=(2, TILE_GAP // 2, 6, TILE_GAP // 2),
            )
        )
        self.label_text = label
        self.clone_name = clone_name
        self.running = running
        self.tooltip = tooltip or clone_name
        self.selected = False
        self.update_available = bool(update_available)
        self.current_version = current_version
        self.latest_version = latest_version
        self._base_tooltip = self.tooltip
        self._on_select = on_select
        self._select_with_intent = _accepts_selection_intent(on_select)
        self._on_batch_action = on_batch_action
        self._batch_entries: tuple[cocoa_events.MenuEntry, ...] | None = None
        self._callbacks = {
            "open": on_open,
            "close": on_close,
            "edit": on_edit,
            "reveal": on_reveal,
            "update": on_update,
        }

        # The pill is the hover/selection surface. It is deliberately smaller
        # than the tile so the rounded highlight hugs the icon + caption instead
        # of filling the whole tile frame (which reads as an off-centre box).
        self.pill = toga.Box(
            style=Pack(
                direction=COLUMN,
                align_items=CENTER,
                width=PILL_WIDTH,
                height=PILL_HEIGHT,
                # Toga lays the tile's children out from the tile's left edge, so
                # centre the pill by hand instead of relying on align_items.
                margin_top=6,
                margin_left=(TILE_WIDTH - PILL_WIDTH) // 2,
            )
        )
        self.icon_view = self._build_icon(label, icon)
        self.pill.add(self.icon_view)

        self.name_label = toga.Label(
            label,
            style=Pack(
                font_size=12.0,
                font_weight="bold",
                color=Theme.TEXT_PRIMARY,
                text_align=CENTER,
                width=PILL_WIDTH - 4,
                margin_top=PILL_GAP,
            ),
        )
        # One line only: an overflowing name truncates in the middle instead of
        # wrapping into a clipped second line (which hid the "AI" suffix).
        cocoa_events.configure_label_single_line(self.name_label)
        self.pill.add(self.name_label)
        self.add(self.pill)

        # Caption directly under the app name: "今天 5:30 打开" / "2 days ago".
        # The height is fixed so tiles without a timestamp stay aligned.
        self.last_opened_label = toga.Label(
            format_last_opened(last_opened, compact=True),
            style=Pack(
                font_size=9.5,
                color=Theme.TEXT_TERTIARY,
                text_align=CENTER,
                width=PILL_WIDTH,
                margin_top=2,
                margin_left=(TILE_WIDTH - PILL_WIDTH) // 2,
                height=LAST_OPENED_HEIGHT,
            ),
        )
        self.add(self.last_opened_label)

        # "New version" badge: hidden (empty, fixed height) unless the source app
        # moved past the version baked into this clone.
        self.update_label = toga.Label(
            "",
            style=Pack(
                font_size=9.5,
                font_weight="bold",
                color=Theme.BTN_WARNING,
                text_align=CENTER,
                width=PILL_WIDTH,
                margin_top=1,
                margin_left=(TILE_WIDTH - PILL_WIDTH) // 2,
                height=UPDATE_BADGE_HEIGHT,
            ),
        )
        self.add(self.update_label)
        self.set_update_info(
            update_available, current_version, latest_version
        )

        # The status row spans the pill width and centres its text so the dot +
        # label stays on the same axis as the icon and caption.
        self.status_label = toga.Label(
            ("● " + t("environment_running")) if running else "",
            style=Pack(
                font_size=10.5,
                color=Theme.BTN_SUCCESS if running else Theme.TEXT_TERTIARY,
                text_align=CENTER,
                width=PILL_WIDTH,
                margin_top=1,
                margin_left=(TILE_WIDTH - PILL_WIDTH) // 2,
                height=14,
            ),
        )
        self.add(self.status_label)

        cocoa_events.attach_tile_interactions(
            self,
            on_click=self._handle_click,
            on_double_click=self._handle_double_click,
            on_hover=self._handle_hover,
            menu_entries=self._menu_entries(),
            menu_handler=self._handle_menu,
            tooltip=self.tooltip,
            accessibility_label=self.tooltip,
        )

    def _build_icon(self, label: str, icon: Any | None) -> Any:
        if icon is not None:
            return toga.ImageView(
                icon,
                style=Pack(
                    width=ICON_SIZE,
                    height=ICON_SIZE,
                    margin_top=PILL_PADDING,
                ),
            )

        fallback = toga.Box(
            style=Pack(
                direction=COLUMN,
                width=ICON_SIZE,
                height=ICON_SIZE,
                align_items=CENTER,
                margin_top=PILL_PADDING,
                background_color=Theme.BADGE_HARD_BG,
            )
        )
        initial = (label.strip()[:1] or "?").upper()
        fallback.add(
            toga.Label(
                initial,
                style=Pack(
                    font_size=24,
                    font_weight="bold",
                    color=Theme.BADGE_HARD_TEXT,
                    text_align=CENTER,
                    margin_top=11,
                ),
            )
        )
        try:
            configure_cocoa_card(fallback._impl.native, corner_radius=14.0, border_width=0.0)
        except Exception:
            pass
        return fallback

    def _handle_click(self) -> None:
        logger.info("Tile click: clone=%s", self.clone_name)
        if self._on_select is None:
            return
        if self._select_with_intent:
            self._on_select(self, cocoa_events.selection_intent())
        else:
            self._on_select(self)

    def set_update_info(
        self,
        update_available: bool,
        current_version: str = "",
        latest_version: str = "",
    ) -> None:
        """Show or hide the "new version available" badge without a rebuild."""
        available = bool(update_available)
        changed = available != self.update_available
        self.update_available = available
        self.current_version = current_version or self.current_version
        self.latest_version = latest_version or self.latest_version
        label = getattr(self, "update_label", None)
        text = (
            t("env_app_update_badge", version=self.latest_version)
            if available
            else ""
        )
        if label is not None and label.text != text:
            label.text = text
        note = (
            t(
                "env_app_update_tooltip",
                version=self.latest_version,
                current=self.current_version or "-",
            )
            if available
            else ""
        )
        self.tooltip = (
            f"{self._base_tooltip}\n{note}" if note and self._base_tooltip else (
                note or self._base_tooltip
            )
        )
        if changed:
            cocoa_events.set_tooltip(self, self.tooltip)

    def set_selected(self, selected: bool) -> None:
        """Draw (or clear) the Finder-style selection pill behind the icon."""
        self.selected = bool(selected)
        cocoa_events.set_hover_background(
            self.pill,
            self.selected,
            Theme.BG_SELECTION,
            radius=PILL_CORNER_RADIUS,
        )

    def set_last_opened(self, value: str) -> None:
        """Repaint the last-opened caption in place (no widget rebuild)."""
        text = format_last_opened(value, compact=True)
        if text != self.last_opened_label.text:
            self.last_opened_label.text = text

    def set_running(self, running: bool) -> None:
        """Repaint the running indicator in place (no widget rebuild)."""
        running = bool(running)
        if running == self.running:
            return
        self.running = running
        self.status_label.text = ("● " + t("environment_running")) if running else ""
        self.status_label.style.color = (
            Theme.BTN_SUCCESS if running else Theme.TEXT_TERTIARY
        )
        # The context menu holds open/close enablement captured at build time.
        cocoa_events.update_tile_menu(
            self, self._menu_entries(), self._handle_menu
        )

    def _handle_double_click(self) -> None:
        logger.info(
            "Tile double-click: clone=%s running=%s", self.clone_name, self.running
        )
        if self.running:
            return
        callback = self._callbacks.get("open")
        if callback is not None:
            callback()

    def set_batch_menu(
        self,
        entries: tuple[cocoa_events.MenuEntry, ...] | None,
    ) -> None:
        """Swap the per-app menu for the multi-selection batch menu.

        ``entries`` is ``None`` when the tile is not part of a multi-selection.
        """
        if entries == self._batch_entries:
            return
        self._batch_entries = entries
        cocoa_events.update_tile_menu(self, self._menu_entries(), self._handle_menu)

    def _menu_entries(self) -> tuple[cocoa_events.MenuEntry, ...]:
        if self._batch_entries is not None:
            return self._batch_entries
        return (
            cocoa_events.MenuEntry("open", t("environment_app_open"), enabled=not self.running),
            cocoa_events.MenuEntry("close", t("environment_app_close"), enabled=self.running),
            cocoa_events.MenuEntry(
                "update",
                t("env_app_menu_update"),
                enabled=not self.running,
                separator=True,
            ),
            cocoa_events.MenuEntry("edit", t("env_app_menu_edit")),
            cocoa_events.MenuEntry("reveal", t("env_app_menu_reveal")),
        )

    def _handle_menu(self, key: str) -> None:
        logger.info("Tile menu action: clone=%s key=%s", self.clone_name, key)
        if self._batch_entries is not None:
            if self._on_batch_action is not None:
                self._on_batch_action(key)
            return
        if key == "open" and self.running:
            return
        if key == "close" and not self.running:
            return
        callback = self._callbacks.get(key)
        if callback is not None:
            callback()

    def _handle_hover(self, active: bool) -> None:
        if self.selected:
            # Keep the selection pill visible while the pointer moves across it.
            return
        cocoa_events.set_hover_background(
            self.pill, active, Theme.BG_HOVER, radius=PILL_CORNER_RADIUS
        )
