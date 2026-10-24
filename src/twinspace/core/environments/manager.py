"""Environment orchestration shared by the GUI and CLI."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from twinspace.core.app_inspector import AppInspector
from twinspace.core.clone_task import CloneTask
from twinspace.core.cloning.manager import CloneManager, normalize_legacy_env_key
from twinspace.core.config import DEFAULT_APPS_DIR, DEFAULT_DATA_DIR, DEFAULT_STATE_FILE
from twinspace.core.logger import get_logger
from twinspace.core.state import CloneRecord, StateManager, is_clone_running
from twinspace.recipes.loader import RecipeLoader
from twinspace.validation import validate_clone_name

from .apps import (
    KNOWN_APPS,
    EnvironmentApp,
    EnvironmentInfo,
    app_for_key,
    app_key_for_bundle_id,
)
from .backup import create_backup, restore_backup
from .spec import EnvironmentAppSpec, EnvironmentSpec

logger = get_logger("core.environments.manager")

ProgressCallback = Callable[[int, int, EnvironmentApp, str], None]


class BlockingCloneBackend:
    """Async adapter around the synchronous CloneManager for CLI callers."""

    def __init__(self, state_manager: StateManager | None = None):
        self.manager = CloneManager(
            state_file=state_manager.state_file if state_manager else DEFAULT_STATE_FILE
        )
        self.state_manager = self.manager.state_manager

    async def create_clone(self, task: CloneTask) -> CloneRecord:
        return await asyncio.to_thread(self.manager.create_clone, task)

    async def update_clone(self, clone_name: str) -> CloneRecord:
        return await asyncio.to_thread(self.manager.update_clone, clone_name)

    async def remove_clone(self, clone_name: str, with_data: bool = False) -> bool:
        return await asyncio.to_thread(self.manager.remove_clone, clone_name, with_data)


class EnvironmentManager:
    """Create, inspect, update and remove named multi-app environments."""

    def __init__(
        self,
        clone_service: Any | None = None,
        state_manager: StateManager | None = None,
    ):
        self.clone_service = clone_service or BlockingCloneBackend(state_manager)
        self.state_manager = state_manager or self.clone_service.state_manager

    @staticmethod
    def app_key_for_bundle_id(bundle_id: str) -> str:
        return app_key_for_bundle_id(bundle_id)

    @staticmethod
    def app_for_key(key: str) -> EnvironmentApp | None:
        return app_for_key(key)

    def available_apps(self) -> list[EnvironmentApp]:
        return list(KNOWN_APPS)

    def list_environments(self) -> list[EnvironmentInfo]:
        records = self.state_manager.load()
        grouped: dict[str, list[CloneRecord]] = {}
        for record in records:
            if record.env_group:
                grouped.setdefault(record.env_group, []).append(record)

        order = {app.key: index for index, app in enumerate(KNOWN_APPS)}
        environments: list[EnvironmentInfo] = []
        for name, group in grouped.items():
            group.sort(
                key=lambda record: (
                    order.get(app_key_for_bundle_id(record.bundle_id), len(order)),
                    record.clone_name.lower(),
                )
            )
            environments.append(
                EnvironmentInfo(
                    name=name,
                    env_dir=self._resolve_env_dir(group),
                    records=group,
                )
            )
        environments.sort(key=lambda env: env.name.lower())
        return environments

    def records_for(self, name: str) -> list[CloneRecord]:
        return [record for record in self.state_manager.load() if record.env_group == name]

    def environment(self, name: str) -> EnvironmentInfo | None:
        for env in self.list_environments():
            if env.name == name:
                return env
        return None

    def _resolve_env_dir(self, records: Iterable[CloneRecord]) -> Path:
        for record in records:
            if getattr(record, "env_dir", ""):
                return Path(record.env_dir)
        first = next(iter(records), None)
        if first is not None:
            return Path(first.data_dir).parent
        return DEFAULT_DATA_DIR / "Environments"

    def app_path_for_clone(self, app: EnvironmentApp, name: str) -> Path:
        return DEFAULT_APPS_DIR / f"{app.clone_prefix}-{name}.app"

    async def create_environment(
        self,
        name: str,
        app_keys: Iterable[str],
        on_progress: ProgressCallback | None = None,
        clone_names: dict[str, str] | None = None,
        env_overrides: dict[str, dict[str, str]] | None = None,
    ) -> list[CloneRecord]:
        validate_clone_name(name)
        selected_keys = set(app_keys)
        selected = [app for app in KNOWN_APPS if app.key in selected_keys]
        if not selected:
            raise ValueError("Select at least one app.")

        env_dir = DEFAULT_DATA_DIR / "Environments" / name
        records = self.state_manager.load()
        existing_bundle_ids = {
            record.new_bundle_id for record in records if record.new_bundle_id
        }
        existing_by_key: dict[str, CloneRecord] = {}
        for record in records:
            if record.env_group != name:
                continue
            key = app_key_for_bundle_id(record.bundle_id)
            if key:
                existing_by_key[key] = record

        chrome_def = app_for_key("chrome")
        chrome_existing = existing_by_key.get("chrome")
        if chrome_existing is not None:
            chrome_path = Path(chrome_existing.dest_path)
        elif chrome_def is not None:
            chrome_path = self.app_path_for_clone(chrome_def, name)
        else:
            chrome_path = DEFAULT_APPS_DIR / f"Chrome-{name}.app"

        requested_names = clone_names or {}
        used_names = {record.clone_name for record in records}
        plans: dict[str, tuple[str, Path]] = {}
        for app in selected:
            if app.key in existing_by_key:
                continue
            source_path = app.installed_path
            if source_path is None:
                raise ValueError(f"{app.label} is not installed.")

            clone_name = (requested_names.get(app.key) or "").strip()
            if not clone_name:
                clone_name = f"{app.clone_prefix}-{name}"
            validate_clone_name(clone_name)
            if clone_name in used_names:
                raise ValueError(f"A clone named {clone_name!r} already exists.")
            dest_path = DEFAULT_APPS_DIR / f"{clone_name}.app"
            if dest_path.exists():
                raise ValueError(f"A clone bundle already exists at {dest_path}.")
            used_names.add(clone_name)
            plans[app.key] = (clone_name, dest_path)

        created: list[CloneRecord] = []
        total = len(selected)
        for index, app in enumerate(selected, start=1):
            if on_progress:
                on_progress(index, total, app, "checking")

            existing_record = existing_by_key.get(app.key)
            if existing_record is not None:
                if on_progress:
                    on_progress(index, total, app, "existing")
                if app.key == "chrome":
                    chrome_path = Path(existing_record.dest_path)
                continue

            source_path = app.installed_path
            if source_path is None:
                raise ValueError(f"{app.label} is not installed.")
            clone_name, dest_path = plans[app.key]

            info = AppInspector.inspect(source_path)
            recipe = RecipeLoader.match(info.bundle_id, app_path=source_path)
            if app.key != "chrome":
                recipe.environment_injection = {
                    **recipe.environment_injection,
                    "TWINSPACE_BROWSER_APP_PATH": str(chrome_path),
                }
            overrides = (env_overrides or {}).get(app.key, {})
            for key, value in overrides.items():
                recipe.environment_injection[normalize_legacy_env_key(key)] = value

            data_dir = env_dir / ("Browser" if app.key == "chrome" else clone_name)
            new_bundle_id = AppInspector.resolve_bundle_id(
                info.bundle_id,
                clone_name=clone_name,
                existing_bundle_ids=existing_bundle_ids,
            )
            task = CloneTask(
                source=info,
                dest_path=dest_path,
                data_dir=data_dir,
                recipe=recipe,
                clone_name=clone_name,
                new_bundle_id=new_bundle_id,
                display_name=clone_name,
                env_group=name,
                env_dir=env_dir,
                injection_strategy=getattr(recipe, "injection_strategy", "auto"),
            )

            if on_progress:
                on_progress(index, total, app, "creating")
            logger.info(
                "Creating environment app: env=%s app=%s clone=%s dest=%s",
                name,
                app.label,
                clone_name,
                dest_path,
            )
            record = await self.clone_service.create_clone(task)
            if overrides:
                record.env_overrides = {
                    normalize_legacy_env_key(key): value
                    for key, value in overrides.items()
                }
                self.state_manager.add(record)
            created.append(record)
            existing_by_key[app.key] = record
            existing_bundle_ids.add(new_bundle_id)
            if app.key == "chrome":
                chrome_path = dest_path
            if on_progress:
                on_progress(index, total, app, "created")

        return created

    async def remove_environment(self, name: str, with_data: bool) -> list[str]:
        records = self.records_for(name)
        if not records:
            raise ValueError(f"Environment {name!r} not found.")
        if any(is_clone_running(record.dest_path) for record in records):
            raise RuntimeError(f"Please quit all apps in {name!r} before removing the environment.")

        order = {app.key: index for index, app in enumerate(KNOWN_APPS)}
        records.sort(
            key=lambda record: order.get(app_key_for_bundle_id(record.bundle_id), len(order)),
            reverse=True,
        )
        errors: list[str] = []
        for record in records:
            try:
                await self.clone_service.remove_clone(record.clone_name, with_data=with_data)
            except Exception as exc:
                logger.error("Failed to remove %s: %s", record.clone_name, exc)
                errors.append(f"{record.clone_name}: {exc}")
        return errors

    async def update_environment(
        self,
        name: str,
        app_keys: Iterable[str] | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> list[str]:
        records = self.records_for(name)
        if not records:
            raise ValueError(f"Environment {name!r} not found.")
        selected_keys = set(app_keys) if app_keys is not None else None
        targets = [
            record
            for record in records
            if selected_keys is None
            or app_key_for_bundle_id(record.bundle_id) in selected_keys
        ]
        if not targets:
            raise ValueError("No matching apps in this environment.")
        if any(is_clone_running(record.dest_path) for record in targets):
            raise RuntimeError(f"Please quit all apps in {name!r} before updating.")

        order = {app.key: index for index, app in enumerate(KNOWN_APPS)}
        targets.sort(
            key=lambda record: order.get(app_key_for_bundle_id(record.bundle_id), len(order))
        )
        errors: list[str] = []
        total = len(targets)
        for index, record in enumerate(targets, start=1):
            app = app_for_key(app_key_for_bundle_id(record.bundle_id))
            if on_progress and app is not None:
                on_progress(index, total, app, "updating")
            try:
                await self.clone_service.update_clone(record.clone_name)
                if on_progress and app is not None:
                    on_progress(index, total, app, "updated")
            except Exception as exc:
                logger.error("Failed to update %s: %s", record.clone_name, exc)
                errors.append(f"{record.clone_name}: {exc}")
                if on_progress and app is not None:
                    on_progress(index, total, app, "failed")
        return errors

    def export_environment(self, name: str) -> EnvironmentSpec:
        env = self.environment(name)
        if env is None:
            raise ValueError(f"Environment {name!r} not found.")
        apps: list[EnvironmentAppSpec] = []
        for record in env.records:
            key = app_key_for_bundle_id(record.bundle_id)
            if not key:
                continue
            apps.append(
                EnvironmentAppSpec(
                    key=key,
                    clone_name=record.clone_name,
                    env_overrides=dict(getattr(record, "env_overrides", {}) or {}),
                )
            )
        if not apps:
            raise ValueError(f"Environment {name!r} has no recognized apps.")
        return EnvironmentSpec(name=env.name, apps=apps)

    async def import_environment(
        self,
        spec: EnvironmentSpec,
        target_name: str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> list[CloneRecord]:
        target = target_name or spec.name
        existing = self.environment(target)
        existing_keys = existing.app_keys if existing else set()
        selected = [app for app in spec.apps if app.key not in existing_keys]
        if not selected:
            return []
        clone_names = {
            app.key: app.clone_name for app in selected if app.clone_name
        }
        overrides = {
            app.key: app.env_overrides for app in selected if app.env_overrides
        }
        created = await self.create_environment(
            target,
            [app.key for app in selected],
            on_progress=on_progress,
            clone_names=clone_names,
            env_overrides=overrides,
        )

        # Imported overrides also apply when an app already existed locally.
        if existing is not None:
            by_key = {
                app_key_for_bundle_id(record.bundle_id): record
                for record in self.records_for(target)
            }
            for app in spec.apps:
                if not app.env_overrides:
                    continue
                record = by_key.get(app.key)
                if record is not None:
                    record.env_overrides.update(
                        {
                            normalize_legacy_env_key(key): value
                            for key, value in app.env_overrides.items()
                        }
                    )
                    self.state_manager.add(record)
        return created

    def backup_environment(
        self,
        name: str,
        output_path: Path | None = None,
    ) -> Path:
        records = self.records_for(name)
        if not records:
            raise ValueError(f"Environment {name!r} not found.")
        if any(is_clone_running(record.dest_path) for record in records):
            raise RuntimeError(f"Please quit all apps in {name!r} before backing up.")
        return create_backup(name, records, output_path)

    def restore_environment(
        self,
        name: str,
        archive_path: Path,
        on_progress=None,
    ) -> tuple[list[str], list[str], Path]:
        records = self.records_for(name)
        if not records:
            raise ValueError(f"Environment {name!r} not found.")
        if any(is_clone_running(record.dest_path) for record in records):
            raise RuntimeError(f"Please quit all apps in {name!r} before restoring.")

        safety_backup = create_backup(name, records)
        restored, errors = restore_backup(archive_path, records, on_progress=on_progress)
        return restored, errors, safety_backup

    def open_environment(self, name: str, app_keys: Iterable[str] | None = None) -> list[str]:
        selected = set(app_keys) if app_keys is not None else None
        records = self.records_for(name)
        order = {app.key: index for index, app in enumerate(KNOWN_APPS)}
        records.sort(
            key=lambda record: order.get(app_key_for_bundle_id(record.bundle_id), len(order))
        )
        errors: list[str] = []
        for record in records:
            key = app_key_for_bundle_id(record.bundle_id)
            if selected is not None and key not in selected:
                continue
            path = Path(record.dest_path)
            if not path.exists():
                errors.append(f"{record.clone_name}: bundle not found")
                continue
            try:
                subprocess.Popen(["open", "-n", str(path)])
            except Exception as exc:
                errors.append(f"{record.clone_name}: {exc}")
        return errors
