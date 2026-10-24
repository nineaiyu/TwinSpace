"""Core environment manager import behavior."""

import asyncio
from pathlib import Path
from unittest.mock import patch

from twinspace.core.environments import apps as apps_module
from twinspace.core.environments import manager as manager_module
from twinspace.core.environments.apps import EnvironmentApp
from twinspace.core.environments.manager import EnvironmentManager
from twinspace.core.environments.spec import EnvironmentAppSpec, EnvironmentSpec
from twinspace.core.models import AppInfo
from twinspace.core.state import CloneRecord, StateManager
from twinspace.recipes.models import Recipe


def test_import_environment_creates_apps_and_overrides(tmp_path):
    chrome_dir = tmp_path / "Applications" / "Chrome.app"
    zcode_dir = tmp_path / "Applications" / "ZCode.app"
    chrome_dir.mkdir(parents=True)
    zcode_dir.mkdir(parents=True)
    chrome = EnvironmentApp("chrome", "Google Chrome", ("com.google.Chrome",), chrome_dir, "Chrome")
    zcode = EnvironmentApp("zcode", "ZCode", ("dev.zcode.app",), zcode_dir, "ZCode")
    with patch.object(apps_module, "KNOWN_APPS", (chrome, zcode)), patch.object(
        manager_module, "KNOWN_APPS", (chrome, zcode)
    ), patch.object(manager_module, "DEFAULT_APPS_DIR", tmp_path / "Apps"), patch.object(
        manager_module, "DEFAULT_DATA_DIR", tmp_path / "Data"
    ):
        state = StateManager(state_file=tmp_path / "clones.yaml")
        tasks = []

        class FakeCloneService:
            def __init__(self):
                self.state_manager = state

            async def create_clone(self, task):
                tasks.append(task)
                record = CloneRecord(
                    clone_name=task.clone_name,
                    source_app=task.source.app_name,
                    source_path=str(task.source.path),
                    bundle_id=task.source.bundle_id,
                    strategy=task.recipe.strategy,
                    dest_path=str(task.dest_path),
                    data_dir=str(task.data_dir),
                    created_at="2026-10-24T00:00:00Z",
                    env_group=task.env_group or "",
                    env_dir=str(task.env_dir) if task.env_dir else "",
                )
                state.add(record)
                return record

        def fake_inspect(path):
            path = Path(path)
            is_chrome = path.name == "Chrome.app"
            return AppInfo(
                path=path,
                bundle_id="com.google.Chrome" if is_chrome else "dev.zcode.app",
                app_name="Google Chrome" if is_chrome else "ZCode",
                executable=path / "Contents/MacOS/app",
                has_sandbox=False,
            )

        def fake_match(bundle_id, app_path=None):
            return Recipe(
                bundle_id=bundle_id,
                app_name="App",
                strategy="soft_clone" if bundle_id == "com.google.Chrome" else "hard_clone",
            )

        with patch.object(manager_module.AppInspector, "inspect", side_effect=fake_inspect), patch.object(
            manager_module.RecipeLoader, "match", side_effect=fake_match
        ):
            manager = EnvironmentManager(clone_service=FakeCloneService(), state_manager=state)
            spec = EnvironmentSpec(
                name="phone1",
                apps=[
                    EnvironmentAppSpec("chrome", "Chrome-custom"),
                    EnvironmentAppSpec(
                        "zcode",
                        "ZCode-custom",
                        {"TWINSPACE_BROWSER_APP_PATH": "/tmp/Chrome-custom.app"},
                    ),
                ],
            )
            created = asyncio.run(manager.import_environment(spec))

    assert [record.clone_name for record in created] == ["Chrome-custom", "ZCode-custom"]
    assert [task.clone_name for task in tasks] == ["Chrome-custom", "ZCode-custom"]
    assert tasks[1].recipe.environment_injection["TWINSPACE_BROWSER_APP_PATH"] == "/tmp/Chrome-custom.app"
    assert state.get("ZCode-custom").env_overrides["TWINSPACE_BROWSER_APP_PATH"] == "/tmp/Chrome-custom.app"
