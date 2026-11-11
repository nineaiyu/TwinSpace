"""Core application prober and dynamic recipe generator."""

import plistlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from twinspace.core.app_inspector import AppInspector
from twinspace.core.argument_prober import BinaryArgumentProber
from twinspace.core.i18n import t
from twinspace.core.models import AppInfo
from twinspace.recipes.models import AppType, Recipe


@dataclass
class ProbeResult:
    app_info: AppInfo
    has_sandbox: bool
    frameworks: list[str]
    strategy: str
    reason_key: str
    recipe: Recipe
    reason_params: dict[str, Any] = field(default_factory=dict)
    raw_entitlements: dict[str, Any] = field(default_factory=dict)

    @property
    def reason(self) -> str:
        """Localized analysis note for GUI and CLI display."""
        return t(self.reason_key, **self.reason_params)


# Bundle-ID heuristics for app-type detection. Dotted keys are vendor-qualified
# and matched as plain substrings ("com.tencent.qq" also covers com.tencent.qqinput).
# Single-word keys must match a whole dot/dash/underscore-delimited segment so
# short names like "arc" cannot misclassify e.g. com.apple.archiveutility as
# Chromium; products that embed their name inside a longer segment (Slack →
# com.tinyspeck.slackmacgap) use segment-prefix matching instead.
_ELECTRON_BID_DOTTED = ("com.microsoft.vscode", "com.tencent.qq")
_ELECTRON_BID_SEGMENTS = ("electron", "vscode", "discord", "lark", "notion")
_ELECTRON_BID_PREFIXES = ("slack",)
_CHROMIUM_BID_DOTTED = ("microsoft.edge",)
_CHROMIUM_BID_SEGMENTS = ("chrome", "chromium", "arc", "brave")


class AppProber:
    """Probes local macOS .app bundles to determine optimal cloning strategies."""

    @staticmethod
    def inspect_entitlements(app_path: Path | str) -> dict[str, Any]:
        """Extract code signing entitlements as a dictionary."""
        # 1. Try modern macOS --xml flag to guarantee XML plist output
        try:
            res = subprocess.run(
                ["codesign", "-d", "--entitlements", ":-", "--xml", str(app_path)],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if res.returncode == 0 and res.stdout:
                return plistlib.loads(res.stdout)
        except Exception:
            pass

        # 2. Fallback for older macOS releases
        try:
            res = subprocess.run(
                ["codesign", "-d", "--entitlements", ":-", str(app_path)],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if res.returncode == 0 and res.stdout:
                return plistlib.loads(res.stdout)
        except Exception:
            pass
        return {}

    @staticmethod
    def detect_frameworks(app_path: Path | str) -> list[str]:
        """Detect notable frameworks and dynamic libraries inside Contents/Frameworks/ or Wrapper/*.app/Frameworks/."""
        path = Path(app_path).expanduser().resolve()
        frameworks_dir = path / "Contents" / "Frameworks"
        if not frameworks_dir.is_dir() and (path / "Wrapper").is_dir():
            for inner in (path / "Wrapper").glob("*.app"):
                fw = inner / "Frameworks"
                if fw.is_dir():
                    frameworks_dir = fw
                    break
        if not frameworks_dir.is_dir():
            return []
        return [
            p.name
            for p in frameworks_dir.iterdir()
            if p.name.endswith(".framework") or p.name.endswith(".dylib")
        ]

    @classmethod
    def detect_app_type(
        cls,
        app_path: Path | str = "",
        bundle_id: str = "",
        frameworks: list[str] | None = None,
    ) -> AppType:
        """Detect the application runtime framework / app type."""
        if frameworks is None and app_path:
            frameworks = cls.detect_frameworks(app_path)
        if frameworks is None:
            frameworks = []

        bid_lower = bundle_id.lower()
        fw_lower = [f.lower() for f in frameworks]
        bid_segments = [seg for seg in re.split(r"[.\-_]", bid_lower) if seg]

        # 1. Electron detection (Framework, bundle ID, or asar bundle structures)
        app_p = Path(app_path).expanduser().resolve() if app_path else None
        has_electron_fingerprint = False
        if app_p and app_p.is_dir():
            has_electron_fingerprint = (
                (app_p / "Contents/Frameworks/QQNT.framework").is_dir()
                or (app_p / "Contents/Frameworks/Electron Framework.framework").is_dir()
                or (app_p / "Contents/Resources/app.asar").is_file()
                or (app_p / "Contents/Resources/electron.asar").is_file()
                or (app_p / "Contents/Resources/app/application.asar").is_file()
            )

        if (
            any("electron" in f or "qqnt" in f for f in fw_lower)
            or any(k in bid_lower for k in _ELECTRON_BID_DOTTED)
            or any(k in bid_segments for k in _ELECTRON_BID_SEGMENTS)
            or any(seg.startswith(p) for p in _ELECTRON_BID_PREFIXES for seg in bid_segments)
            or has_electron_fingerprint
        ):
            return "electron"

        # 2. Chromium detection (Framework or bundle ID)
        if any("chromium" in f or "google chrome" in f for f in fw_lower) or any(
            k in bid_lower for k in _CHROMIUM_BID_DOTTED
        ) or any(k in bid_segments for k in _CHROMIUM_BID_SEGMENTS):
            return "chromium"

        # 3. Firefox / Gecko detection
        if any("xul" in f for f in fw_lower) or "firefox" in bid_lower or "torbrowser" in bid_lower:
            return "firefox"

        # 4. Standard Cocoa (AppKit / SwiftUI) vs Generic
        if app_path:
            path = Path(app_path).expanduser().resolve()
            if (path / "Contents" / "MacOS").is_dir() or (path / "Contents" / "Info.plist").is_file():
                return "cocoa"

        if bundle_id:
            return "cocoa"

        return "generic"

    @classmethod
    def analyze(
        cls,
        app_path: Path | str,
        app_info: AppInfo | None = None,
        entitlements: dict[str, Any] | None = None,
        frameworks: list[str] | None = None,
    ) -> ProbeResult:
        """Perform comprehensive inspection and determine clone strategy and recipe."""
        path = Path(app_path).expanduser().resolve()
        if app_info is None:
            app_info = AppInspector.inspect(path)
        if entitlements is None:
            entitlements = cls.inspect_entitlements(path)
        if frameworks is None:
            frameworks = cls.detect_frameworks(path)

        has_sandbox = bool(entitlements.get("com.apple.security.app-sandbox", False))
        if not has_sandbox and app_info.has_sandbox:
            has_sandbox = True

        app_type = cls.detect_app_type(path, bundle_id=app_info.bundle_id, frameworks=frameworks)

        # iOS/iPadOS app on Apple Silicon Mac detection
        if getattr(app_info, "is_ios_app", False):
            strategy = "hard_clone"
            strip_sandbox = False
            launch_args = []
            env_injection: dict[str, str] = {}
            reason_key = "probe_reason_ios_wrapper"
            reason_params: dict[str, Any] = {}
        # Chromium / Electron detection
        elif app_type in ("chromium", "electron"):
            strategy = "soft_clone"
            strip_sandbox = False
            launch_args = ["--user-data-dir={{TWINSPACE_DATA_DIR}}"]
            env_injection = {}
            reason_key = "probe_reason_web_data_dir"
            reason_params = {}
        elif app_type == "firefox":
            strategy = "soft_clone"
            strip_sandbox = False
            launch_args = ["-profile", "{{TWINSPACE_DATA_DIR}}"]
            env_injection = {}
            reason_key = "probe_reason_firefox_profile"
            reason_params = {}
        else:
            # Probe binary for custom data directory CLI argument (e.g. --data-dir, --config-dir)
            arg_probe = BinaryArgumentProber.probe_data_dir_argument(app_info.executable)
            if arg_probe.template:
                if has_sandbox:
                    strategy = "hard_clone"
                    strip_sandbox = True
                    launch_args = [arg_probe.template]
                    env_injection = {}
                    reason_key = "probe_reason_sandboxed_cli_flag"
                    reason_params = {"flag": arg_probe.flag}
                else:
                    strategy = "soft_clone"
                    strip_sandbox = False
                    launch_args = [arg_probe.template]
                    env_injection = {}
                    reason_key = "probe_reason_cli_flag"
                    reason_params = {"flag": arg_probe.flag}
            else:
                strategy = "hard_clone"
                strip_sandbox = has_sandbox
                launch_args = []
                env_injection = {
                    "HOME": "{{TWINSPACE_DATA_DIR}}/Home",
                    "TMPDIR": "{{TWINSPACE_DATA_DIR}}/Tmp",
                }
                reason_key = (
                    "probe_reason_native_sandboxed" if has_sandbox else "probe_reason_native_nonsandboxed"
                )
                reason_params = {}

        recipe = Recipe(
            bundle_id=app_info.bundle_id,
            app_name=app_info.app_name,
            strategy=strategy,  # type: ignore[arg-type]
            strip_sandbox=strip_sandbox,
            environment_injection=env_injection,
            launch_args=launch_args,
            app_type=app_type,
        )

        return ProbeResult(
            app_info=app_info,
            has_sandbox=has_sandbox,
            frameworks=frameworks,
            strategy=strategy,
            reason_key=reason_key,
            reason_params=reason_params,
            recipe=recipe,
            raw_entitlements=entitlements,
        )

    @classmethod
    def probe(cls, app_path: Path | str) -> Recipe:
        """Convenience method returning a dynamically generated Recipe."""
        return cls.analyze(app_path).recipe
