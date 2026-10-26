"""Guard tests for the flattened, card-friendly table appearance."""

import toga
from toga.style import Pack

from twinspace.core.i18n import t
from twinspace.gui.patch_cocoa import TABLE_ROW_HEIGHT
from twinspace.gui.views.clone_list import CloneNameColumn


def test_tables_use_flat_modern_style(toga_app):
    table = toga.Table(
        columns=[t("list_col_name")],
        data=[("Alpha",)],
        style=Pack(flex=1),
    )
    impl = table._impl

    assert impl.native.borderType == 0  # NSNoBorder
    assert impl.native.autohidesScrollers is True
    assert impl.native_table.usesAlternatingRowBackgroundColors is False
    assert impl.native_table.rowHeight == TABLE_ROW_HEIGHT == 44.0


def test_clone_name_column_provides_icon_and_text():
    column = CloneNameColumn("Name", "name", lambda name: f"icon:{name}")
    row = type("Row", (), {"name": "ZCode-phone1"})()
    assert column.text(row) == "ZCode-phone1"
    assert column.icon(row) == "icon:ZCode-phone1"


def test_clone_name_column_ignores_icon_provider_errors():
    def broken(name):
        raise RuntimeError("no icon")

    column = CloneNameColumn("Name", "name", broken)
    row = type("Row", (), {"name": "ZCode-phone1"})()
    assert column.icon(row) is None
