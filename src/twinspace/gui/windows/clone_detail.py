"""Clone detail window with structured environment and device identity data."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.clone_inspector import CloneInspector, InjectedDetails
from twinspace.core.device_identity import (
    identity_for_clone,
    instance_number,
    keychain_prefix,
)
from twinspace.core.i18n import t
from twinspace.core.locale import SUPPORTED_LANGUAGES
from twinspace.core.state import CloneRecord, is_clone_running
from twinspace.gui import cocoa_events
from twinspace.gui.components.wrapping_label import WrappingLabel
from twinspace.gui.patch_cocoa import (
    configure_cocoa_card,
    configure_cocoa_multiline_text_view,
    configure_cocoa_window,
)
from twinspace.gui.theme import Theme
from twinspace.validation import redact_url_credentials

copy_to_clipboard = cocoa_events.copy_text

__all__ = ["CloneDetailWindow", "copy_to_clipboard"]


class CloneDetailWindow(toga.Window):
    """Read-only parameters page for one clone, including its simulated device."""

    def __init__(
        self,
        record: CloneRecord,
        on_edit: Optional[Callable[[CloneRecord], None]] = None,
        on_update: Optional[Callable[[CloneRecord], None]] = None,
        on_reveal: Optional[Callable[[CloneRecord], None]] = None,
    ):
        super().__init__(title=t("win_detail_title", name=record.clone_name), size=(700, 780))
        configure_cocoa_window(self, floating=False)
        self.record = record
        self.details: InjectedDetails = CloneInspector.inspect(record)
        self._on_edit = on_edit
        self._on_update = on_update
        self._on_reveal = on_reveal
        self.identity = identity_for_clone(
            record.clone_name,
            record.new_bundle_id or record.bundle_id,
            record.env_group or "",
        )
        self._running = self._detect_running()

        self._build_labels()
        self.content = self._build_content()

    # ── data helpers ────────────────────────────────────────────────

    def _detect_running(self) -> bool:
        try:
            return is_clone_running(self.record.dest_path)
        except Exception:
            return False

    def _language_label(self) -> str:
        lang_key = SUPPORTED_LANGUAGES.get(self.record.language, {}).get(
            "label_key", "lang_system"
        )
        return t(lang_key)

    def _strategy_label(self) -> str:
        return (
            t("card_strategy_soft")
            if self.record.strategy == "soft_clone"
            else t("card_strategy_hard")
        )

    def _proxy_label(self) -> str:
        if not self.record.proxy_enabled:
            return t("list_proxy_disabled")
        return redact_url_credentials(self.record.proxy_summary)

    def _overrides_text(self) -> str:
        overrides = getattr(self.record, "env_overrides", None) or {}
        if not overrides:
            return "—"
        return "\n".join(f"{key}={value}" for key, value in sorted(overrides.items()))

    # ── widgets ─────────────────────────────────────────────────────

    def _value_label(self, text: str) -> WrappingLabel:
        return WrappingLabel(
            text,
            selectable=True,
            style=Pack(flex=1, font_size=12.5, color=Theme.TEXT_PRIMARY),
        )

    def _build_labels(self) -> None:
        record = self.record
        self.label_clone_name = WrappingLabel(
            record.clone_name,
            style=Pack(font_weight="bold", font_size=20, color=Theme.TEXT_PRIMARY),
        )
        self.label_display_name = self._value_label(
            getattr(record, "display_name", None) or "—"
        )
        self.label_source_app = self._value_label(record.source_app)
        self.label_source_path = self._value_label(record.source_path)
        self.label_bundle_id = self._value_label(record.bundle_id)
        self.label_new_bundle_id = self._value_label(record.new_bundle_id or "—")
        self.label_strategy = self._value_label(self._strategy_label())
        injection = (
            getattr(record, "injection_strategy", None)
            or self.details.injection_strategy
            or "auto"
        )
        self.label_injection_strategy = self._value_label(injection)
        self.label_language = self._value_label(self._language_label())
        self.label_dest_path = self._value_label(record.dest_path)
        self.label_data_dir = self._value_label(record.data_dir)
        self.label_created_at = self._value_label(record.created_at)
        self.label_proxy = self._value_label(self._proxy_label())

        env_group = getattr(record, "env_group", "") or ""
        env_dir = getattr(record, "env_dir", "") or ""
        self.label_env_group = self._value_label(env_group or "—")
        self.label_env_dir = self._value_label(env_dir or "—")
        self.label_keychain_prefix = self._value_label(
            keychain_prefix(record.clone_name, record.new_bundle_id or record.bundle_id)
        )

        self.label_device_uuid = self._value_label(self.identity.platform_uuid)
        self.label_device_serial = self._value_label(self.identity.serial)
        self.label_device_hostname = self._value_label(self.identity.hostname)
        self.label_device_seed = self._value_label(self.identity.seed)
        self.label_instance_number = self._value_label(
            instance_number(record.clone_name, record.new_bundle_id or record.bundle_id)
        )

        self.label_notes = self._value_label(getattr(record, "notes", "") or "—")
        self.label_env_overrides = self._value_label(self._overrides_text())

    def _row(self, key: str, value: toga.Widget) -> toga.Box:
        row = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=7))
        row.add(
            toga.Label(
                key,
                style=Pack(width=136, font_size=12.5, color=Theme.TEXT_MUTED),
            )
        )
        row.add(value)
        return row

    def _copy_row(self, key: str, value: toga.Widget, copy_value: str) -> toga.Box:
        row = self._row(key, value)
        row.add(toga.Box(style=Pack(width=6)))
        row.add(
            toga.Button(
                t("btn_copy_short"),
                on_press=lambda widget, text=copy_value: copy_to_clipboard(text),
                style=Pack(width=52, height=22, font_size=11),
            )
        )
        return row

    def _section(self, title: str) -> tuple[toga.Box, toga.Box]:
        card = toga.Box(
            style=Pack(direction=COLUMN, margin_bottom=12, background_color=Theme.BG_CARD)
        )
        inner = toga.Box(style=Pack(direction=COLUMN, margin=(14, 16, 14, 16)))
        inner.add(
            toga.Label(
                title,
                style=Pack(
                    font_size=14,
                    font_weight="bold",
                    color=Theme.TEXT_PRIMARY,
                    margin_bottom=10,
                ),
            )
        )
        card.add(inner)
        try:
            configure_cocoa_card(card._impl.native, corner_radius=12.0, border_width=0.5)
        except Exception:
            pass
        return card, inner

    def _build_header(self) -> toga.Box:
        header = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=14))

        icon = cocoa_events.load_app_icon(self.record.dest_path, size=64)
        if icon is not None:
            header.add(
                toga.ImageView(icon, style=Pack(width=56, height=56, margin_right=12))
            )

        title_box = toga.Box(style=Pack(direction=COLUMN, flex=1))
        title_box.add(self.label_clone_name)
        title_box.add(
            toga.Label(
                self.record.source_app,
                style=Pack(font_size=12.5, color=Theme.TEXT_SECONDARY, margin_top=2),
            )
        )

        badges = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_top=6))
        badges.add(
            toga.Label(
                self._strategy_label(),
                style=Pack(
                    font_size=11.5,
                    font_weight="bold",
                    color=Theme.ACCENT_BLUE,
                    margin_right=10,
                ),
            )
        )
        if self.record.env_group:
            badges.add(
                toga.Label(
                    t("card_env_badge", name=self.record.env_group),
                    style=Pack(
                        font_size=11.5,
                        font_weight="bold",
                        color=Theme.BADGE_CUSTOM_TEXT,
                        margin_right=10,
                    ),
                )
            )
        if self._running:
            badges.add(
                toga.Label(
                    "● " + t("environment_running"),
                    style=Pack(
                        font_size=11.5,
                        font_weight="bold",
                        color=Theme.BTN_SUCCESS,
                    ),
                )
            )
        title_box.add(badges)
        header.add(title_box)
        return header

    def _build_content(self) -> toga.Box:
        root = toga.Box(
            style=Pack(
                direction=COLUMN,
                margin=(16, 18, 14, 18),
                background_color=Theme.BG_WINDOW,
            )
        )
        root.add(self._build_header())

        scroll = toga.ScrollContainer(style=Pack(flex=1), horizontal=False)
        body = toga.Box(style=Pack(direction=COLUMN))
        scroll.content = body

        basic_card, basic = self._section(t("win_detail_section_basic"))
        basic.add(self._row(t("detail_label_display_name"), self.label_display_name))
        basic.add(self._row(t("detail_label_source_app"), self.label_source_app))
        basic.add(self._row(t("detail_label_source_path"), self.label_source_path))
        basic.add(self._row(t("detail_label_bundle_id"), self.label_bundle_id))
        basic.add(self._row(t("detail_label_new_bundle_id"), self.label_new_bundle_id))
        basic.add(self._row(t("detail_label_strategy"), self.label_strategy))
        basic.add(self._row(t("detail_label_injection"), self.label_injection_strategy))
        basic.add(self._row(t("detail_label_language"), self.label_language))
        basic.add(self._row(t("detail_label_created_at"), self.label_created_at))
        body.add(basic_card)

        env_card, env = self._section(t("detail_section_environment"))
        env.add(self._row(t("detail_label_env_group"), self.label_env_group))
        env.add(self._row(t("detail_label_env_dir"), self.label_env_dir))
        env.add(self._row(t("detail_label_data_dir"), self.label_data_dir))
        env.add(self._row(t("detail_label_dest_path"), self.label_dest_path))
        env.add(
            self._copy_row(
                t("detail_label_keychain_prefix"),
                self.label_keychain_prefix,
                self.label_keychain_prefix.text,
            )
        )
        body.add(env_card)

        device_card, device = self._section(t("detail_section_device"))
        device.add(
            toga.Label(
                t("detail_device_hint"),
                style=Pack(
                    font_size=11.5,
                    color=Theme.TEXT_MUTED,
                    margin_bottom=8,
                ),
            )
        )
        device.add(
            self._copy_row(
                t("detail_label_device_uuid"),
                self.label_device_uuid,
                self.identity.platform_uuid,
            )
        )
        device.add(
            self._copy_row(
                t("detail_label_device_serial"),
                self.label_device_serial,
                self.identity.serial,
            )
        )
        device.add(
            self._copy_row(
                t("detail_label_device_hostname"),
                self.label_device_hostname,
                self.identity.hostname,
            )
        )
        device.add(
            self._copy_row(
                t("detail_label_device_seed"),
                self.label_device_seed,
                self.identity.seed,
            )
        )
        device.add(self._row(t("detail_label_instance_number"), self.label_instance_number))
        body.add(device_card)

        network_card, network = self._section(t("detail_section_network"))
        network.add(self._row(t("detail_label_proxy"), self.label_proxy))
        body.add(network_card)

        notes_card, notes = self._section(t("detail_section_notes"))
        notes.add(self._row(t("detail_label_notes"), self.label_notes))
        notes.add(self._row(t("detail_label_env_overrides"), self.label_env_overrides))
        body.add(notes_card)

        technical_card, technical = self._section(t("detail_section_technical"))
        self.text_content = toga.MultilineTextInput(
            value=self.get_summary_text(),
            readonly=True,
            style=Pack(
                flex=1,
                height=150,
                font_family="monospace",
                font_size=11.5,
                background_color=Theme.BG_WINDOW,
                margin_bottom=8,
            ),
        )
        technical.add(self.text_content)
        self.btn_copy_cmd = toga.Button(
            t("win_detail_btn_copy_cmd"),
            on_press=self._on_copy_cmd,
            enabled=bool(self.details.exec_command),
            style=Pack(height=28, font_size=12),
        )
        cocoa_events.configure_button_icon(self.btn_copy_cmd, "doc.on.doc")
        technical.add(self.btn_copy_cmd)
        body.add(technical_card)

        root.add(scroll)
        root.add(self._build_footer())
        self._configure_native_view(self.text_content)
        return root

    def _build_footer(self) -> toga.Box:
        footer = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_top=10))

        self.btn_open_dir = toga.Button(
            t("detail_btn_open_data"),
            on_press=self._on_open_dir,
            style=Pack(height=30, font_size=12, margin_right=8),
        )
        cocoa_events.configure_button_icon(self.btn_open_dir, "folder")
        footer.add(self.btn_open_dir)

        if self._on_edit is not None:
            edit_button = toga.Button(
                t("btn_edit"),
                on_press=lambda widget: self._on_edit(self.record),
                style=Pack(height=30, font_size=12, margin_right=8),
            )
            cocoa_events.configure_button_icon(edit_button, "pencil")
            footer.add(edit_button)
        if self._on_update is not None:
            update_button = toga.Button(
                t("btn_update"),
                on_press=lambda widget: self._on_update(self.record),
                style=Pack(height=30, font_size=12, margin_right=8),
            )
            cocoa_events.configure_button_icon(update_button, "arrow.clockwise")
            footer.add(update_button)
        if self._on_reveal is not None:
            reveal_button = toga.Button(
                t("env_app_menu_reveal"),
                on_press=lambda widget: self._on_reveal(self.record),
                style=Pack(height=30, font_size=12, margin_right=8),
            )
            cocoa_events.configure_button_icon(reveal_button, "magnifyingglass")
            footer.add(reveal_button)

        footer.add(toga.Box(style=Pack(flex=1)))
        self.btn_copy_all = toga.Button(
            t("win_detail_btn_copy_all"),
            on_press=self._on_copy_all,
            style=Pack(height=30, font_size=12, margin_right=8),
        )
        cocoa_events.configure_button_icon(self.btn_copy_all, "doc.on.doc")
        self.btn_close = toga.Button(
            t("btn_close"),
            on_press=lambda widget: self.close(),
            style=Pack(height=30, font_size=12),
        )
        cocoa_events.configure_button_icon(self.btn_close, "xmark")
        footer.add(self.btn_copy_all)
        footer.add(self.btn_close)
        return footer

    def _on_open_dir(self, widget: toga.Button) -> None:
        target = Path(self.record.data_dir)
        if not target.exists():
            target = Path(self.record.dest_path).parent
        if target.exists():
            subprocess.Popen(["open", str(target)])

    def _configure_native_view(self, summary_text: toga.MultilineTextInput) -> None:
        """Apply native Cocoa styling and readonly properties to the technical text view."""
        summary_text.readonly = True
        if sys.platform == "darwin":
            try:
                native = getattr(getattr(summary_text, "_impl", None), "native", None)
                configure_cocoa_multiline_text_view(native, font_size=11.5, readonly=True)
            except Exception:
                pass

    def get_summary_text(self) -> str:
        """Generate a complete, copyable text report of the clone."""
        record = self.record
        lines = [
            f"=== {record.clone_name} ({t('win_detail_section_basic')}) ===",
            f"{t('detail_label_display_name')}: {getattr(record, 'display_name', None) or '—'}",
            t("win_detail_source_app", source_app=record.source_app),
            t("win_detail_source_path", path=record.source_path),
            t("win_detail_bundle_id", bundle_id=record.bundle_id),
            t("win_detail_new_bundle_id", new_bundle_id=record.new_bundle_id or "—"),
            t("win_detail_strategy", strategy=self._strategy_label()),
            f"{t('detail_label_injection')}: {getattr(record, 'injection_strategy', None) or self.details.injection_strategy or 'auto'}",
            f"{t('detail_label_language')}: {self._language_label()}",
            t("win_detail_dest_path", dest_path=record.dest_path),
            t("win_detail_data_dir", data_dir=record.data_dir),
            t("win_detail_created_at", created_at=record.created_at),
            t("win_detail_proxy", proxy=self._proxy_label()),
            "",
            f"=== {t('detail_section_environment')} ===",
            f"{t('detail_label_env_group')}: {getattr(record, 'env_group', '') or '—'}",
            f"{t('detail_label_env_dir')}: {getattr(record, 'env_dir', '') or '—'}",
            f"{t('detail_label_keychain_prefix')}: {keychain_prefix(record.clone_name, record.new_bundle_id or record.bundle_id)}",
            "",
            f"=== {t('detail_section_device')} ===",
            f"{t('detail_label_device_uuid')}: {self.identity.platform_uuid}",
            f"{t('detail_label_device_serial')}: {self.identity.serial}",
            f"{t('detail_label_device_hostname')}: {self.identity.hostname}",
            f"{t('detail_label_device_seed')}: {self.identity.seed}",
            f"{t('detail_label_instance_number')}: {instance_number(record.clone_name, record.new_bundle_id or record.bundle_id)}",
            "",
            f"=== {t('detail_section_notes')} ===",
            f"{t('detail_label_notes')}: {getattr(record, 'notes', '') or '—'}",
            f"{t('detail_label_env_overrides')}: {self._overrides_text()}",
            "",
            f"=== {t('win_detail_section_injected')} ===",
            f"[{t('win_detail_launch_args')}]",
        ]
        if self.details.launch_args:
            for arg in self.details.launch_args:
                lines.append(f"  • {arg}")
        else:
            lines.append(f"  {t('win_detail_none')}")

        lines.append("")
        lines.append(f"[{t('win_detail_env_vars')}]")
        if self.details.env_vars:
            for key, value in self.details.env_vars.items():
                lines.append(f"  • {key}={value}")
        else:
            lines.append(f"  {t('win_detail_none')}")

        lines.append("")
        lines.append(f"[{t('win_detail_exec_cmd')}]")
        lines.append(f"  {self.details.exec_command or t('win_detail_none')}")
        return "\n".join(lines)

    def _on_copy_all(self, widget: toga.Button) -> None:
        if copy_to_clipboard(self.get_summary_text()):
            self.btn_copy_all.text = t("win_detail_all_copied")
            self._reset_button_later(self.btn_copy_all, t("win_detail_btn_copy_all"))

    def _on_copy_cmd(self, widget: toga.Button) -> None:
        command = self.details.exec_command
        if command and copy_to_clipboard(command):
            self.btn_copy_cmd.text = t("win_detail_cmd_copied")
            self._reset_button_later(self.btn_copy_cmd, t("win_detail_btn_copy_cmd"))

    def _reset_button_later(self, button: toga.Button, text: str) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        async def _reset():
            await asyncio.sleep(2)
            button.text = text

        loop.create_task(_reset())
