"""Tests for clone/source bundle version comparison."""

import plistlib
from pathlib import Path

from twinspace.core.app_version import (
    BundleVersion,
    bundle_version,
    compare_bundle_versions,
    parse_version,
    update_status,
    update_statuses,
)
from twinspace.core.state import CloneRecord


def _make_bundle(
    path: Path,
    *,
    short: str = "",
    build: str = "",
    bundle_id: str = "com.example.app",
) -> Path:
    """Create a minimal .app bundle with an Info.plist."""
    contents = path / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {"CFBundleIdentifier": bundle_id}
    if short:
        data["CFBundleShortVersionString"] = short
    if build:
        data["CFBundleVersion"] = build
    with open(contents / "Info.plist", "wb") as handle:
        plistlib.dump(data, handle)
    return path


def _record(name: str, source: Path, clone: Path) -> CloneRecord:
    return CloneRecord(
        clone_name=name,
        source_app="Example",
        source_path=str(source),
        bundle_id="com.example.app",
        strategy="hard_clone",
        dest_path=str(clone),
        data_dir=str(clone) + ".data",
        created_at="2026-10-28T00:00:00Z",
    )


def test_parse_version_keeps_numeric_parts_only():
    assert parse_version("1.2.3") == (1, 2, 3)
    assert parse_version("1.2.3-beta.4") == (1, 2, 3, 4)
    assert parse_version("") == ()
    assert parse_version("abc") == ()


def test_higher_versions_compare_numerically():
    # String comparison would rank "1.9.0" above "1.10.0"; numeric parts do not.
    assert compare_bundle_versions(
        BundleVersion("1.10.0", ""), BundleVersion("1.9.0", "")
    ) == 1
    assert compare_bundle_versions(
        BundleVersion("1.9.0", ""), BundleVersion("1.10.0", "")
    ) == -1


def test_build_number_breaks_ties_between_equal_short_versions():
    assert compare_bundle_versions(
        BundleVersion("1.0", "20"), BundleVersion("1.0", "19")
    ) == 1
    assert compare_bundle_versions(
        BundleVersion("1.0", "19"), BundleVersion("1.0", "19")
    ) == 0


def test_bundle_version_reads_the_info_plist(tmp_path):
    bundle = _make_bundle(tmp_path / "App.app", short="2.3.4", build="234")
    version = bundle_version(bundle)
    assert version is not None
    assert version.label == "2.3.4"
    assert bundle_version(tmp_path / "Missing.app") is None


def test_bundle_version_falls_back_to_the_build_number(tmp_path):
    bundle = _make_bundle(tmp_path / "App.app", build="77")
    version = bundle_version(bundle)
    assert version is not None
    assert version.label == "77"


def test_update_status_flags_a_clone_left_behind_the_source(tmp_path):
    source = _make_bundle(tmp_path / "App.app", short="2.0.0", build="200")
    clone = _make_bundle(tmp_path / "App-2.app", short="1.0.0", build="100")

    status = update_status(source, clone)
    assert status is not None
    assert status.current == "1.0.0"
    assert status.latest == "2.0.0"
    assert status.needs_update is True


def test_update_status_is_quiet_for_up_to_date_clones(tmp_path):
    source = _make_bundle(tmp_path / "App.app", short="2.0.0", build="200")
    clone = _make_bundle(tmp_path / "App-2.app", short="2.0.0", build="200")
    status = update_status(source, clone)
    assert status is not None
    assert status.needs_update is False


def test_update_status_is_none_without_version_metadata(tmp_path):
    source = _make_bundle(tmp_path / "App.app")
    clone = _make_bundle(tmp_path / "App-2.app", short="1.0")
    assert update_status(source, clone) is None


def test_update_statuses_is_keyed_by_clone_name(tmp_path):
    source = _make_bundle(tmp_path / "App.app", short="3.0")
    stale = _make_bundle(tmp_path / "App-2.app", short="2.0")
    current = _make_bundle(tmp_path / "App-3.app", short="3.0")
    unknown = tmp_path / "App-4.app"

    statuses = update_statuses(
        [
            _record("Stale", source, stale),
            _record("Current", source, current),
            _record("Missing", source, unknown),
        ]
    )

    assert statuses["Stale"].needs_update is True
    assert statuses["Current"].needs_update is False
    assert "Missing" not in statuses
