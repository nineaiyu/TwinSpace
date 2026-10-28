"""CloneCard widget for presenting application clone instances."""

from pathlib import Path
from typing import Callable, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.i18n import t
from twinspace.core.state import CloneRecord
from twinspace.core.timestamps import format_last_opened
from twinspace.gui import cocoa_events
from twinspace.gui.patch_cocoa import configure_cocoa_danger_button
from twinspace.gui.theme import Theme
from twinspace.validation import redact_url_credentials


class CloneCard(toga.Box):
    """Card widget rendering single clone instance metadata and action controls."""

    def __init__(
        self,
        record: CloneRecord,
        on_launch: Optional[Callable[[CloneRecord], None]] = None,
        on_open_dir: Optional[Callable[[CloneRecord], None]] = None,
        on_update: Optional[Callable[[CloneRecord], None]] = None,
        on_edit: Optional[Callable[[CloneRecord], None]] = None,
        on_detail: Optional[Callable[[CloneRecord], None]] = None,
        on_delete: Optional[Callable[[CloneRecord], None]] = None,
    ):
        super().__init__(style=Pack(direction=COLUMN, margin=(6, 8, 8, 8), flex=1, background_color=Theme.BG_CARD))
        self.record = record

        # Card Header: Icon + Name + Strategy Tag
        header = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin=(12, 14, 6, 14)))
        app_icon = cocoa_events.load_app_icon(record.dest_path, size=32)
        if app_icon is not None:
            header.add(
                toga.ImageView(app_icon, style=Pack(width=32, height=32, margin_right=10))
            )
        self.label_name = toga.Label(
            record.clone_name,
            style=Pack(font_weight="bold", font_size=16, flex=1, color=Theme.TEXT_PRIMARY),
        )
        is_soft = record.strategy == "soft_clone"
        strat_badge = t("card_strategy_soft") if is_soft else t("card_strategy_hard")
        strat_color = Theme.BTN_SUCCESS if is_soft else Theme.ACCENT_BLUE
        self.label_strategy = toga.Label(
            strat_badge,
            style=Pack(font_size=12, font_weight="bold", color=strat_color),
        )
        self.label_env = None
        header.add(self.label_name)
        if getattr(record, "env_group", ""):
            self.label_env = toga.Label(
                t("card_env_badge", name=record.env_group),
                style=Pack(
                    font_size=11,
                    font_weight="bold",
                    color=Theme.BADGE_CUSTOM_TEXT,
                    margin_right=8,
                ),
            )
            header.add(self.label_env)
        header.add(self.label_strategy)
        self.add(header)

        # Card Body: Metadata info
        body = toga.Box(style=Pack(direction=COLUMN, margin=(0, 14, 10, 14)))
        body.add(toga.Label(t("card_label_source", source_app=record.source_app), style=Pack(font_size=12.5, color=Theme.TEXT_MUTED, margin_bottom=3)))
        body.add(toga.Label(t("card_label_path", path=Path(record.dest_path).name), style=Pack(font_size=12, color=Theme.TEXT_TERTIARY, margin_bottom=3)))
        proxy_info = redact_url_credentials(record.proxy_summary) if record.proxy_enabled else t("card_proxy_disabled")
        body.add(toga.Label(t("card_label_proxy", proxy_info=proxy_info), style=Pack(font_size=12, color=Theme.TEXT_TERTIARY)))
        self.last_opened_label = toga.Label(
            format_last_opened(getattr(record, "last_opened_at", "")),
            style=Pack(font_size=11.5, color=Theme.TEXT_TERTIARY, margin_top=3),
        )
        body.add(self.last_opened_label)
        notes_raw = (getattr(record, "notes", "") or "").replace("\n", " ").replace("\r", "")
        if notes_raw:
            notes_display = (notes_raw[:40] + "…") if len(notes_raw) > 40 else notes_raw
            body.add(toga.Label(
                f"{t('win_edit_notes_label')} {notes_display}",
                style=Pack(font_size=11.5, color=Theme.TEXT_TERTIARY, margin_top=3),
            ))
        self.add(body)

        # Card Footer: Action buttons — use flex layout to prevent overflow on any card width
        actions = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin=(0, 10, 12, 10)))

        # 1-Click Direct Launch Button (flex=2: takes proportionally more space)
        btn_launch = toga.Button(
            t("btn_launch"),
            on_press=lambda w: on_launch(record) if on_launch else None,
            style=Pack(font_weight="bold", font_size=12, height=30, margin_right=4, flex=2),
        )
        btn_open_dir = toga.Button(t("btn_open_dir_short"), on_press=lambda w: on_open_dir(record) if on_open_dir else None, style=Pack(margin_right=4, height=30, font_size=11, flex=1))
        btn_update = toga.Button(t("btn_update_short"), on_press=lambda w: on_update(record) if on_update else None, style=Pack(margin_right=4, height=30, font_size=11, flex=1))
        btn_edit = toga.Button(t("btn_edit_short"), on_press=lambda w: on_edit(record) if on_edit else None, style=Pack(margin_right=4, height=30, font_size=11, flex=1))
        btn_detail = toga.Button(t("btn_detail_short"), on_press=lambda w: on_detail(record) if on_detail else None, style=Pack(margin_right=4, height=30, font_size=11, flex=1))
        btn_delete = toga.Button(t("btn_delete_short"), on_press=lambda w: on_delete(record) if on_delete else None, style=Pack(height=30, font_size=11))
        configure_cocoa_danger_button(btn_delete)

        actions.add(btn_launch)
        actions.add(btn_open_dir)
        actions.add(btn_update)
        actions.add(btn_edit)
        actions.add(btn_detail)
        actions.add(toga.Box(style=Pack(flex=1)))
        actions.add(btn_delete)
        self.add(actions)

    def set_last_opened(self, value: str) -> None:
        """Repaint the last-opened line in place (no widget rebuild)."""
        self.record.last_opened_at = value
        self.last_opened_label.text = format_last_opened(value)



