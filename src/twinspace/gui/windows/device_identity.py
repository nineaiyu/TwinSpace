"""Read-only window showing the simulated device identity of an environment."""

from __future__ import annotations

import toga
from toga.style import Pack
from toga.style.pack import CENTER, COLUMN, ROW

from twinspace.core.device_identity import DeviceIdentity
from twinspace.core.i18n import t
from twinspace.gui import cocoa_events
from twinspace.gui.components.wrapping_label import WrappingLabel
from twinspace.gui.patch_cocoa import configure_cocoa_card, configure_cocoa_window
from twinspace.gui.theme import Theme


class DeviceIdentityWindow(toga.Window):
    """Display UUID / serial / hostname / seed with one-click copying."""

    def __init__(
        self,
        name: str,
        identity: DeviceIdentity,
        *,
        keychain_prefix: str = "",
        instance_number: str = "",
    ):
        super().__init__(title=t("device_window_title", name=name), size=(600, 460))
        configure_cocoa_window(self, floating=False)
        self.name = name
        self.identity = identity
        self.keychain_prefix = keychain_prefix
        self.instance_number = instance_number

        self.content = self._build_content()

    def _row(self, key: str, value: str) -> toga.Box:
        row = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=8))
        row.add(
            toga.Label(
                key,
                style=Pack(width=132, font_size=12.5, color=Theme.TEXT_MUTED),
            )
        )
        value_label = WrappingLabel(
            value,
            selectable=True,
            style=Pack(flex=1, font_size=12.5, color=Theme.TEXT_PRIMARY),
        )
        row.add(value_label)
        row.add(
            toga.Button(
                t("btn_copy_short"),
                on_press=lambda widget, text=value: cocoa_events.copy_text(text),
                style=Pack(width=52, height=22, font_size=11),
            )
        )
        return row

    def _build_content(self) -> toga.Box:
        root = toga.Box(
            style=Pack(
                direction=COLUMN,
                margin=(18, 20, 16, 20),
                background_color=Theme.BG_WINDOW,
            )
        )

        header = toga.Box(style=Pack(direction=ROW, align_items=CENTER, margin_bottom=14))
        card = toga.Box(
            style=Pack(direction=COLUMN, flex=1, background_color=Theme.BG_CARD)
        )
        inner = toga.Box(style=Pack(direction=COLUMN, margin=(16, 18, 16, 18)))

        inner.add(
            toga.Label(
                self.name,
                style=Pack(
                    font_size=18,
                    font_weight="bold",
                    color=Theme.TEXT_PRIMARY,
                    margin_bottom=4,
                ),
            )
        )
        inner.add(
            toga.Label(
                t("detail_device_hint"),
                style=Pack(
                    font_size=11.5,
                    color=Theme.TEXT_MUTED,
                    margin_bottom=12,
                ),
            )
        )

        inner.add(self._row(t("detail_label_device_uuid"), self.identity.platform_uuid))
        inner.add(self._row(t("detail_label_device_serial"), self.identity.serial))
        inner.add(self._row(t("detail_label_device_hostname"), self.identity.hostname))
        inner.add(self._row(t("detail_label_device_seed"), self.identity.seed))
        if self.keychain_prefix:
            inner.add(self._row(t("detail_label_keychain_prefix"), self.keychain_prefix))
        if self.instance_number:
            inner.add(self._row(t("detail_label_instance_number"), self.instance_number))

        card.add(inner)
        try:
            configure_cocoa_card(card._impl.native, corner_radius=16.0, border_width=0.5)
        except Exception:
            pass
        header.add(card)
        root.add(header)

        actions = toga.Box(style=Pack(direction=ROW, align_items=CENTER))
        actions.add(
            toga.Button(
                t("win_detail_btn_copy_all"),
                on_press=self._on_copy_all,
                style=Pack(height=30, font_size=12, margin_right=8),
            )
        )
        actions.add(toga.Box(style=Pack(flex=1)))
        actions.add(
            toga.Button(
                t("btn_close"),
                on_press=lambda widget: self.close(),
                style=Pack(height=30, font_size=12),
            )
        )
        root.add(actions)
        return root

    def get_summary_text(self) -> str:
        lines = [
            f"=== {self.name} ===",
            f"{t('detail_label_device_uuid')}: {self.identity.platform_uuid}",
            f"{t('detail_label_device_serial')}: {self.identity.serial}",
            f"{t('detail_label_device_hostname')}: {self.identity.hostname}",
            f"{t('detail_label_device_seed')}: {self.identity.seed}",
        ]
        if self.keychain_prefix:
            lines.append(f"{t('detail_label_keychain_prefix')}: {self.keychain_prefix}")
        if self.instance_number:
            lines.append(f"{t('detail_label_instance_number')}: {self.instance_number}")
        return "\n".join(lines)

    def _on_copy_all(self, widget: toga.Button) -> None:
        cocoa_events.copy_text(self.get_summary_text())
