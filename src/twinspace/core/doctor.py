"""Shared environment self-check registry.

Both the GUI Doctor page (``gui/services/doctor_service.py``) and the
``twinspace doctor`` CLI command consume the same check functions so the two
surfaces can never drift apart. Every check returns a ``DoctorCheckItem`` with
a stable ``key`` (used by the GUI to pick status wording and repair actions),
a display name, details and a repair hint. Tool names (``codesign``,
``xcode-select``, ...) stay language-neutral; details and hints are localized.
"""

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from twinspace.core.config import check_directory_access, get_apps_dir, get_data_dir
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger

logger = get_logger("core.doctor")

# Cloning and backups move gigabytes around; below this the whole workflow
# should be considered unready.
MIN_FREE_BYTES = 1 * 1024**3  # 1 GiB


@dataclass
class DoctorCheckItem:
    key: str = ""
    name: str = ""
    passed: bool = False
    details: str = ""
    hint: str = ""


def _format_bytes(num: float) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def _check_codesign() -> DoctorCheckItem:
    path = shutil.which("codesign")
    if path:
        return DoctorCheckItem(key="codesign", name="codesign", passed=True, details=path)
    return DoctorCheckItem(
        key="codesign",
        name="codesign",
        passed=False,
        details=t("doctor_details_not_found"),
        hint=t("doctor_hint_xcode_select"),
    )


def _check_xcode_select() -> DoctorCheckItem:
    try:
        out = subprocess.check_output(
            ["/usr/bin/xcode-select", "-p"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        ).strip()
        if out and (Path(out).exists() or out.startswith("/")):
            return DoctorCheckItem(key="xcode-select", name="xcode-select", passed=True, details=out)
        details = out or t("doctor_details_not_found")
    except Exception:
        details = t("doctor_details_not_found")
    return DoctorCheckItem(
        key="xcode-select",
        name="xcode-select",
        passed=False,
        details=details,
        hint=t("doctor_hint_xcode_select"),
    )


def _check_plistbuddy() -> DoctorCheckItem:
    plistbuddy = "/usr/libexec/PlistBuddy"
    if shutil.which(plistbuddy) or Path(plistbuddy).exists():
        return DoctorCheckItem(key="plistbuddy", name="PlistBuddy", passed=True, details=plistbuddy)
    return DoctorCheckItem(
        key="plistbuddy",
        name="PlistBuddy",
        passed=False,
        details=t("doctor_details_plistbuddy_missing"),
        hint=t("doctor_hint_plistbuddy"),
    )


def _check_python() -> DoctorCheckItem:
    version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        return DoctorCheckItem(key="python", name="Python", passed=True, details=f"Python {version}")
    return DoctorCheckItem(
        key="python",
        name="Python",
        passed=False,
        details=t("doctor_details_python_version", version=version),
        hint=t("doctor_hint_python"),
    )


def _check_directory(key: str, label_key: str, path: Path) -> DoctorCheckItem:
    passed, detail = check_directory_access(path)
    if passed:
        return DoctorCheckItem(
            key=key,
            name=t(label_key),
            passed=True,
            details=f"{t('doctor_rw_normal')} ({path})",
        )
    return DoctorCheckItem(
        key=key,
        name=t(label_key),
        passed=False,
        details=f"{t('doctor_rw_failed')} ({detail})",
        hint=t("doctor_hint_dir_perm", path=str(path)),
    )


def _check_apps_dir() -> DoctorCheckItem:
    return _check_directory("apps_dir", "doctor_item_apps_dir", get_apps_dir())


def _check_data_dir() -> DoctorCheckItem:
    return _check_directory("data_dir", "doctor_item_data_dir", get_data_dir())


def _check_disk_space() -> DoctorCheckItem:
    """Ensure the TwinSpace data volume has room for clone/backup workloads."""
    probe = get_data_dir()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        usage = shutil.disk_usage(probe)
    except OSError as exc:
        return DoctorCheckItem(
            key="disk_space",
            name=t("doctor_item_disk_space"),
            passed=False,
            details=t("doctor_details_disk_error", error=str(exc)),
        )
    free_label = _format_bytes(usage.free)
    if usage.free < MIN_FREE_BYTES:
        return DoctorCheckItem(
            key="disk_space",
            name=t("doctor_item_disk_space"),
            passed=False,
            details=t("doctor_details_disk_low", free=free_label, path=str(probe)),
            hint=t("doctor_hint_disk_low", limit=_format_bytes(MIN_FREE_BYTES)),
        )
    return DoctorCheckItem(
        key="disk_space",
        name=t("doctor_item_disk_space"),
        passed=True,
        details=t("doctor_details_disk_ok", free=free_label, path=str(probe)),
    )


# Ordered registry consumed by both GUI and CLI; append new checks here.
CHECK_REGISTRY: list[tuple[str, Callable[[], DoctorCheckItem]]] = [
    ("codesign", _check_codesign),
    ("xcode-select", _check_xcode_select),
    ("plistbuddy", _check_plistbuddy),
    ("python", _check_python),
    ("apps_dir", _check_apps_dir),
    ("data_dir", _check_data_dir),
    ("disk_space", _check_disk_space),
]


def run_all_checks() -> list[DoctorCheckItem]:
    """Run every registered check; a crashing check degrades to a failure
    item instead of taking down the whole diagnostic pass."""
    items: list[DoctorCheckItem] = []
    for key, check in CHECK_REGISTRY:
        try:
            items.append(check())
        except Exception as exc:
            logger.error("Doctor check '%s' crashed: %s", key, exc)
            items.append(DoctorCheckItem(key=key, name=key, passed=False, details=str(exc)))
    passed = sum(1 for item in items if item.passed)
    logger.info(f"Doctor checks finished: {passed}/{len(items)} passed")
    return items


def is_xcode_select_installed() -> bool:
    """Lightweight defensive probe reused by the GUI startup check."""
    try:
        out = subprocess.check_output(
            ["/usr/bin/xcode-select", "-p"],
            stderr=subprocess.STDOUT,
            text=True,
            timeout=10,
        ).strip()
        return bool(out and (Path(out).exists() or out.startswith("/")))
    except Exception as exc:
        logger.debug(f"xcode-select -p check failed: {exc}")
        return False
