"""Cache and orphan scanning for clone data directories.

Clones keep their own `$HOME` and app data, so caches pile up per clone: Go
build caches, Playwright browsers, Electron profile caches, package stores and
temporary files. None of that is user data, but deleting the wrong directory
inside a clone HOME would be destructive — and several paths there are
symlinks into the *host* home (Host Resource Mapping), so a naive walk would
report (and delete) the host's caches once per clone.

This module therefore only ever reports whitelisted cache/temp/log locations,
resolves every candidate with ``realpath`` to prove it still lives inside the
clone's data directory, refuses symlinks, and never descends into them. The
GUI asks the user which entries to delete; :func:`delete_entries` re-validates
each path with the same rules before removing anything.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from twinspace.core.config import get_apps_dir, get_data_dir
from twinspace.core.logger import get_logger

logger = get_logger("core.cleanup")

# Entry categories (the GUI groups rows by these).
CATEGORY_CACHE = "cache"
CATEGORY_TMP = "tmp"
CATEGORY_LOGS = "logs"
CATEGORY_CRASH = "crash"
CATEGORY_PACKAGE = "package"
CATEGORY_ORPHAN = "orphan"

CATEGORY_ORDER = (
    CATEGORY_CACHE,
    CATEGORY_TMP,
    CATEGORY_LOGS,
    CATEGORY_CRASH,
    CATEGORY_PACKAGE,
    CATEGORY_ORPHAN,
)

# Electron / VS Code style user-data caches.
_ELECTRON_DIRS = {
    "Cache": CATEGORY_CACHE,
    "Code Cache": CATEGORY_CACHE,
    "GPUCache": CATEGORY_CACHE,
    "ShaderCache": CATEGORY_CACHE,
    "GrShaderCache": CATEGORY_CACHE,
    "DawnCache": CATEGORY_CACHE,
    "DawnGraphiteCache": CATEGORY_CACHE,
    "DawnWebGPUCache": CATEGORY_CACHE,
    "CachedData": CATEGORY_CACHE,
    "logs": CATEGORY_LOGS,
    "Crashpad": CATEGORY_CRASH,
}

# Chromium user-data-dir caches (browser clones store profiles under Browser/).
_CHROMIUM_DIRS = {
    "Cache": CATEGORY_CACHE,
    "Code Cache": CATEGORY_CACHE,
    "GPUCache": CATEGORY_CACHE,
    "ShaderCache": CATEGORY_CACHE,
    "GrShaderCache": CATEGORY_CACHE,
    "DawnCache": CATEGORY_CACHE,
    "DawnGraphiteCache": CATEGORY_CACHE,
    "DawnWebGPUCache": CATEGORY_CACHE,
    "GraphiteDawnCache": CATEGORY_CACHE,
    "component_crx_cache": CATEGORY_CACHE,
    "extensions_crx_cache": CATEGORY_CACHE,
    "BrowserMetrics": CATEGORY_CACHE,
    "DeferredBrowserMetrics": CATEGORY_CACHE,
    "Crashpad": CATEGORY_CRASH,
}

# Package-manager caches: safe to delete, but re-downloaded on next install.
_PACKAGE_CACHE_PATHS = (
    "Home/Library/pnpm",
    "Home/.pnpm-store",
    "Home/.npm/_cacache",
    "Home/.gradle/caches",
    "Home/.m2/repository",
    "Home/go/pkg/mod",
    "Home/.cargo/registry",
)

# Environment children that contain per-profile browser state.
_CHROMIUM_PROFILE_PREFIX = "Profile "

# Do not list micro-caches: they add noise without reclaiming anything.
MIN_ENTRY_SIZE = 1024 * 1024


@dataclass(frozen=True)
class CacheEntry:
    """One deletable directory: a cache, temp dir, log dir or orphan."""

    path: Path
    size: int
    category: str
    clone_name: str = ""
    # Validation root: the path must resolve strictly inside it.
    root: Path = field(default_factory=Path)
    # Short label for the row ("go-build", "Cache", …).
    detail: str = ""


@dataclass
class CleanupReport:
    entries: list[CacheEntry] = field(default_factory=list)
    skipped_running: list[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(entry.size for entry in self.entries)

    def by_category(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for entry in self.entries:
            totals[entry.category] = totals.get(entry.category, 0) + entry.size
        return totals


def _real(path: Path) -> Path | None:
    try:
        return Path(os.path.realpath(path))
    except OSError:
        return None


def is_inside(path: Path, root: Path) -> bool:
    """True when ``path`` resolves strictly inside ``root`` (root itself excluded).

    ``realpath`` folds symlinked ancestors, so a cache reached through a host
    resource link resolves outside the clone and is rejected.
    """
    real_path = _real(path)
    real_root = _real(root)
    if real_path is None or real_root is None:
        return False
    return real_path != real_root and real_root in real_path.parents


def dir_stats(path: Path | str) -> tuple[int, int]:
    """Recursive ``(bytes, files)`` for a directory; never follows symlinks."""
    total = 0
    files = 0
    try:
        root = Path(path)
    except Exception:
        return 0, 0
    if not root.is_dir() or root.is_symlink():
        return 0, 0
    for current, dirs, names in os.walk(root, onerror=lambda _error: None):
        dirs[:] = [
            name
            for name in dirs
            if not os.path.islink(os.path.join(current, name))
        ]
        for name in names:
            try:
                total += os.path.getsize(os.path.join(current, name))
                files += 1
            except OSError:
                continue
    return total, files


def _candidate(category: str, path: Path, base: Path) -> bool:
    """Whitelisted path that is a real directory inside the clone data dir."""
    try:
        if path.is_symlink() or not path.is_dir():
            return False
    except OSError:
        return False
    return is_inside(path, base)


def cache_candidates(data_dir: Path) -> list[tuple[str, Path]]:
    """Whitelisted cache/temp/log directories of one clone data dir."""
    found: list[tuple[str, Path]] = []

    def add(category: str, path: Path) -> None:
        if _candidate(category, path, data_dir):
            found.append((category, path))

    add(CATEGORY_TMP, data_dir / "Tmp")

    # Electron user-data caches (VS Code forks keep them under UserData/).
    user_data = data_dir / "UserData"
    for name, category in _ELECTRON_DIRS.items():
        add(category, user_data / name)

    # Chromium browser clones: cache dirs at the profile root and one level in.
    browser = data_dir / "Browser"
    for name, category in _CHROMIUM_DIRS.items():
        add(category, browser / name)
    if browser.is_dir() and not browser.is_symlink():
        try:
            profiles = list(browser.iterdir())
        except OSError:
            profiles = []
        for profile in profiles:
            if profile.name != "Default" and not profile.name.startswith(
                _CHROMIUM_PROFILE_PREFIX
            ):
                continue
            for name, category in _CHROMIUM_DIRS.items():
                add(category, profile / name)

    # Per-clone HOME caches. Each child is listed separately so one huge cache
    # (go-build can be tens of GB) does not hide the rest behind one row.
    home_caches = data_dir / "Home" / "Library" / "Caches"
    if home_caches.is_dir() and not home_caches.is_symlink():
        try:
            children = list(home_caches.iterdir())
        except OSError:
            children = []
        for child in children:
            add(CATEGORY_CACHE, child)
    dev_caches = data_dir / "Home" / ".cache"
    if dev_caches.is_dir() and not dev_caches.is_symlink():
        try:
            children = list(dev_caches.iterdir())
        except OSError:
            children = []
        for child in children:
            add(CATEGORY_CACHE, child)

    add(CATEGORY_LOGS, data_dir / "Home" / "Library" / "Logs")
    add(
        CATEGORY_CRASH,
        data_dir / "Home" / "Library" / "Application Support" / "CrashReporter",
    )
    for relative in _PACKAGE_CACHE_PATHS:
        add(CATEGORY_PACKAGE, data_dir / relative)

    return found


def _orphans(
    referenced_data: set[Path],
    referenced_apps: set[Path],
    data_root: Path,
    apps_root: Path,
    min_size: int = MIN_ENTRY_SIZE,
) -> list[CacheEntry]:
    """Data directories and app bundles no clone record points at."""
    entries: list[CacheEntry] = []
    environments = data_root / "Environments"
    if environments.is_dir():
        try:
            env_dirs = [path for path in environments.iterdir() if path.is_dir()]
        except OSError:
            env_dirs = []
        for env_dir in env_dirs:
            try:
                children = [path for path in env_dir.iterdir() if path.is_dir()]
            except OSError:
                continue
            for child in children:
                if child.is_symlink():
                    continue
                real = _real(child)
                if real is None or real in referenced_data:
                    continue
                size, _files = dir_stats(child)
                if size >= min_size:
                    entries.append(
                        CacheEntry(
                            path=child,
                            size=size,
                            category=CATEGORY_ORPHAN,
                            root=data_root,
                            detail=child.name,
                        )
                    )
    if apps_root.is_dir():
        try:
            bundles = [path for path in apps_root.iterdir() if path.suffix == ".app"]
        except OSError:
            bundles = []
        for bundle in bundles:
            if bundle.is_symlink():
                continue
            real = _real(bundle)
            if real is None or real in referenced_apps:
                continue
            size, _files = dir_stats(bundle)
            if size >= min_size:
                entries.append(
                    CacheEntry(
                        path=bundle,
                        size=size,
                        category=CATEGORY_ORPHAN,
                        root=apps_root,
                        detail=bundle.name,
                    )
                )
    return entries


def scan_cleanup(
    records: Iterable[Any],
    *,
    data_root: Path | None = None,
    apps_root: Path | None = None,
    skip_clones: Iterable[str] = (),
    include_orphans: bool = True,
    min_size: int = MIN_ENTRY_SIZE,
) -> CleanupReport:
    """List deletable directories for the given clone records.

    ``skip_clones`` (normally the running ones) are excluded because pulling
    cache files out from under a live application can break it.
    """
    records = list(records)
    skip = set(skip_clones)
    report = CleanupReport()
    data_root = Path(data_root) if data_root is not None else get_data_dir()
    apps_root = Path(apps_root) if apps_root is not None else get_apps_dir()

    referenced_data: set[Path] = set()
    referenced_apps: set[Path] = set()
    for record in records:
        raw_data = str(getattr(record, "data_dir", "") or "")
        raw_app = str(getattr(record, "dest_path", "") or "")
        if raw_data:
            real = _real(Path(raw_data))
            if real is not None:
                referenced_data.add(real)
        if raw_app:
            real = _real(Path(raw_app))
            if real is not None:
                referenced_apps.add(real)

    seen: set[Path] = set()
    for record in records:
        clone_name = str(getattr(record, "clone_name", "") or "")
        if clone_name in skip:
            report.skipped_running.append(clone_name)
            continue
        raw_dir = str(getattr(record, "data_dir", "") or "")
        if not raw_dir:
            continue
        data_dir = Path(raw_dir)
        if data_dir.is_symlink() or not data_dir.is_dir():
            continue
        for category, path in cache_candidates(data_dir):
            real = _real(path)
            if real is None or real in seen:
                continue
            size, _files = dir_stats(path)
            if size < min_size:
                continue
            seen.add(real)
            report.entries.append(
                CacheEntry(
                    path=path,
                    size=size,
                    category=category,
                    clone_name=clone_name,
                    root=data_dir,
                    detail=path.name,
                )
            )

    # Orphans are attributed to no clone and validated against the data/apps root.
    if include_orphans:
        for entry in _orphans(
            referenced_data,
            referenced_apps,
            data_root,
            apps_root,
            min_size=min_size,
        ):
            real = _real(entry.path)
            if real is None or real in seen:
                continue
            seen.add(real)
            report.entries.append(entry)

    report.entries.sort(key=lambda entry: (entry.category, -entry.size))
    return report


def delete_entries(entries: Iterable[CacheEntry]) -> tuple[int, list[str]]:
    """Delete the selected entries, re-validating every path first.

    Returns ``(freed_bytes, errors)``. A path is only removed when it still
    resolves inside its validation root and is not a symlink — exactly the
    rules the scan applied, so a path swapped between scan and delete cannot
    escape the clone data directory.
    """
    freed = 0
    errors: list[str] = []
    for entry in entries:
        path = entry.path
        try:
            if path.is_symlink():
                errors.append(f"{path}: refused (symlink)")
                continue
            if not path.exists():
                continue
            if not is_inside(path, entry.root):
                errors.append(f"{path}: refused (outside {entry.root})")
                continue
            size = entry.size
            shutil.rmtree(path)
            freed += size
        except Exception as exc:  # pragma: no cover - filesystem specific
            logger.warning("Could not remove cache %s: %s", path, exc)
            errors.append(f"{path}: {exc}")
    return freed, errors
