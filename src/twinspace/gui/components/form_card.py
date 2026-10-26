"""Grouped form card shared by the settings, probe and doctor pages.

The three pages are all "stacked cards of labelled form rows".  Keeping the
metrics in one place stops them from drifting apart: every card uses the same
16/18pt inset, the same 120pt label column and the same 4-6-8-10 spacing rhythm
as macOS System Settings.
"""

from __future__ import annotations

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.gui.theme import Theme

# Apple HIG grouped-form metrics: 16pt vertical / 18pt horizontal inset with a
# 120pt label column keeps every card on the same optical grid.
CARD_PADDING = (16, 18, 16, 18)
LABEL_WIDTH = 120


class FormCard(toga.Box):
    """Elevated card that groups labelled form rows under a compact section title."""

    padding = CARD_PADDING
    label_width = LABEL_WIDTH

    def __init__(
        self,
        title: str | None = None,
        *,
        subtitle: str | None = None,
        margin_bottom: int = 14,
        padding: tuple[int, int, int, int] | None = None,
        fill: bool = False,
    ):
        """Build the card shell; children are routed into the padded ``body``.

        Args:
            title: Optional in-card section title rendered at 13pt bold.
            subtitle: Optional muted line directly below the title.
            margin_bottom: Gap between this card and the next stacked card.
            padding: Override the default ``(16, 18, 16, 18)`` body inset.
            fill: Let the card and its body expand to the available height
                (used by cards that host a table).
        """
        card_style = {
            "direction": COLUMN,
            "margin_bottom": margin_bottom,
            "background_color": Theme.BG_CARD,
        }
        body_style = {"direction": COLUMN, "margin": padding or self.padding}
        if fill:
            card_style["flex"] = 1
            body_style["flex"] = 1
        super().__init__(style=Pack(**card_style))
        self.body = toga.Box(style=Pack(**body_style))
        super().add(self.body)

        self.title_label: toga.Label | None = None
        self.subtitle_label: toga.Label | None = None

        if title:
            self.title_label = toga.Label(
                title,
                style=Pack(
                    font_size=Theme.FONT_CARD_TITLE,
                    font_weight="bold",
                    color=Theme.TEXT_PRIMARY,
                    margin_bottom=2 if subtitle else 10,
                ),
            )
            self.body.add(self.title_label)
        if subtitle:
            self.subtitle_label = toga.Label(
                subtitle,
                style=Pack(
                    font_size=Theme.FONT_CAPTION,
                    color=Theme.TEXT_TERTIARY,
                    margin_bottom=12,
                ),
            )
            self.body.add(self.subtitle_label)

    def add(self, *children: toga.Widget) -> None:
        """Add children to the padded body so callers never touch the shell."""
        for child in children:
            self.body.add(child)

    def make_row(
        self,
        label: str | None,
        control: toga.Widget,
        *,
        label_width: int | None = None,
        margin_bottom: int = 8,
    ) -> toga.Box:
        """Build a `label | control` line without appending it to the card."""
        row = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=margin_bottom))
        if label is not None:
            row.add(
                toga.Label(
                    label,
                    style=Pack(
                        width=label_width or self.label_width,
                        font_size=Theme.FONT_FIELD_LABEL,
                        color=Theme.TEXT_PRIMARY,
                    ),
                )
            )
        row.add(control)
        return row

    def add_row(
        self,
        label: str | None,
        control: toga.Widget,
        *,
        label_width: int | None = None,
        margin_bottom: int = 8,
    ) -> toga.Box:
        """Add a `label | control` line and return the row for extra widgets."""
        row = self.make_row(
            label,
            control,
            label_width=label_width,
            margin_bottom=margin_bottom,
        )
        self.body.add(row)
        return row

    def add_hint(
        self,
        text: str,
        *,
        margin_top: int = 4,
        margin_bottom: int = 8,
        margin_left: int = 0,
    ) -> toga.Label:
        """Add muted helper text below a field group."""
        hint = toga.Label(
            text,
            style=Pack(
                font_size=Theme.FONT_CAPTION,
                color=Theme.TEXT_MUTED,
                margin=(margin_top, 0, margin_bottom, margin_left),
            ),
        )
        self.body.add(hint)
        return hint

    def add_divider(self, *, margin_top: int = 2, margin_bottom: int = 12) -> toga.Box:
        """Add a hairline separator between two field groups inside the card."""
        divider = toga.Box(
            style=Pack(
                height=1,
                margin=(margin_top, 0, margin_bottom, 0),
                background_color=Theme.BORDER_SUBTLE,
            )
        )
        self.body.add(divider)
        return divider

    def add_action_row(self, *buttons: toga.Widget, margin_top: int = 12) -> toga.Box:
        """Add a left-aligned button row; buttons keep their natural width."""
        row = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_top=margin_top))
        for button in buttons:
            row.add(button)
        self.body.add(row)
        return row
