"""Static application definitions used by environment management."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from twinspace.core.state import CloneRecord, is_any_clone_running


@dataclass(frozen=True)
class EnvironmentApp:
    key: str
    label: str
    bundle_ids: tuple[str, ...]
    default_path: Path
    clone_prefix: str
    # International builds ship alongside the CN ones; they stay available in the
    # create dialog but are not ticked by default so existing setups are unchanged.
    default_selected: bool = True

    @property
    def installed_path(self) -> Path | None:
        for candidate in (self.default_path, Path.home() / "Applications" / self.default_path.name):
            if candidate.is_dir():
                return candidate
        return None

    @property
    def installed(self) -> bool:
        return self.installed_path is not None


@dataclass
class EnvironmentInfo:
    name: str
    env_dir: Path
    records: list[CloneRecord]

    @property
    def running(self) -> bool:
        return is_any_clone_running(record.dest_path for record in self.records)

    @property
    def app_keys(self) -> set[str]:
        keys: set[str] = set()
        for record in self.records:
            key = app_key_for_bundle_id(record.bundle_id)
            if key:
                keys.add(key)
        return keys


KNOWN_APPS: tuple[EnvironmentApp, ...] = (
    EnvironmentApp(
        "chrome",
        "Google Chrome",
        ("com.google.Chrome",),
        Path("/Applications/Google Chrome.app"),
        "Chrome",
    ),
    EnvironmentApp(
        "zcode",
        "ZCode",
        ("dev.zcode.app",),
        Path("/Applications/ZCode.app"),
        "ZCode",
    ),
    EnvironmentApp(
        "workbuddy",
        "WorkBuddy",
        ("com.tencent.workbuddy.mac",),
        Path("/Applications/WorkBuddy.app"),
        "WorkBuddy",
    ),
    EnvironmentApp(
        "workbuddy_ai",
        "WorkBuddy AI",
        ("com.workbuddy.workbuddy-ai",),
        Path("/Applications/WorkBuddy AI.app"),
        "WorkBuddyAI",
        default_selected=False,
    ),
    EnvironmentApp(
        "codebuddy",
        "CodeBuddy CN",
        ("com.tencent.codebuddycn",),
        Path("/Applications/CodeBuddy CN.app"),
        "CodeBuddy",
    ),
    EnvironmentApp(
        "codebuddy_ai",
        "CodeBuddy AI",
        ("com.tencent.codebuddy",),
        Path("/Applications/CodeBuddy.app"),
        "CodeBuddyAI",
        default_selected=False,
    ),
    EnvironmentApp(
        "qoder",
        "Qoder CN",
        ("com.qodercn.app",),
        Path("/Applications/Qoder CN.app"),
        "Qoder",
    ),
    EnvironmentApp(
        "trae",
        "Trae CN",
        ("cn.trae.app",),
        Path("/Applications/Trae CN.app"),
        "Trae",
    ),
)


def app_key_for_bundle_id(bundle_id: str) -> str:
    for app in KNOWN_APPS:
        if bundle_id in app.bundle_ids:
            return app.key
    return ""


def app_for_key(key: str) -> EnvironmentApp | None:
    for app in KNOWN_APPS:
        if app.key == key:
            return app
    return None
