import os
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

import yaml

from twinspace.core.config import DEFAULT_STATE_FILE
from twinspace.core.logger import get_logger
from twinspace.core.timestamps import parse_iso_timestamp

STATE_FILE = DEFAULT_STATE_FILE

logger = get_logger("core.state")


@dataclass
class CloneRecord:
    clone_name: str
    source_app: str
    source_path: str
    bundle_id: str
    strategy: str
    dest_path: str
    data_dir: str
    created_at: str
    last_opened_at: str = ""
    proxy_enabled: bool = False
    proxy_summary: str = ""
    new_bundle_id: str = ""
    language: str = "system"
    display_name: str | None = None
    injection_strategy: str = "auto"
    notes: str = ""
    env_group: str = ""
    env_dir: str = ""
    env_overrides: dict[str, str] = field(default_factory=dict)


import contextlib
import fcntl
import tempfile


@contextlib.contextmanager
def _file_lock(lock_path: Path):
    """Advisory file lock to serialize read-modify-write state changes."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a") as f:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def _normalise_bundle_path(value: str | Path | None) -> str:
    """Resolve a bundle path so notifications and the state file compare equal."""
    text = str(value or "")
    if not text:
        return ""
    try:
        return os.path.realpath(text)
    except OSError:  # pragma: no cover - realpath is tolerant in practice
        return text


def is_any_clone_running(dest_paths: Iterable[str | Path]) -> bool:
    """Return True when any process command line references one of the clone paths."""
    import subprocess

    needles = [str(path) for path in dest_paths if str(path).endswith(".app")]
    if not needles:
        return False
    try:
        result = subprocess.run(
            ["ps", "-axo", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if result.returncode != 0:
        return False
    lines = result.stdout.splitlines()
    return any(needle in line for needle in needles for line in lines)


def is_clone_running(dest_path: str | Path) -> bool:
    """Return True when a process command line references the clone bundle path."""
    return is_any_clone_running([dest_path])


def clone_pids(dest_path: str | Path) -> list[str]:
    """Return the PIDs whose command line references the clone bundle path."""
    import subprocess

    needle = str(dest_path)
    if not needle.endswith(".app"):
        return []
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    pids: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid, command = parts
        if needle in command:
            pids.append(pid)
    return pids


def running_clone_names(records: Iterable[CloneRecord]) -> set[str]:
    """Return the clone names that currently have a process running."""
    import subprocess

    mapping = {
        str(record.dest_path): record.clone_name
        for record in records
        if str(record.dest_path).endswith(".app")
    }
    if not mapping:
        return set()
    try:
        result = subprocess.run(
            ["ps", "-axo", "command="],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return set()
    if result.returncode != 0:
        return set()
    lines = result.stdout.splitlines()
    return {
        name
        for path, name in mapping.items()
        if any(path in line for line in lines)
    }


def _signal_clone(needle: str, signal_name: str) -> None:
    """Send ``signal_name`` to every process whose command line mentions ``needle``."""
    import subprocess

    pids = clone_pids(needle)
    if not pids:
        return
    try:
        subprocess.run(["kill", signal_name, *pids], capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def _wait_until_stopped(needle: str, timeout: float) -> bool:
    """Poll the process table until the clone is gone (or the timeout expires)."""
    import time

    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if not is_clone_running(needle):
            return True
        time.sleep(0.2)
    return not is_clone_running(needle)


def quit_clone(dest_path: str | Path, timeout: float = 4.0) -> bool:
    """Stop every process of a clone, escalating when it ignores SIGTERM.

    Electron apps (WorkBuddy, Qoder, Trae…) install a SIGTERM handler that can
    keep them alive, so a plain TERM leaves the clone "still running" and the
    stop action appears to fail. After ``timeout`` seconds the remaining
    processes get SIGKILL — the data directory is separate from the bundle, so
    nothing but unsaved window state is lost.
    """
    needle = str(dest_path)
    if not needle.endswith(".app"):
        return True
    if not is_clone_running(needle):
        return True
    _signal_clone(needle, "-TERM")
    if _wait_until_stopped(needle, timeout):
        return True
    _signal_clone(needle, "-KILL")
    return _wait_until_stopped(needle, 2.0)


class StateManager:
    def __init__(self, state_file: Path | None = None):
        if state_file is not None:
            self.state_file = Path(state_file)
        else:
            self.state_file = DEFAULT_STATE_FILE

    @property
    def lock_file(self) -> Path:
        return self.state_file.with_suffix(".lock")

    def load(self) -> list[CloneRecord]:
        """Load all records from YAML file. Returns empty list if file missing or corrupt."""
        if not self.state_file.exists():
            return []
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except (yaml.YAMLError, OSError):
            return []

        if not isinstance(data, list):
            return []

        records: list[CloneRecord] = []
        dirty = False
        for item in data:
            if isinstance(item, dict):
                if "language" not in item or not item["language"]:
                    item["language"] = "system"
                if "injection_strategy" not in item or not item["injection_strategy"]:
                    item["injection_strategy"] = "auto"
                try:
                    rec = CloneRecord(**item)
                    # Migrate legacy embedded password from proxy_summary to Keychain
                    if rec.proxy_enabled and rec.proxy_summary:
                        try:
                            from urllib.parse import urlparse
                            parsed = urlparse(rec.proxy_summary)
                            if parsed.password:
                                from twinspace.core.keychain import save_clone_proxy_password
                                save_clone_proxy_password(rec.clone_name, parsed.password)
                                user_info = f"{parsed.username}@" if parsed.username else ""
                                host_info = parsed.hostname or ""
                                if parsed.port:
                                    host_info = f"{host_info}:{parsed.port}"
                                rec.proxy_summary = f"{parsed.scheme}://{user_info}{host_info}"
                                dirty = True
                        except Exception as e:
                            logger.warning(
                                f"Failed to migrate embedded proxy password to Keychain "
                                f"for '{rec.clone_name}': {e}"
                            )
                    records.append(rec)
                except TypeError:
                    # Unknown or renamed fields must never silently drop a clone
                    # record (the next save would delete it for good): keep the
                    # recognized fields and surface what was ignored.
                    known = {f.name for f in fields(CloneRecord)}
                    dropped = sorted(set(item) - known)
                    logger.warning(
                        f"Ignoring unknown field(s) {dropped} in clone record "
                        f"'{item.get('clone_name', '<unknown>')}'"
                    )
                    rec = CloneRecord(**{k: v for k, v in item.items() if k in known})
                    records.append(rec)
                    continue

        if dirty:
            self.save(records)
        return records

    def save(self, records: list[CloneRecord]) -> None:
        """Save records atomically to YAML file (create parent dirs if needed)."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        # Ensure no plaintext passwords exist in records before saving
        for r in records:
            if r.proxy_enabled and r.proxy_summary:
                try:
                    from urllib.parse import urlparse
                    parsed = urlparse(r.proxy_summary)
                    if parsed.password:
                        from twinspace.core.keychain import save_clone_proxy_password
                        save_clone_proxy_password(r.clone_name, parsed.password)
                        user_info = f"{parsed.username}@" if parsed.username else ""
                        host_info = parsed.hostname or ""
                        if parsed.port:
                            host_info = f"{host_info}:{parsed.port}"
                        r.proxy_summary = f"{parsed.scheme}://{user_info}{host_info}"
                except Exception as e:
                    logger.warning(
                        f"Failed to migrate embedded proxy password to Keychain "
                        f"for '{r.clone_name}': {e}"
                    )

        raw_list = [asdict(r) for r in records]
        temp_fd, temp_path = tempfile.mkstemp(
            prefix="clones_",
            suffix=".yaml.tmp",
            dir=str(self.state_file.parent),
        )
        try:
            with open(temp_fd, "w", encoding="utf-8") as f:
                yaml.safe_dump(raw_list, f, allow_unicode=True, sort_keys=False)
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            os.replace(temp_path, self.state_file)
        finally:
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    def add(self, record: CloneRecord) -> None:
        """Append or update a record and persist under lock."""
        with _file_lock(self.lock_file):
            records = self.load()
            for i, r in enumerate(records):
                if r.clone_name == record.clone_name:
                    records[i] = record
                    break
            else:
                records.append(record)
            self.save(records)

    def remove(self, clone_name: str) -> bool:
        """Remove record by clone_name under lock. Returns True if found and removed."""
        with _file_lock(self.lock_file):
            records = self.load()
            new_records = [r for r in records if r.clone_name != clone_name]
            if len(new_records) != len(records):
                self.save(new_records)
                try:
                    from twinspace.core.keychain import delete_clone_proxy_password
                    delete_clone_proxy_password(clone_name)
                except Exception:
                    pass
                return True
            return False

    def get(self, clone_name: str) -> CloneRecord | None:
        """Get record by clone_name. Returns None if not found."""
        for r in self.load():
            if r.clone_name == clone_name:
                return r
        return None

    def mark_opened(
        self,
        clone_name: str | None = None,
        *,
        dest_path: str | Path | None = None,
        timestamp: str | None = None,
        min_interval: float = 5.0,
    ) -> tuple[str, str] | None:
        """Record when a clone bundle was last opened.

        The record is matched by ``clone_name`` or, for system launch
        notifications, by ``dest_path``. Returns ``(clone_name, timestamp)`` for
        the matched record, or ``None`` when nothing matches.

        A click and the matching NSWorkspace notification describe the same
        launch, so a timestamp that arrives ``min_interval`` seconds after the
        stored one reuses it instead of rewriting the state file twice.
        """
        if clone_name is None and dest_path is None:
            return None

        stamp = timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds")
        wanted_path = _normalise_bundle_path(dest_path)
        with _file_lock(self.lock_file):
            records = self.load()
            target: CloneRecord | None = None
            for record in records:
                if clone_name is not None:
                    if record.clone_name == clone_name:
                        target = record
                        break
                elif wanted_path and _normalise_bundle_path(record.dest_path) == wanted_path:
                    target = record
                    break
            if target is None:
                return None

            previous = parse_iso_timestamp(target.last_opened_at)
            current = parse_iso_timestamp(stamp)
            if (
                previous is not None
                and current is not None
                and abs((current - previous).total_seconds()) < min_interval
            ):
                return target.clone_name, target.last_opened_at

            target.last_opened_at = stamp
            self.save(records)
            return target.clone_name, stamp
