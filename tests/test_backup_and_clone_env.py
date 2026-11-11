"""Tests for backup listing/pruning and environment-copy helpers."""

from pathlib import Path

from twinspace.core.environments.backup import list_backups, prune_backups
from twinspace.core.environments.manager import _derived_clone_name


def _make_backup(root: Path, env: str, stamp: str, size: int = 10) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{env}-{stamp}.tar.gz"
    path.write_bytes(b"x" * size)
    return path


def test_list_backups_filters_and_orders(tmp_path):
    backups = tmp_path / "Backups"
    _make_backup(backups, "b2", "20260101-000000")
    _make_backup(backups, "b2", "20260102-000000")
    _make_backup(backups, "other", "20260103-000000")
    # Non-backup files are ignored entirely.
    (backups / "b2-notes.txt").write_text("keep me")

    items = list_backups("b2", base_dir=tmp_path)
    assert [item["name"] for item in items] == [
        "b2-20260102-000000.tar.gz",
        "b2-20260101-000000.tar.gz",
    ]
    assert all(item["environment"] == "b2" for item in items)

    everything = list_backups(base_dir=tmp_path)
    assert {item["environment"] for item in everything} == {"b2", "other"}


def test_prune_backups_keeps_newest(tmp_path):
    backups = tmp_path / "Backups"
    for stamp in (
        "20260101-000000",
        "20260102-000000",
        "20260103-000000",
        "20260104-000000",
    ):
        _make_backup(backups, "b2", stamp)
    _make_backup(backups, "other", "20260105-000000")

    removed = prune_backups("b2", keep=2, base_dir=tmp_path)
    assert len(removed) == 2
    remaining = {item["name"] for item in list_backups("b2", base_dir=tmp_path)}
    assert remaining == {"b2-20260103-000000.tar.gz", "b2-20260104-000000.tar.gz"}
    # Other environments are never touched by a per-environment prune.
    assert (backups / "other-20260105-000000.tar.gz").exists()


def test_prune_backups_never_goes_below_keep(tmp_path):
    backups = tmp_path / "Backups"
    _make_backup(backups, "b2", "20260101-000000")
    assert prune_backups("b2", keep=3, base_dir=tmp_path) == []
    assert len(list_backups("b2", base_dir=tmp_path)) == 1


def test_derived_clone_name():
    assert _derived_clone_name("Chrome-b2", "b2", "b3") == "Chrome-b3"
    # Suffix matching ignores case but preserves the original casing otherwise.
    assert _derived_clone_name("chrome-B2", "b2", "b3") == "chrome-b3"
    # User-renamed clones gain the new environment as an extra suffix.
    assert _derived_clone_name("MyCustomClone", "b2", "b3") == "MyCustomClone-b3"
