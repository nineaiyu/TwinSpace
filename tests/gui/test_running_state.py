"""Running-state detection for environment app tiles.

Electron clones started through a launcher surface in NSWorkspace as an
executable (`…/ZCode-b1.app/Contents/MacOS/ZCode-b1`) or as a nested helper
bundle, which used to make the tile's green dot disappear a second after the
launch even though the app kept running.
"""

from twinspace.core.state import CloneRecord, StateManager
from twinspace.gui.services.app_monitor import enclosing_bundle
from twinspace.gui.services.environment_service import EnvironmentService
from twinspace.gui.views.environment_list import EnvironmentListView


class _FakeMonitor:
    available = True

    def __init__(self, paths):
        self._paths = set(paths)

    def running_paths(self):
        return set(self._paths)


def _environment_state(tmp_path) -> StateManager:
    state = StateManager(state_file=tmp_path / "clones.yaml")
    for name, source, bundle in (
        ("Chrome-phone1", "Google Chrome", "com.google.Chrome"),
        ("ZCode-phone1", "ZCode", "dev.zcode.app"),
        ("WorkBuddy-phone1", "WorkBuddy", "com.workbuddy.app"),
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
                created_at="2026-10-28T00:00:00Z",
                env_group="phone1",
                env_dir=str(tmp_path / "env"),
            )
        )
    return state


def _view(tmp_path) -> EnvironmentListView:
    service = EnvironmentService(state_manager=_environment_state(tmp_path))
    view = EnvironmentListView(environment_service=service)
    view._environments = service.list_environments()
    view._rebuild_path_index()
    view._render()
    return view


def test_enclosing_bundle_folds_executables_and_helpers():
    assert (
        enclosing_bundle("/Apps/ZCode-b1.app/Contents/MacOS/ZCode-b1")
        == "/Apps/ZCode-b1.app"
    )
    assert (
        enclosing_bundle("/Apps/ZCode-b1.app/Contents/Frameworks/ZCode Helper.app")
        == "/Apps/ZCode-b1.app"
    )
    assert enclosing_bundle("/Apps/ZCode-b1.app") == "/Apps/ZCode-b1.app"
    assert enclosing_bundle("") == ""


def test_executable_path_marks_the_clone_as_running(toga_app, tmp_path):
    view = _view(tmp_path)
    record = next(
        item
        for item in view._environments[0].records
        if item.clone_name == "ZCode-phone1"
    )
    view._monitor = _FakeMonitor([f"{record.dest_path}/Contents/MacOS/ZCode-phone1"])

    assert "ZCode-phone1" in (view._snapshot_running_clones() or set())


def test_helper_bundle_marks_the_clone_as_running(toga_app, tmp_path):
    view = _view(tmp_path)
    record = next(
        item
        for item in view._environments[0].records
        if item.clone_name == "ZCode-phone1"
    )
    view._monitor = _FakeMonitor(
        [f"{record.dest_path}/Contents/Frameworks/ZCode Helper.app"]
    )

    assert "ZCode-phone1" in (view._snapshot_running_clones() or set())


def test_missing_snapshot_entry_is_confirmed_against_the_process_table(
    toga_app, tmp_path, monkeypatch
):
    view = _view(tmp_path)
    view._monitor = _FakeMonitor([])
    view._running_clones = {"ZCode-phone1"}
    calls: list[list[str]] = []

    def fake_running(records):
        calls.append([record.clone_name for record in records])
        return {"ZCode-phone1"}

    monkeypatch.setattr(
        "twinspace.gui.views.environment_list.running_clone_names", fake_running
    )

    running = view._snapshot_running_clones() or set()

    assert "ZCode-phone1" in running
    assert calls == [["ZCode-phone1"]]


def test_snapshot_is_not_checked_when_nothing_is_expected(toga_app, tmp_path, monkeypatch):
    view = _view(tmp_path)
    view._monitor = _FakeMonitor([])
    view._running_clones = set()

    monkeypatch.setattr(
        "twinspace.gui.views.environment_list.running_clone_names",
        lambda records: pytest_fail(),
    )

    assert view._snapshot_running_clones() == set()


def pytest_fail():  # pragma: no cover - only reached on a regression
    raise AssertionError("the process table must not be scanned without candidates")
