"""Environment data backup and restore."""

from __future__ import annotations

import io
import json
import re
import shutil
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from twinspace.core.config import DEFAULT_TWINSPACE_DIR
from twinspace.core.logger import get_logger
from twinspace.core.state import CloneRecord
from twinspace.validation import validate_deletion_target

from .apps import app_key_for_bundle_id

logger = get_logger("core.environments.backup")

MANIFEST_NAME = "manifest.json"
BACKUP_VERSION = 1

_BACKUP_NAME_RE = re.compile(r"^(?P<env>.+)-(?P<date>\d{8})-(?P<time>\d{6})\.tar\.gz$")


def default_backup_path(environment: str, base_dir: Path | None = None) -> Path:
    root = Path(base_dir) if base_dir else DEFAULT_TWINSPACE_DIR
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return root / "Backups" / f"{environment}-{timestamp}.tar.gz"


def list_backups(
    environment: str | None = None,
    base_dir: Path | None = None,
) -> list[dict[str, object]]:
    """List backup archives, newest first.

    Each item carries ``path`` / ``name`` / ``environment`` / ``size`` /
    ``mtime``. With ``environment`` set, only archives named
    ``<environment>-<date>-<time>.tar.gz`` are returned. Listing never touches
    the archive files.
    """
    root = (Path(base_dir) if base_dir else DEFAULT_TWINSPACE_DIR) / "Backups"
    if not root.is_dir():
        return []
    prefix = f"{environment}-" if environment else ""
    items: list[dict[str, object]] = []
    for path in sorted(root.glob("*.tar.gz")):
        match = _BACKUP_NAME_RE.match(path.name)
        if match is None:
            continue
        if prefix and not path.name.startswith(prefix):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        items.append(
            {
                "path": path,
                "name": path.name,
                "environment": match.group("env"),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
            }
        )
    items.sort(key=lambda item: float(item["mtime"]), reverse=True)
    return items


def prune_backups(
    environment: str,
    keep: int,
    base_dir: Path | None = None,
) -> list[Path]:
    """Delete the oldest backups of one environment beyond ``keep``.

    Only files matching the ``<environment>-<date>-<time>.tar.gz`` naming
    pattern are considered, and the newest ``keep`` backups always survive.
    Returns the deleted paths.
    """
    keep = max(0, int(keep))
    backups = list_backups(environment, base_dir)
    removed: list[Path] = []
    for item in backups[keep:]:
        path = Path(item["path"])
        try:
            path.unlink()
            removed.append(path)
            logger.info("Pruned old backup %s", path)
        except OSError as exc:
            logger.debug("Could not prune backup %s: %s", path, exc)
    return removed


def create_backup(
    environment: str,
    records: list[CloneRecord],
    output_path: Path | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Archive each app's data directory plus a portable manifest."""
    if not records:
        raise ValueError(f"Environment {environment!r} has no apps to back up.")

    destination = Path(output_path) if output_path else default_backup_path(environment, base_dir)
    destination = destination.expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)

    apps: list[dict[str, object]] = []
    with tarfile.open(destination, "w:gz") as archive:
        for record in records:
            key = app_key_for_bundle_id(record.bundle_id)
            if not key:
                logger.warning("Skipping unknown app in backup: %s", record.clone_name)
                continue
            data_dir = Path(record.data_dir)
            included = data_dir.is_dir()
            apps.append(
                {
                    "key": key,
                    "clone_name": record.clone_name,
                    "data_included": included,
                }
            )
            if included:
                archive.add(data_dir, arcname=f"data/{key}", recursive=True)

        manifest = {
            "version": BACKUP_VERSION,
            "environment": environment,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "apps": apps,
        }
        payload = json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8")
        info = tarfile.TarInfo(MANIFEST_NAME)
        info.size = len(payload)
        info.mtime = int(time.time())
        info.mode = 0o600
        archive.addfile(info, io.BytesIO(payload))

    logger.info("Created environment backup at %s", destination)
    return destination


def summarize_backup(archive_path: Path) -> dict:
    """Per-app content summary of a backup without extracting anything.

    Returns ``{"environment", "created_at", "apps": [{key, files, bytes}],
    "total_bytes"}``. Reading the member list of a ``.tar.gz`` streams the
    whole archive, so callers should run this in a worker thread and cache the
    result per path.
    """
    path = Path(archive_path).expanduser()
    result: dict[str, object] = {
        "path": path,
        "environment": "",
        "created_at": "",
        "apps": [],
        "total_bytes": 0,
    }
    with tarfile.open(path, "r:gz") as archive:
        try:
            member = archive.getmember(MANIFEST_NAME)
        except KeyError as exc:
            raise ValueError(f"Not a TwinSpace environment backup: {path}") from exc
        handle = archive.extractfile(member)
        if handle is None:
            raise ValueError(f"Backup manifest is unreadable: {path}")
        data = json.loads(handle.read().decode("utf-8"))
        result["environment"] = str(data.get("environment", ""))
        result["created_at"] = str(data.get("created_at", ""))

        per: dict[str, dict[str, object]] = {}
        for entry in archive.getmembers():
            if entry.name == MANIFEST_NAME or not entry.name.startswith("data/"):
                continue
            parts = entry.name.split("/", 2)
            if len(parts) < 2 or not parts[1]:
                continue
            key = parts[1]
            item = per.setdefault(key, {"key": key, "files": 0, "bytes": 0})
            if entry.isfile():
                item["files"] = int(item["files"]) + 1
                item["bytes"] = int(item["bytes"]) + int(entry.size)
        apps = sorted(per.values(), key=lambda item: -int(item["bytes"]))
        result["apps"] = apps
        result["total_bytes"] = sum(int(item["bytes"]) for item in apps)
    return result


def read_manifest(archive_path: Path) -> dict:
    path = Path(archive_path).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Backup archive not found: {path}")
    with tarfile.open(path, "r:gz") as archive:
        try:
            member = archive.getmember(MANIFEST_NAME)
        except KeyError as exc:
            raise ValueError(f"Not a TwinSpace environment backup: {path}") from exc
        handle = archive.extractfile(member)
        if handle is None:
            raise ValueError(f"Backup manifest is unreadable: {path}")
        data = json.loads(handle.read().decode("utf-8"))
    if not isinstance(data, dict) or data.get("version") != BACKUP_VERSION:
        raise ValueError(f"Unsupported backup format: {path}")
    return data


def restore_backup(
    archive_path: Path,
    records: list[CloneRecord],
    on_progress=None,
) -> tuple[list[str], list[str]]:
    """Merge archived app data into the current data directories.

    Returns ``(restored_keys, errors)``. Existing files are overwritten, but
    nothing is deleted, so a restore cannot remove newer user data.
    """
    manifest = read_manifest(archive_path)
    records_by_key = {
        app_key_for_bundle_id(record.bundle_id): record
        for record in records
        if app_key_for_bundle_id(record.bundle_id)
    }
    apps = manifest.get("apps") or []
    restored: list[str] = []
    errors: list[str] = []

    with tempfile.TemporaryDirectory(prefix="twinspace-restore-") as temp_dir:
        root = Path(temp_dir)
        with tarfile.open(Path(archive_path).expanduser(), "r:gz") as archive:
            archive.extractall(root, filter="data")

        total = len(apps)
        for index, item in enumerate(apps, start=1):
            key = str(item.get("key", "")) if isinstance(item, dict) else ""
            record = records_by_key.get(key)
            if record is None:
                errors.append(f"{key or 'unknown'}: app is not part of this environment")
                continue
            source = root / "data" / key
            if not item.get("data_included") or not source.is_dir():
                errors.append(f"{key}: backup does not contain app data")
                continue
            destination = Path(record.data_dir)
            try:
                validate_deletion_target(str(destination), field="data_dir")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, destination, dirs_exist_ok=True, symlinks=True)
                restored.append(key)
                logger.info("Restored %s data to %s", key, destination)
            except Exception as exc:
                errors.append(f"{key}: {exc}")
            if on_progress:
                on_progress(index, total, key)

    return restored, errors
