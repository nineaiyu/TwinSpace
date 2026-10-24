"""Update Service for checking and installing TwinSpace updates from GitHub Releases."""

import asyncio
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests

from twinspace import __version__
from twinspace.core.logger import get_logger

logger = get_logger("gui.update_service")


@dataclass
class UpdateInfo:
    version: str
    notes: str
    pub_date: str
    checksum: str
    download_url: str


def _parse_version(v: str) -> tuple[int, ...]:
    cleaned = v.strip().lstrip("v")
    # "1.2.3-rc1" -> (1, 2, 3, -1): sorts below the final "1.2.3" but above
    # any earlier release, instead of the suffix silently collapsing to 0.
    prerelease = -1 if "-" in cleaned else 0
    cleaned = cleaned.split("-", 1)[0]
    parts = []
    for x in cleaned.split("."):
        try:
            parts.append(int(x))
        except ValueError:
            parts.append(0)
    if len(parts) < 3:
        parts += [0] * (3 - len(parts))
    parts.append(prerelease)
    return tuple(parts)


def _get_configured_proxies() -> dict[str, str] | None:
    """Retrieve user-configured proxy settings from application preferences."""
    try:
        from twinspace.core.config import get_config_value

        cfg_proxy = get_config_value("default_proxy", {})
        if cfg_proxy.get("enabled"):
            ptype = cfg_proxy.get("type", "http")
            host = cfg_proxy.get("host", "127.0.0.1")
            port = cfg_proxy.get("port", 7890)
            user = cfg_proxy.get("username", "")

            pwd = None
            if user:
                from twinspace.core.keychain import get_default_proxy_password

                pwd = get_default_proxy_password()

            auth = f"{user}:{pwd}@" if user and pwd else (f"{user}@" if user else "")
            proxy_url = f"{ptype}://{auth}{host}:{port}"
            return {"http": proxy_url, "https": proxy_url}
    except (KeyError, ValueError, OSError, TypeError) as e:
        logger.debug(f"Could not load configured proxy: {e}")
    return None


class UpdateService:
    LATEST_JSON_URL = os.environ.get(
        "TWINSPACE_UPDATE_URL",
        "https://github.com/nineaiyu/TwinSpace/releases/latest/download/latest.json",
    )

    def _get_platform_key(self) -> str:
        machine = platform.machine().lower()
        if machine in ("arm64", "aarch64"):
            return "darwin-aarch64"
        return "darwin-x86_64"

    def _get_arch_suffix(self) -> str:
        machine = platform.machine().lower()
        return "arm64" if machine in ("arm64", "aarch64") else "x86_64"

    def _get_target_app_path(self) -> Path:
        """Resolve the currently running .app bundle or fallback to /Applications/TwinSpace.app."""
        p = Path(sys.executable).resolve()
        for parent in p.parents:
            if parent.suffix == ".app":
                return parent
        return Path("/Applications/TwinSpace.app")

    def _get_download_path(self, version: str) -> Path:
        downloads_dir = Path.home() / "Downloads"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        arch = self._get_arch_suffix()
        return downloads_dir / f"TwinSpace-{version}-{arch}.dmg"

    async def check_for_updates(self) -> UpdateInfo | None:
        """Fetch latest.json and return UpdateInfo if remote is strictly newer than current version."""
        loop = asyncio.get_running_loop()

        def _fetch():
            proxies = _get_configured_proxies()
            logger.info(f"Checking for updates from {self.LATEST_JSON_URL} (proxy={bool(proxies)})...")
            try:
                resp = requests.get(self.LATEST_JSON_URL, timeout=10, proxies=proxies)
                resp.raise_for_status()
            except requests.HTTPError as exc:
                # Re-raise showing our canonical URL, not the redirect target GitHub returns
                raise requests.HTTPError(
                    f"{exc.response.status_code} {exc.response.reason} — {self.LATEST_JSON_URL}",
                    response=exc.response,
                ) from exc
            data = resp.json()

            remote_ver_str = data.get("version", "").strip()
            remote_ver = _parse_version(remote_ver_str)
            curr_ver = _parse_version(__version__)

            logger.info(f"Version check: current={__version__} ({curr_ver}), remote={remote_ver_str} ({remote_ver})")
            if remote_ver > curr_ver:
                platforms = data.get("platforms", {})
                plat_key = self._get_platform_key()
                platform_info = platforms.get(plat_key)
                if not platform_info:
                    # Never fall back to another architecture's package: an Intel
                    # host silently downloading an arm64 DMG would install an app
                    # that cannot launch.
                    raise RuntimeError(f"No update package published for {plat_key}")

                download_url = platform_info.get("url", "")
                checksum = platform_info.get("checksum", "").strip()

                if not download_url or not checksum:
                    raise ValueError(f"Missing download URL or checksum for platform '{plat_key}'")

                return UpdateInfo(
                    version=remote_ver_str,
                    notes=data.get("notes", ""),
                    pub_date=data.get("pub_date", ""),
                    checksum=checksum,
                    download_url=download_url,
                )
            return None

        return await loop.run_in_executor(None, _fetch)

    async def download_and_install(
        self,
        info: UpdateInfo,
        on_progress: Callable[[int, int], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        """Download DMG, verify checksum, mount, ditto install to target .app, detach, and cleanup."""
        loop = asyncio.get_running_loop()

        def _worker():
            dmg_path = self._get_download_path(info.version)
            target_app_path = self._get_target_app_path()
            proxies = _get_configured_proxies()
            logger.info(f"Downloading update from {info.download_url} to {dmg_path} (target={target_app_path})...")

            # 1. Streaming Download
            if on_status:
                on_status("downloading")

            try:
                with requests.get(info.download_url, stream=True, timeout=30, proxies=proxies) as r:
                    r.raise_for_status()
                    total_size = int(r.headers.get("content-length", 0))
                    downloaded = 0

                    with open(dmg_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if on_progress:
                                    on_progress(downloaded, total_size)

                # 2. SHA256 Verification
                if on_status:
                    on_status("verifying")
                logger.info("Verifying SHA256 checksum...")
                hasher = hashlib.sha256()
                with open(dmg_path, "rb") as f:
                    while True:
                        block = f.read(65536)
                        if not block:
                            break
                        hasher.update(block)
                computed_sha = hasher.hexdigest()

                if computed_sha.lower() != info.checksum.lower():
                    logger.error(f"SHA256 mismatch! Expected {info.checksum}, got {computed_sha}")
                    if dmg_path.exists():
                        dmg_path.unlink(missing_ok=True)
                    raise ValueError(f"Checksum mismatch! Expected {info.checksum}, got {computed_sha}")

                # 3. Mount DMG — use a unique temp directory to avoid race conditions
                if on_status:
                    on_status("installing")
                mount_point = Path(tempfile.mkdtemp(prefix="twinspace_upd_"))
                logger.info(f"Attaching disk image at {mount_point}...")

                attach_res = subprocess.run(
                    ["hdiutil", "attach", str(dmg_path), "-nobrowse", "-mountpoint", str(mount_point)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if attach_res.returncode != 0:
                    shutil.rmtree(mount_point, ignore_errors=True)
                    raise RuntimeError(f"Failed to mount DMG: {attach_res.stderr.strip()}")

                try:
                    # 4. Locate .app inside mount point
                    apps = list(mount_point.glob("*.app"))
                    if not apps:
                        raise RuntimeError(f"No .app bundle found inside {mount_point}")
                    src_app = apps[0]
                    logger.info(f"Found source app in DMG: {src_app}")

                    # 5. Move existing .app to Trash or move aside
                    if target_app_path.exists():
                        logger.info(f"Moving {target_app_path} to Trash via osascript...")
                        script = f'tell application "Finder" to move POSIX file "{target_app_path}" to trash'
                        trash_res = subprocess.run(
                            ["osascript", "-e", script],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if trash_res.returncode != 0:
                            logger.warning(f"osascript trash failed ({trash_res.stderr.strip()}), moving aside")
                            temp_backup = Path(f"/tmp/TwinSpace_old_{os.getpid()}.app")
                            if temp_backup.exists():
                                shutil.rmtree(temp_backup, ignore_errors=True)
                            try:
                                target_app_path.rename(temp_backup)
                                shutil.rmtree(temp_backup, ignore_errors=True)
                            except OSError:
                                shutil.rmtree(target_app_path, ignore_errors=True)

                    # 6. Ditto install new .app
                    logger.info(f"Installing {src_app} to {target_app_path} via ditto...")
                    ditto_res = subprocess.run(
                        ["ditto", str(src_app), str(target_app_path)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if ditto_res.returncode != 0:
                        raise RuntimeError(f"Failed to ditto install application: {ditto_res.stderr.strip()}")

                    # 7. Strip quarantine attribute to avoid Gatekeeper warning
                    subprocess.run(
                        ["xattr", "-cr", str(target_app_path)],
                        capture_output=True,
                        text=True,
                        check=False,
                    )

                    logger.info(f"Successfully installed update to {target_app_path}")
                finally:
                    # 8. Detach mount and remove the temp mount directory
                    logger.info("Detaching disk image...")
                    subprocess.run(
                        ["hdiutil", "detach", str(mount_point), "-force"],
                        capture_output=True,
                        check=False,
                    )
                    shutil.rmtree(mount_point, ignore_errors=True)

            finally:
                # 9. Cleanup temporary DMG
                if dmg_path.exists():
                    try:
                        dmg_path.unlink()
                        logger.info("Removed temporary DMG")
                    except OSError as e:
                        logger.warning(f"Failed to remove temp DMG: {e}")

        await loop.run_in_executor(None, _worker)
