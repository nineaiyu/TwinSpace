"""Tests for the storage cleanup scanner and deletion guards."""

import os
from pathlib import Path

from twinspace.core.cleanup import (
    CATEGORY_CACHE,
    CATEGORY_CRASH,
    CATEGORY_LOGS,
    CATEGORY_ORPHAN,
    CATEGORY_PACKAGE,
    CATEGORY_TMP,
    CacheEntry,
    delete_entries,
    is_inside,
    scan_cleanup,
)
from twinspace.core.state import CloneRecord


def _write(path: Path, size: int = 4096) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def _record(tmp_path: Path, name: str, data_dir: Path) -> CloneRecord:
    return CloneRecord(
        clone_name=name,
        source_app="App",
        source_path="/Applications/App.app",
        bundle_id="com.example.app",
        strategy="hard_clone",
        dest_path=str(tmp_path / "Apps" / f"{name}.app"),
        data_dir=str(data_dir),
        created_at="2026-11-01T00:00:00",
    )


def _layout(tmp_path: Path) -> tuple[Path, Path, CloneRecord]:
    """Data root with one clone's caches, plus an unrelated user file."""
    data_root = tmp_path / "Data"
    clone_dir = data_root / "Environments" / "env1" / "App-b1"
    _write(clone_dir / "Tmp" / "scratch.bin")
    _write(clone_dir / "UserData" / "Cache" / "data_0")
    _write(clone_dir / "UserData" / "Code Cache" / "js" / "index")
    _write(clone_dir / "UserData" / "logs" / "main.log")
    _write(clone_dir / "UserData" / "Crashpad" / "report.dmp")
    _write(clone_dir / "Home" / "Library" / "Caches" / "go-build" / "ab" / "cache")
    _write(clone_dir / "Home" / ".cache" / "pip" / "wheel")
    # Real user data: must never be listed.
    _write(clone_dir / "Home" / "Documents" / "notes.txt")
    _write(clone_dir / "UserData" / "User" / "settings.json")
    return data_root, clone_dir, _record(tmp_path, "App-b1", clone_dir)


def test_scan_lists_only_whitelisted_caches(tmp_path):
    data_root, clone_dir, record = _layout(tmp_path)

    report = scan_cleanup(
        [record],
        data_root=data_root,
        apps_root=tmp_path / "Apps",
        include_orphans=False,
        min_size=1,
    )

    categories = {entry.category for entry in report.entries}
    assert categories == {CATEGORY_TMP, CATEGORY_CACHE, CATEGORY_LOGS, CATEGORY_CRASH}
    names = {entry.path.name for entry in report.entries}
    assert "go-build" in names
    assert "pip" in names
    assert "notes.txt" not in names
    assert all(entry.clone_name == "App-b1" for entry in report.entries)
    assert all(entry.size > 0 for entry in report.entries)


def test_scan_skips_symlinks_into_the_host_home(tmp_path):
    data_root, clone_dir, record = _layout(tmp_path)
    host = tmp_path / "host"
    _write(host / "go" / "pkg" / "mod" / "big.zip", 8192)
    _write(host / "Library" / "Caches" / "host-cache" / "blob", 8192)

    # Host Resource Mapping links host caches into the clone HOME.
    os.symlink(host / "go", clone_dir / "Home" / "go")
    os.symlink(
        host / "Library" / "Caches" / "host-cache",
        clone_dir / "Home" / "Library" / "Caches" / "host-cache",
    )

    report = scan_cleanup(
        [record],
        data_root=data_root,
        apps_root=tmp_path / "Apps",
        include_orphans=False,
        min_size=1,
    )

    paths = [str(entry.path) for entry in report.entries]
    assert not any("host-cache" in path for path in paths)
    assert not any("pkg/mod" in path for path in paths)
    # The host files survived the scan untouched.
    assert (host / "go" / "pkg" / "mod" / "big.zip").exists()


def test_scan_skips_running_clones(tmp_path):
    data_root, _clone_dir, record = _layout(tmp_path)

    report = scan_cleanup(
        [record],
        data_root=data_root,
        apps_root=tmp_path / "Apps",
        skip_clones={"App-b1"},
        include_orphans=False,
        min_size=1,
    )

    assert report.entries == []
    assert report.skipped_running == ["App-b1"]


def test_scan_finds_orphan_data_and_bundles(tmp_path):
    data_root, clone_dir, record = _layout(tmp_path)
    orphan_data = data_root / "Environments" / "env1" / "Gone-b1"
    _write(orphan_data / "UserData" / "leveldb" / "000001.log", 4096)
    orphan_app = tmp_path / "Apps" / "Gone-b1.app"
    _write(orphan_app / "Contents" / "Info.plist", 4096)
    _write(tmp_path / "Apps" / "App-b1.app" / "Contents" / "Info.plist", 100)

    report = scan_cleanup(
        [record],
        data_root=data_root,
        apps_root=tmp_path / "Apps",
        min_size=1,
    )

    orphans = [entry for entry in report.entries if entry.category == CATEGORY_ORPHAN]
    assert {entry.path.name for entry in orphans} == {"Gone-b1", "Gone-b1.app"}
    assert all(entry.clone_name == "" for entry in orphans)
    # Referenced clone data is not an orphan.
    assert all(Path(entry.path) != clone_dir for entry in orphans)


def test_scan_reports_package_caches_separately(tmp_path):
    data_root, clone_dir, record = _layout(tmp_path)
    _write(clone_dir / "Home" / "Library" / "pnpm" / "store" / "pkg", 4096)

    report = scan_cleanup(
        [record],
        data_root=data_root,
        apps_root=tmp_path / "Apps",
        include_orphans=False,
        min_size=1,
    )

    package = [entry for entry in report.entries if entry.category == CATEGORY_PACKAGE]
    assert [entry.path.name for entry in package] == ["pnpm"]


def test_delete_entries_frees_and_removes_only_selected(tmp_path):
    data_root, clone_dir, record = _layout(tmp_path)
    report = scan_cleanup(
        [record],
        data_root=data_root,
        apps_root=tmp_path / "Apps",
        include_orphans=False,
        min_size=1,
    )
    cache_entries = [
        entry for entry in report.entries if entry.path.name == "go-build"
    ]

    freed, errors = delete_entries(cache_entries)

    assert errors == []
    assert freed == cache_entries[0].size
    assert not (clone_dir / "Home" / "Library" / "Caches" / "go-build").exists()
    # Everything else is untouched, including user data.
    assert (clone_dir / "Home" / "Documents" / "notes.txt").exists()
    assert (clone_dir / "Tmp").exists()


def test_delete_refuses_symlink_and_outside_root(tmp_path):
    data_root, clone_dir, record = _layout(tmp_path)
    host_target = tmp_path / "host" / "cache"
    _write(host_target / "blob", 4096)
    link = clone_dir / "Home" / "Library" / "Caches" / "linked"
    os.symlink(host_target, link)
    outside = tmp_path / "outside"
    _write(outside / "data", 4096)

    freed, errors = delete_entries(
        [
            CacheEntry(path=link, size=4096, category=CATEGORY_CACHE, root=clone_dir),
            CacheEntry(
                path=outside, size=4096, category=CATEGORY_ORPHAN, root=data_root
            ),
        ]
    )

    assert freed == 0
    assert len(errors) == 2
    assert host_target.exists()
    assert outside.exists()


def test_is_inside_rejects_the_root_and_symlinked_ancestors(tmp_path):
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    assert is_inside(child, root) is True
    assert is_inside(root, root) is False

    host = tmp_path / "host"
    host.mkdir()
    os.symlink(host, root / "link")
    assert is_inside(root / "link", root) is False
