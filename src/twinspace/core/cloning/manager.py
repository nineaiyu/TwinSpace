"""Core clone lifecycle operations shared by the CLI and the GUI."""

from __future__ import annotations

import shlex
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from twinspace.core.app_inspector import AppInspector
from twinspace.core.clone_task import CloneTask, preserve_clone_icon
from twinspace.core.config import DEFAULT_DATA_DIR, DEFAULT_STATE_FILE
from twinspace.core.engines import HardCloneEngine, SoftCloneEngine
from twinspace.core.keychain import get_clone_proxy_password, save_clone_proxy_password
from twinspace.core.logger import get_logger
from twinspace.core.state import CloneRecord, StateManager, is_clone_running
from twinspace.executor.runner import Runner
from twinspace.recipes.loader import RecipeLoader
from twinspace.validation import validate_deletion_target

logger = get_logger("core.cloning.manager")


class CloneManager:
    """Execute create, update and remove operations against the local state file.

    The manager is synchronous so it can run inside a worker thread for the GUI
    while remaining directly callable from CLI commands.
    """

    def __init__(self, state_file: Path = DEFAULT_STATE_FILE):
        self.state_file = Path(state_file)
        self.state_manager = StateManager(state_file=self.state_file)
        self._busy_clones: set[str] = set()
        self._busy_lock = threading.Lock()

    @property
    def busy_clones(self) -> set[str]:
        """Names of clones currently being created, updated or removed."""
        return self._busy_clones

    def list_clones(self) -> list[CloneRecord]:
        return self.state_manager.load()

    def get_clone(self, clone_name: str) -> CloneRecord | None:
        return self.state_manager.get(clone_name)

    def _claim(self, clone_name: str) -> None:
        with self._busy_lock:
            if clone_name in self._busy_clones:
                logger.warning("Operation already in progress for clone '%s'", clone_name)
                raise RuntimeError(f"Operation already in progress for '{clone_name}'")
            self._busy_clones.add(clone_name)

    def _release(self, clone_name: str) -> None:
        with self._busy_lock:
            self._busy_clones.discard(clone_name)

    def create_clone(self, task: CloneTask) -> CloneRecord:
        self._claim(task.clone_name)
        try:
            dest_path = task.dest_path
            logger.info(
                "Starting clone creation: name='%s', source='%s', strategy='%s', dest='%s'",
                task.clone_name,
                task.source.path,
                task.recipe.strategy,
                dest_path,
            )
            try:
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                task.data_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass

            needs_admin = not dest_path.is_relative_to(Path.home())
            try:
                if task.recipe.strategy == "soft_clone":
                    SoftCloneEngine.execute(task, needs_admin)
                else:
                    HardCloneEngine.execute(task, needs_admin)

                summary = ""
                if task.recipe.proxy.enabled:
                    proxy = task.recipe.proxy
                    if proxy.password:
                        save_clone_proxy_password(task.clone_name, proxy.password)
                    user = f"{proxy.username}@" if proxy.username else ""
                    summary = f"{proxy.type}://{user}{proxy.host}:{proxy.port}"

                record = CloneRecord(
                    clone_name=task.clone_name,
                    source_app=task.source.app_name,
                    source_path=str(task.source.path),
                    bundle_id=task.source.bundle_id,
                    strategy=task.recipe.strategy,
                    dest_path=str(task.dest_path),
                    data_dir=str(task.data_dir),
                    created_at=datetime.now(timezone.utc).isoformat(),
                    proxy_enabled=task.recipe.proxy.enabled,
                    proxy_summary=summary,
                    new_bundle_id=task.new_bundle_id,
                    language=task.language,
                    display_name=task.display_name,
                    injection_strategy=getattr(
                        task,
                        "actual_injection_strategy",
                        getattr(task, "injection_strategy", "auto"),
                    ),
                    env_group=task.env_group or "",
                    env_dir=str(task.env_dir) if task.env_dir else "",
                )
                self.state_manager.add(record)
                logger.info("Clone '%s' created successfully at '%s'", task.clone_name, dest_path)
                return record
            except Exception as exc:
                logger.error("Failed to create clone '%s': %s", task.clone_name, exc)
                raise
        finally:
            self._release(task.clone_name)

    def update_clone(self, clone_name: str) -> CloneRecord:
        self._claim(clone_name)
        try:
            logger.info("Updating clone '%s'", clone_name)
            record = self.state_manager.get(clone_name)
            if record is None:
                logger.error("Clone '%s' not found for update", clone_name)
                raise ValueError(f"Clone {clone_name} not found")
            if not Path(record.source_path).exists():
                logger.error("Source app not found for clone '%s': %s", clone_name, record.source_path)
                raise FileNotFoundError(f"Source app not found: {record.source_path}")

            dest_path = Path(record.dest_path)
            needs_admin = not dest_path.is_relative_to(Path.home())

            # The state file is user-writable and unauthenticated: never hand a
            # path from it to `rm -rf` without validation.
            validate_deletion_target(str(dest_path), expect_bundle=True, field="dest_path")
            if is_clone_running(dest_path):
                raise RuntimeError(f"Please quit '{clone_name}' before updating.")

            with preserve_clone_icon(dest_path) as icon_path:
                script = f"#!/bin/bash\nset -e\nrm -rf {shlex.quote(str(dest_path))}\n"
                Runner.run(script, needs_admin)

                info = AppInspector.inspect(record.source_path)
                recipe = RecipeLoader.match(info.bundle_id, app_path=record.source_path)
                for key, value in getattr(record, "env_overrides", {}).items():
                    recipe.environment_injection[normalize_legacy_env_key(key)] = value

                existing_records = self.state_manager.load()
                existing_bundle_ids = {
                    item.new_bundle_id
                    for item in existing_records
                    if item.new_bundle_id and item.clone_name != clone_name
                }
                new_bundle_id = record.new_bundle_id or AppInspector.resolve_bundle_id(
                    record.bundle_id,
                    clone_name=record.clone_name,
                    existing_bundle_ids=existing_bundle_ids,
                )

                env_group = getattr(record, "env_group", "") or None
                env_dir_value = getattr(record, "env_dir", "")
                if env_dir_value:
                    rebuild_env_dir = Path(env_dir_value)
                elif env_group:
                    rebuild_env_dir = DEFAULT_DATA_DIR / "Environments" / env_group
                else:
                    rebuild_env_dir = None

                task = CloneTask(
                    source=info,
                    dest_path=dest_path,
                    data_dir=Path(record.data_dir),
                    recipe=recipe,
                    clone_name=record.clone_name,
                    new_bundle_id=new_bundle_id,
                    language=getattr(record, "language", "system"),
                    display_name=getattr(record, "display_name", None),
                    icon_path=icon_path,
                    env_group=env_group,
                    env_dir=rebuild_env_dir,
                    injection_strategy=getattr(recipe, "injection_strategy", "auto"),
                )
                self._restore_proxy(task, record)

                # Follow the current recipe: a recipe may deliberately switch
                # strategies (e.g. Chrome's hard-to-soft Keychain fix).
                record.strategy = recipe.strategy
                if recipe.strategy == "soft_clone":
                    SoftCloneEngine.execute(task, needs_admin)
                else:
                    HardCloneEngine.execute(task, needs_admin)

                record.created_at = datetime.now(timezone.utc).isoformat()
                record.injection_strategy = getattr(task, "actual_injection_strategy", "auto")
                self.state_manager.add(record)
                logger.info("Clone '%s' updated successfully", clone_name)
                return record
        finally:
            self._release(clone_name)

    @staticmethod
    def _restore_proxy(task: CloneTask, record: CloneRecord) -> None:
        if not (record.proxy_enabled and record.proxy_summary):
            return
        parsed = urlparse(record.proxy_summary)
        task.recipe.proxy.enabled = True
        if parsed.scheme:
            task.recipe.proxy.type = parsed.scheme  # type: ignore[assignment]
        if parsed.hostname:
            task.recipe.proxy.host = parsed.hostname
        if parsed.port:
            task.recipe.proxy.port = parsed.port
        if parsed.username:
            task.recipe.proxy.username = parsed.username
        if parsed.password:
            task.recipe.proxy.password = parsed.password
        elif parsed.username:
            password = get_clone_proxy_password(record.clone_name)
            if password:
                task.recipe.proxy.password = password

    def remove_clone(self, clone_name: str, with_data: bool = False) -> bool:
        self._claim(clone_name)
        try:
            logger.info("Removing clone '%s' (with_data=%s)", clone_name, with_data)
            record = self.state_manager.get(clone_name)
            if record is None:
                logger.warning("Clone '%s' not found for removal", clone_name)
                return False
            needs_admin = (
                not Path(record.dest_path).is_relative_to(Path.home())
                or (with_data and not Path(record.data_dir).is_relative_to(Path.home()))
            )

            validate_deletion_target(record.dest_path, expect_bundle=True, field="dest_path")
            if with_data:
                validate_deletion_target(record.data_dir, field="data_dir")
            if is_clone_running(record.dest_path):
                raise RuntimeError(f"Please quit '{clone_name}' before removing it.")

            lines = [
                "#!/bin/bash",
                "set -e",
                f"rm -rf {shlex.quote(record.dest_path)}",
            ]
            if with_data:
                lines.append(f"rm -rf {shlex.quote(record.data_dir)}")

            script = "\n".join(lines) + "\n"
            try:
                Runner.run(script, needs_admin)
            except Exception as exc:
                logger.error("Failed to remove clone files for '%s': %s", clone_name, exc)
                raise
            removed = self.state_manager.remove(clone_name)
            if removed:
                logger.info("Successfully removed clone '%s'", clone_name)
            return removed
        finally:
            self._release(clone_name)


def normalize_legacy_env_key(key: str) -> str:
    """Map pre-3.0 ATB_* internal override keys to their TwinSpace names."""
    if key.startswith("ATB_"):
        return "TWINSPACE_" + key[4:]
    return key
