import asyncio
from pathlib import Path

import pytest
import toga

from twinspace.core.environments import apps as environment_apps
from twinspace.core.environments import manager as environment_manager_module
from twinspace.core.models import AppInfo
from twinspace.core.state import CloneRecord, StateManager
from twinspace.gui.services.environment_service import EnvironmentApp, EnvironmentService
from twinspace.gui.views.environment_list import EnvironmentListView
from twinspace.gui.windows.environment_create import EnvironmentCreateWindow
from twinspace.recipes.models import Recipe


def test_environment_view_lists_and_creates_window(toga_app, tmp_path):
    service = EnvironmentService(state_manager=StateManager(state_file=tmp_path / "clones.yaml"))
    view = EnvironmentListView(environment_service=service)
    assert view.top_bar is not None
    assert view.top_bar.btn_action is not None

    window = EnvironmentCreateWindow(environment_service=service)
    assert "chrome" in window._app_switches
    assert window.btn_create is not None


def test_environment_service_groups_records(toga_app, tmp_path):
    state = StateManager(state_file=tmp_path / "clones.yaml")
    state.add(
        CloneRecord(
            clone_name="Chrome-phone1",
            source_app="Google Chrome",
            source_path="/Applications/Google Chrome.app",
            bundle_id="com.google.Chrome",
            strategy="soft_clone",
            dest_path=str(tmp_path / "Chrome-phone1.app"),
            data_dir=str(tmp_path / "env" / "Browser"),
            created_at="2026-08-19T00:00:00Z",
            env_group="phone1",
            env_dir=str(tmp_path / "env"),
        )
    )
    state.add(
        CloneRecord(
            clone_name="ZCode-phone1",
            source_app="ZCode",
            source_path="/Applications/ZCode.app",
            bundle_id="dev.zcode.app",
            strategy="hard_clone",
            dest_path=str(tmp_path / "ZCode-phone1.app"),
            data_dir=str(tmp_path / "env" / "ZCode-phone1"),
            created_at="2026-08-19T00:00:01Z",
            env_group="phone1",
            env_dir=str(tmp_path / "env"),
        )
    )
    state.add(
        CloneRecord(
            clone_name="Standalone",
            source_app="Other",
            source_path="/Applications/Other.app",
            bundle_id="com.example.other",
            strategy="hard_clone",
            dest_path=str(tmp_path / "Standalone.app"),
            data_dir=str(tmp_path / "other"),
            created_at="2026-08-19T00:00:02Z",
        )
    )

    service = EnvironmentService(state_manager=state)
    environments = service.list_environments()
    assert [env.name for env in environments] == ["phone1"]
    assert environments[0].env_dir == tmp_path / "env"
    assert [record.clone_name for record in environments[0].records] == [
        "Chrome-phone1",
        "ZCode-phone1",
    ]
    assert environments[0].app_keys == {"chrome", "zcode"}


def _environment_service_with_fakes(tmp_path, monkeypatch):
    chrome_dir = tmp_path / "Applications" / "Chrome.app"
    zcode_dir = tmp_path / "Applications" / "ZCode.app"
    chrome_dir.mkdir(parents=True)
    zcode_dir.mkdir(parents=True)
    chrome_app = EnvironmentApp(
        "chrome", "Google Chrome", ("com.google.Chrome",), chrome_dir, "Chrome"
    )
    zcode_app = EnvironmentApp("zcode", "ZCode", ("dev.zcode.app",), zcode_dir, "ZCode")
    monkeypatch.setattr(environment_apps, "KNOWN_APPS", (chrome_app, zcode_app))
    monkeypatch.setattr(environment_manager_module, "KNOWN_APPS", (chrome_app, zcode_app))
    monkeypatch.setattr(environment_manager_module, "DEFAULT_APPS_DIR", tmp_path / "Apps")
    monkeypatch.setattr(
        environment_manager_module,
        "DEFAULT_DATA_DIR",
        tmp_path / "Data",
    )

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
                created_at="2026-08-19T00:00:00Z",
                new_bundle_id=task.new_bundle_id,
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
            executable=path / "Contents" / "MacOS" / ("Chrome" if is_chrome else "ZCode"),
            has_sandbox=False,
        )

    def fake_match(bundle_id, app_path=None):
        is_chrome = bundle_id == "com.google.Chrome"
        return Recipe(
            bundle_id=bundle_id,
            app_name="Google Chrome" if is_chrome else "ZCode",
            strategy="soft_clone" if is_chrome else "hard_clone",
            app_type="chromium" if is_chrome else "electron",
        )

    monkeypatch.setattr(environment_manager_module.AppInspector, "inspect", fake_inspect)
    monkeypatch.setattr(environment_manager_module.RecipeLoader, "match", fake_match)
    service = EnvironmentService(clone_service=FakeCloneService(), state_manager=state)
    return service, tasks


def test_environment_service_creates_chrome_first_and_isolates_data(tmp_path, monkeypatch):
    service, tasks = _environment_service_with_fakes(tmp_path, monkeypatch)

    asyncio.run(service.create_environment("phone1", ["zcode", "chrome"]))

    assert [task.clone_name for task in tasks] == ["Chrome-phone1", "ZCode-phone1"]
    env_dir = tmp_path / "Data" / "Environments" / "phone1"
    assert tasks[0].data_dir == env_dir / "Browser"
    assert tasks[0].recipe.strategy == "soft_clone"
    assert tasks[0].env_group == "phone1"
    assert tasks[1].data_dir == env_dir / "ZCode-phone1"
    assert tasks[1].recipe.strategy == "hard_clone"
    assert tasks[1].recipe.environment_injection["TWINSPACE_BROWSER_APP_PATH"] == str(
        tmp_path / "Apps" / "Chrome-phone1.app"
    )
    assert service.environment("phone1") is not None


def test_environment_service_uses_custom_clone_names(tmp_path, monkeypatch):
    service, tasks = _environment_service_with_fakes(tmp_path, monkeypatch)

    asyncio.run(
        service.create_environment(
            "phone1",
            ["chrome", "zcode"],
            clone_names={"chrome": "Chrome-acct1", "zcode": "ZCode-acct1"},
        )
    )

    assert [task.clone_name for task in tasks] == ["Chrome-acct1", "ZCode-acct1"]
    env_dir = tmp_path / "Data" / "Environments" / "phone1"
    assert tasks[0].data_dir == env_dir / "Browser"
    assert tasks[1].data_dir == env_dir / "ZCode-acct1"
    assert tasks[1].display_name == "ZCode-acct1"
    assert tasks[1].recipe.environment_injection["TWINSPACE_BROWSER_APP_PATH"] == str(
        tmp_path / "Apps" / "Chrome-acct1.app"
    )
    assert {record.clone_name for record in service.environment("phone1").records} == {
        "Chrome-acct1",
        "ZCode-acct1",
    }


def test_environment_service_rejects_duplicate_custom_clone_names(tmp_path, monkeypatch):
    service, tasks = _environment_service_with_fakes(tmp_path, monkeypatch)

    with pytest.raises(ValueError, match="already exists"):
        asyncio.run(
            service.create_environment(
                "phone1",
                ["chrome", "zcode"],
                clone_names={"chrome": "SameName", "zcode": "SameName"},
            )
        )
    assert tasks == []


def test_environment_create_window_syncs_clone_names(toga_app, tmp_path, monkeypatch):
    service, _ = _environment_service_with_fakes(tmp_path, monkeypatch)
    window = EnvironmentCreateWindow(environment_service=service)

    assert window._name_inputs["chrome"].value == "Chrome"
    assert window._name_inputs["zcode"].value == "ZCode"

    window.input_name.value = "phone1"
    assert window._name_inputs["chrome"].value == "Chrome-phone1"
    assert window._name_inputs["zcode"].value == "ZCode-phone1"

    window._name_inputs["zcode"].value = "ZCode-work"
    window.input_name.value = "phone2"
    assert window._name_inputs["zcode"].value == "ZCode-work"
    assert window._name_inputs["chrome"].value == "Chrome-phone2"


def test_environment_create_window_passes_custom_names(toga_app, tmp_path, monkeypatch):
    service, _ = _environment_service_with_fakes(tmp_path, monkeypatch)
    window = EnvironmentCreateWindow(environment_service=service)
    window.input_name.value = "phone1"
    window._name_inputs["chrome"].value = "ChromeAcct"
    window._name_inputs["zcode"].value = "ZCodeAcct"

    captured = {}

    async def fake_create(name, keys, on_progress=None, clone_names=None):
        captured["name"] = name
        captured["keys"] = list(keys)
        captured["clone_names"] = clone_names
        return []

    async def noop_dialog(*args, **kwargs):
        return None

    service.create_environment = fake_create
    window.info_dialog = noop_dialog
    window.close = lambda: None

    asyncio.run(window._on_create())

    assert captured["name"] == "phone1"
    assert captured["keys"] == ["chrome", "zcode"]
    assert captured["clone_names"] == {"chrome": "ChromeAcct", "zcode": "ZCodeAcct"}


def _label_texts(widget) -> list[str]:
    texts = [widget.text] if isinstance(widget, toga.Label) else []
    for child in getattr(widget, "children", []):
        texts.extend(_label_texts(child))
    return texts


def test_environment_card_shows_clone_names(toga_app, tmp_path):
    state = StateManager(state_file=tmp_path / "clones.yaml")
    state.add(
        CloneRecord(
            clone_name="Chrome-work",
            source_app="Google Chrome",
            source_path="/Applications/Google Chrome.app",
            bundle_id="com.google.Chrome",
            strategy="soft_clone",
            dest_path=str(tmp_path / "Chrome-work.app"),
            data_dir=str(tmp_path / "env" / "Browser"),
            created_at="2026-08-19T00:00:00Z",
            env_group="phone1",
            env_dir=str(tmp_path / "env"),
        )
    )
    state.add(
        CloneRecord(
            clone_name="ZCode-work",
            source_app="ZCode",
            source_path="/Applications/ZCode.app",
            bundle_id="dev.zcode.app",
            strategy="hard_clone",
            dest_path=str(tmp_path / "ZCode-work.app"),
            data_dir=str(tmp_path / "env" / "ZCode-work"),
            created_at="2026-08-19T00:00:01Z",
            env_group="phone1",
            env_dir=str(tmp_path / "env"),
        )
    )

    service = EnvironmentService(state_manager=state)
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()

    texts = _label_texts(view.list_box)
    assert any("Google Chrome · Chrome-work" in text for text in texts)
    assert any("ZCode · ZCode-work" in text for text in texts)


def test_environment_card_exposes_update_and_backup(toga_app, tmp_path):
    state = StateManager(state_file=tmp_path / "clones.yaml")
    state.add(
        CloneRecord(
            clone_name="ZCode-work",
            source_app="ZCode",
            source_path="/Applications/ZCode.app",
            bundle_id="dev.zcode.app",
            strategy="hard_clone",
            dest_path=str(tmp_path / "ZCode-work.app"),
            data_dir=str(tmp_path / "env" / "ZCode-work"),
            created_at="2026-10-24T00:00:00Z",
            env_group="phone1",
            env_dir=str(tmp_path / "env"),
        )
    )
    service = EnvironmentService(state_manager=state)
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._render()

    button_texts = []

    def collect(widget):
        if isinstance(widget, toga.Button):
            button_texts.append(widget.text)
        for child in getattr(widget, "children", []):
            collect(child)

    collect(view.list_box)
    assert "Update All" in button_texts
    assert "Backup" in button_texts
