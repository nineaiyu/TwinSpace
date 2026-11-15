"""Tests for the storage cleanup window (selection + confirmed deletion)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from twinspace.core.cleanup import (
    CATEGORY_CACHE,
    CATEGORY_ORPHAN,
    CATEGORY_PACKAGE,
    CacheEntry,
    CleanupReport,
)
from twinspace.core.i18n import t
from twinspace.gui import cocoa_events
from twinspace.gui.services.data_size import format_size
from twinspace.gui.windows.cache_cleanup import CacheCleanupWindow


def _entry(tmp_path, name: str, category: str, size: int) -> CacheEntry:
    path = tmp_path / name
    path.mkdir(parents=True, exist_ok=True)
    return CacheEntry(
        path=path,
        size=size,
        category=category,
        clone_name="App-b1",
        root=tmp_path,
        detail=name,
    )


def _window() -> CacheCleanupWindow:
    return CacheCleanupWindow(None, MagicMock(), auto_scan=False)


def test_render_groups_entries_with_safe_defaults(tmp_path):
    window = _window()
    cache = _entry(tmp_path, "go-build", CATEGORY_CACHE, 1024)
    package = _entry(tmp_path, "pnpm", CATEGORY_PACKAGE, 2048)
    orphan = _entry(tmp_path, "Gone-b1", CATEGORY_ORPHAN, 4096)

    window._render_report(CleanupReport(entries=[cache, package, orphan]))

    assert len(window._rows) == 3
    # Caches are preselected; package caches and orphaned data are not.
    assert window._selected_entries() == [cache]
    assert window.btn_clean.enabled is True
    assert window.label_summary.text == t(
        "storage_cleanup_summary", count=3, size=format_size(7168)
    )

    window._on_select_none()
    assert window._selected_entries() == []
    assert window.btn_clean.enabled is False

    window._on_select_all()
    assert len(window._selected_entries()) == 3


def test_bulk_selection_updates_summary_once_and_paints_glyphs(tmp_path):
    """Select All/None must not recompute the summary per row.

    That per-row callback is what made a 174-row click take ~5 seconds
    (each row triggered a full-list scan plus a status-label relayout).
    """
    window = _window()
    entries = [
        _entry(tmp_path, f"cache-{index}", CATEGORY_CACHE, 1024)
        for index in range(6)
    ]
    window._render_report(CleanupReport(entries=entries))

    calls: list[int] = []
    for row in window._rows:
        row._on_toggle = lambda: calls.append(1)

    window._on_select_none()
    assert calls == []
    assert window._selected_entries() == []
    assert all(row.mark.text == "☐" for row in window._rows)

    window._on_select_all()
    assert calls == []
    assert len(window._selected_entries()) == 6
    assert all(row.mark.text == "☑" for row in window._rows)


def test_single_row_toggle_notifies_once(tmp_path):
    window = _window()
    entry = _entry(tmp_path, "go-build", CATEGORY_CACHE, 1024)
    window._render_report(CleanupReport(entries=[entry]))
    calls: list[int] = []
    row = window._rows[0]
    row._on_toggle = lambda: calls.append(1)

    row.toggle()
    assert calls == [1]
    assert row.selected is False
    assert row.mark.text == "☐"


def test_render_empty_report_shows_hint(tmp_path):
    window = _window()
    window._render_report(CleanupReport(entries=[], skipped_running=["App-b1"]))

    assert window._rows == []
    assert window.label_summary.text == t("storage_cleanup_empty")
    assert "App-b1" in window.label_status.text
    assert window.btn_clean.enabled is False


def test_clean_selected_confirms_before_deleting(tmp_path):
    async def _test():
        window = _window()
        entry = _entry(tmp_path, "go-build", CATEGORY_CACHE, 2048)
        window._render_report(CleanupReport(entries=[entry]))
        window.scan = lambda: None

        with patch(
            "twinspace.gui.windows.cache_cleanup.delete_entries",
            return_value=(2048, []),
        ) as deleter, patch.object(
            cocoa_events, "confirm_with_labels", new=AsyncMock(return_value=True)
        ) as confirm:
            await window._clean_selected()

        confirm.assert_awaited_once()
        deleter.assert_called_once()
        assert deleter.call_args.args[0] == [entry]
        assert window.label_status.text == t(
            "storage_cleanup_done", size=format_size(2048)
        )

    asyncio.run(_test())


def test_clean_selected_aborts_when_not_confirmed(tmp_path):
    async def _test():
        window = _window()
        entry = _entry(tmp_path, "go-build", CATEGORY_CACHE, 2048)
        window._render_report(CleanupReport(entries=[entry]))
        window.scan = lambda: None

        with patch(
            "twinspace.gui.windows.cache_cleanup.delete_entries"
        ) as deleter, patch.object(
            cocoa_events, "confirm_with_labels", new=AsyncMock(return_value=False)
        ):
            await window._clean_selected()

        deleter.assert_not_called()

    asyncio.run(_test())


def test_clean_selected_does_nothing_without_selection():
    async def _test():
        window = _window()
        with patch(
            "twinspace.gui.windows.cache_cleanup.delete_entries"
        ) as deleter, patch.object(
            cocoa_events, "confirm_with_labels", new=AsyncMock(return_value=True)
        ):
            await window._clean_selected()
        deleter.assert_not_called()

    asyncio.run(_test())
