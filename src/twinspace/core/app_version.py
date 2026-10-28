"""Bundle version detection used to flag clones that lag behind their source app.

A clone is a full copy of an application bundle, so the version stored inside the
clone's ``Info.plist`` is frozen at build time. Once the user updates the original
app in ``/Applications`` the clone keeps the older version; comparing the two
plists lets the GUI show a "new version available" badge without re-cloning.

Only the plists are read (no codesign, no subprocess), so a refresh that checks a
few dozen clones stays cheap; results are cached per file mtime.
"""

from __future__ import annotations

import plistlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from twinspace.core.logger import get_logger

logger = get_logger("core.app_version")

# (plist path, mtime_ns) -> (CFBundleShortVersionString, CFBundleVersion)
_PLIST_CACHE: dict[tuple[str, int], tuple[str, str]] = {}
_CACHE_LIMIT = 512


@dataclass(frozen=True)
class BundleVersion:
    """The two version fields of one app bundle."""

    short: str = ""
    build: str = ""

    @property
    def label(self) -> str:
        """Human readable version, falling back to the build number."""
        return self.short or self.build


@dataclass(frozen=True)
class AppUpdate:
    """Version comparison between a clone and the app it was cloned from."""

    current: str
    latest: str
    needs_update: bool


def parse_version(value: str) -> tuple[int, ...]:
    """Split a dotted version into comparable integers ("1.2.3b" -> (1, 2, 3))."""
    parts = re.split(r"[^0-9]+", str(value or ""))
    return tuple(int(part) for part in parts if part)


def _compare_number_sequences(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    length = max(len(left), len(right))
    left_padded = left + (0,) * (length - len(left))
    right_padded = right + (0,) * (length - len(right))
    if left_padded > right_padded:
        return 1
    if left_padded < right_padded:
        return -1
    return 0


def compare_bundle_versions(left: BundleVersion, right: BundleVersion) -> int:
    """Return 1 when ``left`` is newer than ``right``, -1 when older, 0 when equal.

    ``CFBundleShortVersionString`` decides first (that is what users see); the
    build number breaks ties so a build-only bump still counts as an update.
    """
    result = _compare_number_sequences(parse_version(left.short), parse_version(right.short))
    if result:
        return result
    return _compare_number_sequences(parse_version(left.build), parse_version(right.build))


def _candidate_plists(app_path: Path) -> list[Path]:
    """Info.plist locations used by standard, iOS-on-Mac and wrapper bundles."""
    candidates = [
        app_path / "Contents" / "Info.plist",
        app_path / "Info.plist",
        app_path / "WrappedBundle" / "Info.plist",
    ]
    wrapper = app_path / "Wrapper"
    try:
        if wrapper.is_dir():
            candidates.extend(sorted(wrapper.glob("*.app/Info.plist")))
    except OSError:  # pragma: no cover - unreadable directory
        pass
    return candidates


def _read_versions(plist_path: Path) -> tuple[str, str]:
    try:
        with open(plist_path, "rb") as handle:
            data = plistlib.load(handle)
    except Exception:  # pragma: no cover - malformed or unreadable plist
        return ("", "")
    if not isinstance(data, dict):
        return ("", "")
    short = str(data.get("CFBundleShortVersionString") or "").strip()
    build = str(data.get("CFBundleVersion") or "").strip()
    return (short, build)


def bundle_version(app_path: str | Path) -> BundleVersion | None:
    """Read the version of an app bundle, or None when it cannot be determined."""
    if not app_path:
        return None
    path = Path(str(app_path)).expanduser()
    for plist_path in _candidate_plists(path):
        try:
            stat = plist_path.stat()
        except OSError:
            continue
        key = (str(plist_path), stat.st_mtime_ns)
        versions = _PLIST_CACHE.get(key)
        if versions is None:
            versions = _read_versions(plist_path)
            if len(_PLIST_CACHE) >= _CACHE_LIMIT:
                _PLIST_CACHE.clear()
            _PLIST_CACHE[key] = versions
        short, build = versions
        if short or build:
            return BundleVersion(short=short, build=build)
    return None


def update_status(source_path: str | Path, clone_path: str | Path) -> AppUpdate | None:
    """Compare the clone bundle against its source app; None when unknown."""
    current = bundle_version(clone_path)
    if current is None:
        return None
    latest = bundle_version(source_path)
    if latest is None:
        return None
    return AppUpdate(
        current=current.label,
        latest=latest.label,
        needs_update=compare_bundle_versions(latest, current) > 0,
    )


def update_statuses(records: Iterable[Any]) -> dict[str, AppUpdate]:
    """Version status for every record that has one, keyed by clone name."""
    statuses: dict[str, AppUpdate] = {}
    for record in records:
        clone_name = getattr(record, "clone_name", "")
        if not clone_name:
            continue
        try:
            status = update_status(
                getattr(record, "source_path", ""),
                getattr(record, "dest_path", ""),
            )
        except Exception:  # pragma: no cover - defensive, one bad bundle only
            logger.debug("Version check failed for %s", clone_name, exc_info=True)
            continue
        if status is not None:
            statuses[clone_name] = status
    return statuses
