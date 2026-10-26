import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
import toga

from twinspace.core.environments import apps as environment_apps
from twinspace.core.environments import manager as environment_manager_module
from twinspace.core.models import AppInfo
from twinspace.core.state import CloneRecord, StateManager
from twinspace.gui.components.app_tile import AppTile
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

    async def fake_create(name, keys, on_progress=None, clone_names=None, browser_path=None):
        captured["name"] = name
        captured["keys"] = list(keys)
        captured["clone_names"] = clone_names
        captured["browser_path"] = browser_path
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
    # Default browser binding mode passes no external browser override.
    assert captured["browser_path"] is None


def _label_texts(widget) -> list[str]:
    texts = [widget.text] if isinstance(widget, toga.Label) else []
    for child in getattr(widget, "children", []):
        texts.extend(_label_texts(child))
    return texts


def _app_tiles(widget) -> list[AppTile]:
    tiles = [widget] if isinstance(widget, AppTile) else []
    for child in getattr(widget, "children", []):
        tiles.extend(_app_tiles(child))
    return tiles


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

    tiles = {tile.clone_name: tile for tile in _app_tiles(view.list_box)}
    assert tiles["Chrome-work"].label_text == "Google Chrome"
    assert tiles["ZCode-work"].label_text == "ZCode"


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


def test_environment_create_window_browser_modes(toga_app, tmp_path):
    service = EnvironmentService(state_manager=StateManager(state_file=tmp_path / "c.yaml"))
    window = EnvironmentCreateWindow(environment_service=service)

    # Default mode: environment Chrome, no external override.
    assert window._resolve_browser_path() == (None, None)

    # System default mode: also no override.
    window.select_browser_mode.value = "System default browser (no binding)"
    assert window._resolve_browser_path() == (None, None)

    # External mode with an empty path -> validation error key.
    window.select_browser_mode.value = "External browser (.app)"
    assert window._resolve_browser_path() == (None, "env_browser_invalid")

    # External mode with a non-.app path -> validation error key.
    window.input_browser_path.value = str(tmp_path / "NotABrowser")
    assert window._resolve_browser_path() == (None, "env_browser_invalid")

    # External mode with a valid .app bundle -> resolved path.
    browser = tmp_path / "External Browser.app"
    browser.mkdir()
    window.input_browser_path.value = str(browser)
    resolved, error = window._resolve_browser_path()
    assert error is None
    assert resolved == browser


def test_environment_list_export_restore_import(toga_app, tmp_path):
    service = EnvironmentService(state_manager=StateManager(state_file=tmp_path / "clones.yaml"))
    service.state_manager.add(
        CloneRecord(
            clone_name="ZCode-phone1",
            source_app="ZCode",
            source_path="/Applications/ZCode.app",
            bundle_id="dev.zcode.app",
            strategy="hard_clone",
            dest_path=str(tmp_path / "ZCode-phone1.app"),
            data_dir=str(tmp_path / "env" / "ZCode-phone1"),
            created_at="2026-10-25T00:00:00Z",
            env_group="phone1",
            env_dir=str(tmp_path / "env"),
        )
    )
    view = EnvironmentListView(environment_service=service)
    asyncio.run(view.refresh_environments())

    # Secondary top-bar action (import) and per-card secondary row exist.
    assert view.top_bar.btn_secondary is not None

    mock_app = MagicMock()
    mock_app.main_window.dialog = AsyncMock(return_value=tmp_path / "phone1.yaml")
    mock_app.main_window.info_dialog = AsyncMock()
    mock_app.main_window.error_dialog = AsyncMock()
    mock_app.main_window.confirm_dialog = AsyncMock(return_value=True)
    view.app_instance = mock_app

    # Export writes the portable template next to the chosen path.
    target = tmp_path / "phone1.yaml"
    mock_app.main_window.dialog = AsyncMock(return_value=target)
    asyncio.run(view._export_template("phone1"))
    assert target.exists()
    assert "version: 1" in target.read_text(encoding="utf-8")
    mock_app.main_window.info_dialog.assert_awaited_once()

    # Restore: confirm accepted -> service called, safety info shown.
    calls = {}
    service.restore_environment = lambda name, archive: calls.update(
        name=name, archive=archive
    ) or (["ZCode-phone1"], [], Path("/safety.tar.gz"))
    archive = tmp_path / "backup.tar.gz"
    mock_app.main_window.dialog = AsyncMock(return_value=archive)
    asyncio.run(view._restore_backup("phone1"))
    assert calls == {"name": "phone1", "archive": archive}
    mock_app.main_window.info_dialog.assert_awaited()

    # Import: confirm accepted -> import_environment receives the parsed spec.
    yaml_file = tmp_path / "template.yaml"
    yaml_file.write_text(
        "version: 1\nname: phone2\napps:\n  - key: chrome\n    clone_name: Chrome-phone2\n",
        encoding="utf-8",
    )
    imported = {}

    async def fake_import(spec, target_name=None, on_progress=None):
        imported["spec"] = spec
        return ["Chrome-phone2"]

    service.import_environment = fake_import
    mock_app.main_window.dialog = AsyncMock(return_value=yaml_file)
    asyncio.run(view.on_import_template())
    assert imported["spec"].name == "phone2"
    mock_app.main_window.info_dialog.assert_awaited()


def test_environment_card_marks_running_apps(toga_app, tmp_path):
    state = StateManager(state_file=tmp_path / "clones.yaml")
    for name, source, bundle in (
        ("Chrome-work", "Google Chrome", "com.google.Chrome"),
        ("ZCode-work", "ZCode", "dev.zcode.app"),
    ):
        state.add(
            CloneRecord(
                clone_name=name,
                source_app=source,
                source_path=f"/Applications/{source}.app",
                bundle_id=bundle,
                strategy="hard_clone",
                dest_path=str(tmp_path / f"{name}.app"),
                data_dir=str(tmp_path / "env" / name),
                created_at="2026-10-26T00:00:00Z",
                env_group="phone1",
                env_dir=str(tmp_path / "env"),
            )
        )

    service = EnvironmentService(state_manager=state)
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._running_clones = {"Chrome-work"}
    view._render()

    tiles = {tile.clone_name: tile for tile in _app_tiles(view.list_box)}
    assert tiles["Chrome-work"].running is True
    assert tiles["ZCode-work"].running is False
    assert tiles["Chrome-work"].status_label.text != ""
    assert tiles["ZCode-work"].status_label.text == ""


def test_environment_toggle_app_opens_and_quits_selected_app(toga_app, tmp_path):
    service = EnvironmentService(state_manager=StateManager(state_file=tmp_path / "clones.yaml"))
    view = EnvironmentListView(environment_service=service)
    calls = []
    service.open_environment = lambda name, keys=None: calls.append(("open", name, keys)) or []
    service.quit_environment = lambda name, keys=None: calls.append(("quit", name, keys)) or []

    async def noop_refresh():
        return None

    view.refresh_environments = noop_refresh

    asyncio.run(view._toggle_app("phone1", "chrome", True))
    asyncio.run(view._toggle_app("phone1", "zcode", False))

    assert calls == [
        ("quit", "phone1", ["chrome"]),
        ("open", "phone1", ["zcode"]),
    ]
