"""Guard tests for the shared grouped-form card metrics used by settings/probe/doctor."""

import toga
from toga.colors import Color

from twinspace.gui.components.form_card import CARD_PADDING, LABEL_WIDTH, FormCard
from twinspace.gui.theme import Theme


def test_form_card_shell_metrics():
    card = FormCard("Section")

    assert card.style.direction == "column"
    assert card.style.margin_bottom == 14
    assert card.style.background_color == Color.parse(Theme.BG_CARD)
    assert card.body in card.children

    body = card.body
    assert (
        body.style.margin_top,
        body.style.margin_right,
        body.style.margin_bottom,
        body.style.margin_left,
    ) == CARD_PADDING == (16, 18, 16, 18)

    title = card.title_label
    assert title is not None
    assert title.text == "Section"
    # Toga floors fractional point sizes, so the card title sits at 13pt bold.
    assert title.style.font_size == Theme.FONT_CARD_TITLE == 13
    assert title.style.font_weight == "bold"
    assert title.style.color == Color.parse(Theme.TEXT_PRIMARY)


def test_form_card_subtitle_tightens_title_gap():
    card = FormCard("Section", subtitle="Supporting line")

    assert card.title_label.style.margin_bottom == 2
    assert card.subtitle_label.text == "Supporting line"
    # Fractional tokens are floored by Toga (FONT_CAPTION = 11.5 -> 11pt).
    assert card.subtitle_label.style.font_size == int(Theme.FONT_CAPTION) == 11
    assert card.subtitle_label.style.color == Color.parse(Theme.TEXT_TERTIARY)


def test_form_card_routes_children_into_body():
    card = FormCard()
    child = toga.Label("child")

    card.add(child)

    assert child in card.body.children
    assert child not in card.children


def test_form_card_row_uses_aligned_label_column():
    card = FormCard()
    control = toga.TextInput()

    row = card.add_row("Root", control)

    label = row.children[0]
    assert label.text == "Root"
    assert label.style.width == LABEL_WIDTH == 120
    assert label.style.font_size == Theme.FONT_FIELD_LABEL
    assert control in row.children
    assert row.style.align_items == "center"
    assert row.style.margin_bottom == 8
    assert row in card.body.children


def test_form_card_make_row_returns_detached_row():
    card = FormCard()
    control = toga.TextInput()

    row = card.make_row("User", control)

    assert control in row.children
    assert row not in card.body.children

    holder = toga.Box()
    holder.add(row)
    assert row in holder.children


def test_form_card_hint_and_divider():
    card = FormCard()

    hint = card.add_hint("Helper text", margin_left=12)
    assert hint.style.font_size == int(Theme.FONT_CAPTION)
    assert hint.style.color == Color.parse(Theme.TEXT_MUTED)
    assert hint.style.margin_left == 12

    divider = card.add_divider()
    assert divider.style.height == 1
    assert divider.style.background_color == Color.parse(Theme.BORDER_SUBTLE)


def test_form_card_action_row_keeps_button_natural_width():
    card = FormCard()
    button = toga.Button("Open")

    row = card.add_action_row(button)

    assert button in row.children
    assert button.style.flex == 0
    assert row.style.direction == "row"
    assert row.style.margin_top == 12


def test_form_card_fill_expands_card_and_body():
    card = FormCard(fill=True, margin_bottom=0, padding=(8, 8, 8, 8))

    assert card.style.flex == 1
    assert card.body.style.flex == 1
    assert card.style.margin_bottom == 0
    assert card.body.style.margin_top == 8


def test_settings_view_cards_share_form_card_shell():
    from twinspace.gui.views.settings_view import SettingsView

    view = SettingsView()
    scroll = next(child for child in view.children if isinstance(child, toga.ScrollContainer))
    cards = [child for child in scroll.content.children if isinstance(child, FormCard)]

    assert len(cards) == 5
    assert all(card.title_label is not None for card in cards)
    assert all(card.title_label.style.font_size == Theme.FONT_CARD_TITLE for card in cards)


def test_probe_and_doctor_cards_share_form_card_shell():
    from twinspace.gui.views.doctor_view import DoctorView
    from twinspace.gui.views.probe_view import ProbeView

    probe = ProbeView()
    assert isinstance(probe.card_results, FormCard)
    assert probe.card_results.title_label.style.font_size == Theme.FONT_CARD_TITLE

    doctor = DoctorView()
    assert isinstance(doctor.card_summary, FormCard)
    assert doctor.label_summary.style.font_size == Theme.FONT_SUBHEADER
