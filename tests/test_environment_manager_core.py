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


def test_browser_binding_modes(tmp_path, monkeypatch):
    """Chrome-in-env binds both keys; no chrome binds nothing; --browser wins."""
    import asyncio

    apps_root = tmp_path / "Applications"
    monkeypatch.setattr(manager_module, "DEFAULT_APPS_DIR", apps_root)
    monkeypatch.setattr(manager_module, "DEFAULT_DATA_DIR", tmp_path / "Data")
    monkeypatch.setattr(
        manager_module,
        "KNOWN_APPS",
        (
            EnvironmentApp("chrome", "Google Chrome", ("com.google.Chrome",), apps_root / "Google Chrome.app", "Chrome"),
            EnvironmentApp("zcode", "ZCode", ("dev.zcode.app",), apps_root / "ZCode.app", "ZCode"),
        ),
    )
    for app_dir in (apps_root / "Google Chrome.app", apps_root / "ZCode.app"):
        app_dir.mkdir(parents=True)

    def run_env(name, app_keys, browser_path=None, overrides=None):
        state_file = tmp_path / f"{name}-clones.yaml"
        state = StateManager(state_file=state_file)
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
                    created_at="2026-10-25T00:00:00Z",
                    env_group=task.env_group or "",
                    env_dir=str(task.env_dir) if task.env_dir else "",
                )
                state.add(record)
                return record

        def fake_inspect(app_path):
            app_path = Path(app_path)
            bundle_id = "com.google.Chrome" if "Chrome" in app_path.name else "dev.zcode.app"
            from twinspace.core.models import AppInfo as _AppInfo

            return _AppInfo(
                path=app_path,
                bundle_id=bundle_id,
                app_name=app_path.stem,
                executable=app_path / "Contents/MacOS/app",
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
            asyncio.run(
                manager.create_environment(
                    name,
                    app_keys,
                    clone_names={key: f"App-{key}-{name}" for key in app_keys},
                    env_overrides=overrides,
                    browser_path=browser_path,
                )
            )
        return state

    # 1. Chrome in the env: non-chrome apps get both keys, persisted.
    state = run_env("withchrome", ["chrome", "zcode"])
    zc = state.get("App-zcode-withchrome")
    assert zc.env_overrides["TWINSPACE_BROWSER_APP_PATH"].endswith("App-chrome-withchrome.app")
    assert zc.env_overrides["TWINSPACE_BROWSER_DATA_DIR"].endswith("Browser")

    # 2. No chrome, no --browser: no binding at all (links open system default).
    state = run_env("nochrio", ["zcode"])
    zc = state.get("App-zcode-nochrio")
    assert "TWINSPACE_BROWSER_APP_PATH" not in zc.env_overrides
    assert "TWINSPACE_BROWSER_DATA_DIR" not in zc.env_overrides

    # 3. External browser: binds to the given .app with the env-owned profile.
    external = tmp_path / "External Browser.app"
    external.mkdir()
    state = run_env("extbrowser", ["zcode"], browser_path=external)
    zc = state.get("App-zcode-extbrowser")
    assert zc.env_overrides["TWINSPACE_BROWSER_APP_PATH"] == str(external)
    assert zc.env_overrides["TWINSPACE_BROWSER_DATA_DIR"].endswith("Browser")

    # 4. Explicit user override wins over the automatic binding.
    state = run_env(
        "override",
        ["chrome", "zcode"],
        overrides={"zcode": {"TWINSPACE_BROWSER_DATA_DIR": "/custom/profile"}},
    )
    zc = state.get("App-zcode-override")
    assert zc.env_overrides["TWINSPACE_BROWSER_DATA_DIR"] == "/custom/profile"


def _environment_with_two_apps(tmp_path):
    state = StateManager(state_file=tmp_path / "clones.yaml")
    for name, source, bundle, dest in (
        ("Chrome-work", "Google Chrome", "com.google.Chrome", "Chrome-work.app"),
        ("ZCode-work", "ZCode", "dev.zcode.app", "ZCode-work.app"),
    ):
        state.add(
            CloneRecord(
                clone_name=name,
                source_app=source,
                source_path=f"/Applications/{source}.app",
                bundle_id=bundle,
                strategy="hard_clone",
                dest_path=str(tmp_path / dest),
                data_dir=str(tmp_path / "env" / name),
                created_at="2026-10-26T00:00:00Z",
                env_group="phone1",
                env_dir=str(tmp_path / "env"),
            )
        )
    return EnvironmentManager(state_manager=state)


def test_quit_environment_stops_only_selected_apps(tmp_path):
    manager = _environment_with_two_apps(tmp_path)
    stopped = []

    with patch.object(
        manager_module, "quit_clone", lambda path: stopped.append(str(path)) or True
    ):
        errors = manager.quit_environment("phone1", ["zcode"])

    assert errors == []
    assert len(stopped) == 1
    assert stopped[0].endswith("ZCode-work.app")


def test_quit_environment_reports_still_running_apps(tmp_path):
    manager = _environment_with_two_apps(tmp_path)

    with patch.object(manager_module, "quit_clone", lambda path: False):
        errors = manager.quit_environment("phone1", ["chrome"])

    assert errors == ["Chrome-work: still running"]


def test_running_clones_forwards_environment_records(tmp_path):
    manager = _environment_with_two_apps(tmp_path)
    seen = []

    def fake_running(records):
        seen.extend(record.clone_name for record in records)
        return {"ZCode-work"}

    with patch.object(manager_module, "running_clone_names", fake_running):
        assert manager.running_clones("phone1") == {"ZCode-work"}

    assert sorted(seen) == ["Chrome-work", "ZCode-work"]
