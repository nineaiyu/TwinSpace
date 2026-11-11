"""Unit tests for the `doctor` CLI command (shared registry based)."""

from collections import namedtuple
from unittest.mock import patch

from click.testing import CliRunner

from twinspace.cli.main import cli
from twinspace.core.doctor import (
    CHECK_REGISTRY,
    MIN_FREE_BYTES,
    DoctorCheckItem,
    _check_codesign,
    _check_disk_space,
    _format_bytes,
    is_xcode_select_installed,
    run_all_checks,
)


def _item(key: str, name: str, passed: bool, details: str, hint: str = "") -> DoctorCheckItem:
    return DoctorCheckItem(key=key, name=name, passed=passed, details=details, hint=hint)


def test_doctor_all_passed():
    runner = CliRunner()
    items = [
        _item("codesign", "codesign", True, "/usr/bin/codesign"),
        _item("xcode-select", "xcode-select", True, "/Applications/Xcode.app/Contents/Developer"),
        _item("plistbuddy", "PlistBuddy", True, "/usr/libexec/PlistBuddy"),
        _item("apps_dir", "Application Directory Permissions", True, "Read/Write OK (/path)"),
    ]
    with patch("twinspace.cli.cmd_doctor.run_all_checks", return_value=items):
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 0
        assert "Running environment checks:" in result.output
        assert "✓ codesign" in result.output
        assert "/usr/bin/codesign" in result.output
        assert "✓ xcode-select" in result.output
        assert "✓ PlistBuddy" in result.output
        assert "✗" not in result.output


def test_doctor_failure_exits_nonzero_and_prints_hint():
    runner = CliRunner()
    items = [
        _item("codesign", "codesign", True, "/usr/bin/codesign"),
        _item(
            "xcode-select",
            "xcode-select",
            False,
            "Not found",
            hint="Click 'Install Xcode Command Line Tools' above or run: xcode-select --install",
        ),
    ]
    with patch("twinspace.cli.cmd_doctor.run_all_checks", return_value=items):
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 1
        assert "✗ xcode-select" in result.output
        assert "↳" in result.output
        # Rich wraps long hint lines at 80 columns; assert on unwrapped parts
        assert "xcode-select" in result.output
        assert "--install" in result.output


def test_doctor_dir_permission_failed():
    runner = CliRunner()
    items = [
        _item("codesign", "codesign", True, "/usr/bin/codesign"),
        _item("apps_dir", "Apps Directory", False, "Permission denied mock"),
    ]
    with patch("twinspace.cli.cmd_doctor.run_all_checks", return_value=items):
        result = runner.invoke(cli, ["doctor"])
        assert result.exit_code == 1
        assert "✗" in result.output
        assert "Permission denied mock" in result.output


def test_doctor_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "doctor" in result.output.lower() or "环境检测" in result.output


# ── Shared registry unit tests (core.doctor) ──────────────────────────────── #


def test_format_bytes():
    assert _format_bytes(512) == "512 B"
    assert _format_bytes(1024) == "1.0 KB"
    assert _format_bytes(2 * 1024**3) == "2.0 GB"


def test_check_codesign_missing():
    with patch("twinspace.core.doctor.shutil.which", return_value=None):
        item = _check_codesign()
    assert item.key == "codesign"
    assert item.passed is False
    assert item.details == "Not found"
    assert "xcode-select --install" in item.hint


def test_check_disk_space_low(tmp_path):
    usage = namedtuple("usage", "total used free")
    fake = usage(total=100 * 1024**3, used=99 * 1024**3, free=100 * 1024**2)
    with patch("twinspace.core.doctor.get_data_dir", return_value=tmp_path), \
         patch("twinspace.core.doctor.shutil.disk_usage", return_value=fake):
        item = _check_disk_space()
    assert item.key == "disk_space"
    assert item.passed is False
    assert "MB" in item.details
    assert str(MIN_FREE_BYTES) not in item.details


def test_check_disk_space_ok(tmp_path):
    usage = namedtuple("usage", "total used free")
    fake = usage(total=100 * 1024**3, used=10 * 1024**3, free=90 * 1024**3)
    with patch("twinspace.core.doctor.get_data_dir", return_value=tmp_path), \
         patch("twinspace.core.doctor.shutil.disk_usage", return_value=fake):
        item = _check_disk_space()
    assert item.passed is True
    assert "GB" in item.details


def test_check_disk_space_io_error(tmp_path):
    with patch("twinspace.core.doctor.get_data_dir", return_value=tmp_path), \
         patch("twinspace.core.doctor.shutil.disk_usage", side_effect=OSError("boom")):
        item = _check_disk_space()
    assert item.passed is False
    assert "boom" in item.details


def test_run_all_checks_crash_degrades_to_failure_item():
    def boom():
        raise RuntimeError("boom")

    with patch("twinspace.core.doctor.CHECK_REGISTRY", [("boom", boom)]):
        items = run_all_checks()
    assert len(items) == 1
    assert items[0].key == "boom"
    assert items[0].passed is False
    assert "boom" in items[0].details


def test_is_xcode_select_installed(tmp_path):
    with patch("twinspace.core.doctor.subprocess.check_output", return_value=f"{tmp_path}\n"):
        assert is_xcode_select_installed() is True
    with patch("twinspace.core.doctor.subprocess.check_output", side_effect=OSError("gone")):
        assert is_xcode_select_installed() is False


def test_registry_has_seven_checks():
    keys = [key for key, _ in CHECK_REGISTRY]
    assert keys == ["codesign", "xcode-select", "plistbuddy", "python", "apps_dir", "data_dir", "disk_space"]
