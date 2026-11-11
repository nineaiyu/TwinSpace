import ctypes
import functools
import os
import plistlib
import subprocess
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


_PROC_PIDPATHINFO_MAXSIZE = 4096


@functools.lru_cache(maxsize=1)
def _proc_pidpath() -> Any | None:
    """Resolve ``libproc.proc_pidpath`` once; ``None`` off macOS."""
    for name in ("libproc.dylib", "/usr/lib/libproc.dylib"):
        try:
            lib = ctypes.CDLL(name)
            fn = lib.proc_pidpath
        except (OSError, AttributeError):
            continue
        fn.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        fn.restype = ctypes.c_int
        return fn
    return None


def _process_executable_path(pid: str) -> str:
    """Kernel-resolved executable path of a process (empty when unavailable)."""
    fn = _proc_pidpath()
    if fn is None:
        return ""
    buffer = ctypes.create_string_buffer(_PROC_PIDPATHINFO_MAXSIZE)
    try:
        length = fn(int(pid), ctypes.cast(buffer, ctypes.c_void_p), len(buffer))
    except (ValueError, OSError):
        return ""
    if length <= 0:
        return ""
    return os.fsdecode(buffer.value)


def _bundle_executable_names(needle: str) -> frozenset[str]:
    """Names the clone's main executable can show up as in ``ps``.

    Apps like ZCode call ``app.setName()`` and rewrite ``argv[0]``, so the main
    process only shows a bare name (``ZCode-b1``) while helpers still carry the
    full bundle path in their command lines.
    """
    names = {Path(needle).stem}
    for relative in ("Contents/Info.plist", "Info.plist"):
        try:
            with open(Path(needle) / relative, "rb") as handle:
                metadata = plistlib.load(handle)
        except Exception:  # best effort: a missing or broken plist is not fatal
            continue
        executable = metadata.get("CFBundleExecutable") if isinstance(metadata, dict) else None
        if isinstance(executable, str) and executable:
            names.add(executable)
    return frozenset(names)


def _process_rows() -> list[tuple[str, str]]:
    """Snapshot ``(pid, command)`` for every process, once per check."""
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
    rows: list[tuple[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2:
            rows.append((parts[0], parts[1]))
    return rows


def _clone_process_pids(needle: str, rows: list[tuple[str, str]]) -> list[str]:
    """PIDs of a clone: helpers by bundle path, main process by executable path."""
    if not needle.endswith(".app"):
        return []
    names = _bundle_executable_names(needle)
    bundle = os.path.realpath(needle)
    needles = tuple(dict.fromkeys((needle, bundle)))
    pids: list[str] = []
    for pid, command in rows:
        # Helpers start with their own path inside the bundle. A shell/grep/open
        # command that merely *mentions* the path is not a running clone.
        if command.startswith(needles):
            pids.append(pid)
            continue
        first = command.split(None, 1)[0]
        if os.path.basename(first) not in names:
            continue
        executable = os.path.realpath(_process_executable_path(pid))
        if executable.startswith(bundle + os.sep):
            pids.append(pid)
    return pids


_AE_CORE_EVENT_CLASS = 0x61657674  # 'aevt'
_AE_QUIT_APPLICATION = 0x71756974  # 'quit'
_AE_TYPE_KERNEL_PROCESS_ID = 0x6B706964  # 'kpid'
_AE_NO_REPLY = 0x00000001
_AE_DEFAULT_TIMEOUT = -1


class _AEDesc(ctypes.Structure):
    _fields_ = [("descriptorType", ctypes.c_uint32), ("dataHandle", ctypes.c_void_p)]


@functools.lru_cache(maxsize=1)
def _apple_event_library() -> Any | None:
    """Resolve the Apple Event Manager once; ``None`` when it is unavailable."""
    for name in (
        "/System/Library/Frameworks/CoreServices.framework/CoreServices",
        "/System/Library/Frameworks/CoreServices.framework/Frameworks/AE.framework/Versions/A/AE",
    ):
        try:
            lib = ctypes.CDLL(name)
            create_desc = lib.AECreateDesc
            create_event = lib.AECreateAppleEvent
            send = lib.AESendMessage
            dispose = lib.AEDisposeDesc
        except (OSError, AttributeError):
            continue
        desc_ptr = ctypes.POINTER(_AEDesc)
        create_desc.argtypes = [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_ulong, desc_ptr]
        create_desc.restype = ctypes.c_int32
        create_event.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
            desc_ptr,
            ctypes.c_int16,
            ctypes.c_uint32,
            desc_ptr,
        ]
        create_event.restype = ctypes.c_int32
        send.argtypes = [desc_ptr, ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32]
        send.restype = ctypes.c_int32
        dispose.argtypes = [desc_ptr]
        dispose.restype = ctypes.c_int32
        return lib
    return None


def _send_quit_apple_event(pid: str) -> bool:
    """Deliver a Quit Apple Event to one PID, just like the app's ⌘Q menu item."""
    lib = _apple_event_library()
    if lib is None:
        return False
    pid_value = ctypes.c_int32(int(pid))
    target = _AEDesc()
    event = _AEDesc()
    target_ready = event_ready = False
    try:
        if lib.AECreateDesc(
            _AE_TYPE_KERNEL_PROCESS_ID,
            ctypes.byref(pid_value),
            ctypes.sizeof(pid_value),
            ctypes.byref(target),
        ) != 0:
            return False
        target_ready = True
        if lib.AECreateAppleEvent(
            _AE_CORE_EVENT_CLASS,
            _AE_QUIT_APPLICATION,
            ctypes.byref(target),
            -1,  # kAutoGenerateReturnID
            0,  # kAnyTransactionID
            ctypes.byref(event),
        ) != 0:
            return False
        event_ready = True
        return lib.AESendMessage(
            ctypes.byref(event), None, _AE_NO_REPLY, _AE_DEFAULT_TIMEOUT
        ) == 0
    except (ValueError, OSError):
        return False
    finally:
        if event_ready:
            lib.AEDisposeDesc(ctypes.byref(event))
        if target_ready:
            lib.AEDisposeDesc(ctypes.byref(target))


def _clone_main_pids(needle: str, rows: list[tuple[str, str]]) -> list[str]:
    """Main app PIDs (under Contents/MacOS), excluding Electron helpers."""
    macos = os.path.join(os.path.realpath(needle), "Contents", "MacOS") + os.sep
    return [
        pid
        for pid in _clone_process_pids(needle, rows)
        if os.path.realpath(_process_executable_path(pid)).startswith(macos)
    ]


def _request_graceful_quit(needle: str) -> bool:
    """Ask the clone's main process(es) to quit via Quit Apple Events."""
    pids = _clone_main_pids(needle, _process_rows())
    if not pids:
        return False
    sent = False
    for pid in pids:
        if _send_quit_apple_event(pid):
            sent = True
        else:
            logger.warning("Quit Apple Event could not be delivered to pid %s (%s)", pid, needle)
    return sent


def is_any_clone_running(dest_paths: Iterable[str | Path]) -> bool:
    """Return True when any process belonging to one of the clones is alive."""
    needles = [str(path) for path in dest_paths if str(path).endswith(".app")]
    if not needles:
        return False
    rows = _process_rows()
    return any(_clone_process_pids(needle, rows) for needle in needles)


def is_clone_running(dest_path: str | Path) -> bool:
    """Return True when a process belonging to the clone bundle is alive."""
    return is_any_clone_running([dest_path])


def clone_pids(dest_path: str | Path) -> list[str]:
    """Return every PID to signal, including a renamed main process."""
    needle = str(dest_path)
    if not needle.endswith(".app"):
        return []
    return _clone_process_pids(needle, _process_rows())


def running_clone_names(records: Iterable[CloneRecord]) -> set[str]:
    """Return the clone names that currently have a process running."""
    mapping = {
        str(record.dest_path): record.clone_name
        for record in records
        if str(record.dest_path).endswith(".app")
    }
    if not mapping:
        return set()
    rows = _process_rows()
    return {
        name
        for needle, name in mapping.items()
        if _clone_process_pids(needle, rows)
    }


def _signal_clone(needle: str, signal_name: str) -> None:
    """Fallback for non-GUI hosts: request termination via a signal, never SIGKILL."""
    pids = clone_pids(needle)
    if not pids:
        return
    try:
        result = subprocess.run(
            ["kill", signal_name, *pids],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Could not send %s to %s: %s", signal_name, needle, exc)
        return
    if result.returncode != 0:
        logger.warning(
            "kill %s failed for %s (pids %s): %s",
            signal_name,
            needle,
            ", ".join(pids),
            result.stderr.strip(),
        )


def _wait_until_stopped(needle: str, timeout: float) -> bool:
    """Poll the process table until the clone is gone (or the timeout expires)."""
    import time

    deadline = time.monotonic() + max(0.0, timeout)
    while time.monotonic() < deadline:
        if not is_clone_running(needle):
            return True
        time.sleep(0.2)
    return not is_clone_running(needle)


def quit_clone(dest_path: str | Path, timeout: float = 8.0) -> bool:
    """Ask a clone to quit the way its own Quit (⌘Q) menu item does.

    A Quit Apple Event goes to the app's main process, so Electron runs its
    normal shutdown (before-quit / will-quit, window state, helper cleanup).
    SIGKILL is never used: if the app needs to ask about unsaved work or refuses
    to quit, the caller reports "still running" instead of forcing it down.
    Only when the Apple Event Manager is unavailable do we fall back to a plain
    SIGTERM request.
    """
    needle = str(dest_path)
    if not needle.endswith(".app"):
        return True
    if not is_clone_running(needle):
        return True
    if not _request_graceful_quit(needle):
        logger.warning("Quit Apple Event unavailable for %s; falling back to SIGTERM", needle)
        _signal_clone(needle, "-TERM")
    return _wait_until_stopped(needle, timeout)


def quit_clones(
    dest_paths: Iterable[str | Path], timeout: float = 8.0
) -> dict[str, bool]:
    """Quit several clones with one shared shutdown wait.

    Every Quit Apple Event is sent up front so the apps shut down in parallel,
    then a single poll watches all of them — waiting for each clone in turn
    would make switching environments take N × 8 s in the worst case. Same
    graceful-only policy as ``quit_clone``: no SIGKILL, ever.
    """
    import time

    needles: list[str] = []
    seen: set[str] = set()
    for raw in dest_paths:
        needle = str(raw)
        if not needle.endswith(".app") or needle in seen:
            continue
        seen.add(needle)
        needles.append(needle)

    pending: list[str] = []
    for needle in needles:
        if not is_clone_running(needle):
            continue
        if not _request_graceful_quit(needle):
            logger.warning(
                "Quit Apple Event unavailable for %s; falling back to SIGTERM", needle
            )
            _signal_clone(needle, "-TERM")
        pending.append(needle)

    deadline = time.monotonic() + max(0.0, timeout)
    remaining = list(pending)
    while remaining and time.monotonic() < deadline:
        time.sleep(0.2)
        # One process-table snapshot per cycle covers every pending clone;
        # forking `ps` per needle would multiply the cost by the batch size.
        rows = _process_rows()
        remaining = [
            needle
            for needle in remaining
            if _clone_process_pids(needle, rows)
        ]

    return {needle: needle not in remaining for needle in needles}


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
