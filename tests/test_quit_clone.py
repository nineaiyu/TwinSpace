"""Stopping a clone asks the app to quit gracefully, never force-kills it."""

import os
import plistlib
import subprocess
from types import SimpleNamespace

import pytest

from twinspace.core import state as state_module


def _patch_process(
    monkeypatch, *, dies_on: str | None, graceful_ok: bool = True
) -> list[str]:
    """Fake the process table; ``dies_on`` is the action that actually stops it."""
    actions: list[str] = []
    alive = {"value": True}

    def fake_graceful(needle: str) -> bool:
        actions.append("quit-event")
        if dies_on == "quit-event":
            alive["value"] = False
        return graceful_ok

    def fake_signal(needle: str, signal_name: str) -> None:
        actions.append(signal_name)
        if dies_on == signal_name:
            alive["value"] = False

    monkeypatch.setattr(state_module, "is_clone_running", lambda needle: alive["value"])
    monkeypatch.setattr(state_module, "_request_graceful_quit", fake_graceful)
    monkeypatch.setattr(state_module, "_signal_clone", fake_signal)
    monkeypatch.setattr(
        state_module, "_wait_until_stopped", lambda needle, timeout: not alive["value"]
    )
    return actions


def test_quit_clone_uses_a_quit_apple_event(monkeypatch):
    actions = _patch_process(monkeypatch, dies_on="quit-event")

    assert state_module.quit_clone("/Apps/ZCode-b1.app", timeout=0) is True
    assert actions == ["quit-event"]


def test_quit_clone_falls_back_to_sigterm_without_force(monkeypatch):
    actions = _patch_process(monkeypatch, dies_on="-TERM", graceful_ok=False)

    assert state_module.quit_clone("/Apps/Qoder-b2.app", timeout=0) is True
    assert actions == ["quit-event", "-TERM"]


def test_quit_clone_never_force_kills(monkeypatch):
    actions = _patch_process(monkeypatch, dies_on=None)

    assert state_module.quit_clone("/Apps/Stubborn.app", timeout=0) is False
    assert actions == ["quit-event"]
    assert "-KILL" not in actions


def test_quit_clone_is_a_no_op_when_nothing_runs(monkeypatch):
    monkeypatch.setattr(state_module, "is_clone_running", lambda needle: False)
    monkeypatch.setattr(
        state_module, "_request_graceful_quit", lambda needle: pytest.fail("no quit event")
    )
    monkeypatch.setattr(
        state_module, "_signal_clone", lambda needle, signal_name: pytest.fail("no signal")
    )

    assert state_module.quit_clone("/Apps/Trae-b2.app") is True


def _fake_process_table(monkeypatch, rows, executable_paths) -> None:
    monkeypatch.setattr(state_module, "_process_rows", lambda: rows)
    monkeypatch.setattr(
        state_module,
        "_process_executable_path",
        lambda pid: executable_paths.get(pid, ""),
    )


def test_clone_pids_finds_a_renamed_main_process(monkeypatch, tmp_path):
    """ZCode calls app.setName(), so its main process loses the bundle path."""
    bundle = tmp_path / "ZCode-b1.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleExecutable": "ZCode-b1"})
    )
    resolved = os.path.realpath(bundle)
    rows = [
        ("101", "ZCode-b1"),
        ("102", f"{resolved}/Contents/Frameworks/ZCode Helper.app/Contents/MacOS/ZCode Helper --type=gpu-process"),
        ("103", "/Applications/Unrelated.app/Contents/MacOS/Unrelated"),
    ]
    _fake_process_table(
        monkeypatch, rows, {"101": f"{resolved}/Contents/MacOS/ZCode-b1"}
    )

    assert state_module.clone_pids(bundle) == ["101", "102"]
    assert state_module.is_clone_running(bundle) is True


def test_clone_pids_ignores_a_same_named_process_outside_the_bundle(monkeypatch, tmp_path):
    bundle = tmp_path / "ZCode-b1.app"
    _fake_process_table(
        monkeypatch,
        [("101", "ZCode-b1"), ("102", "something else")],
        {"101": "/usr/local/bin/ZCode-b1"},
    )

    assert state_module.clone_pids(bundle) == []


def test_clone_pids_ignores_commands_that_merely_mention_the_path(monkeypatch, tmp_path):
    bundle = tmp_path / "ZCode-b1.app"
    resolved = os.path.realpath(bundle)
    _fake_process_table(
        monkeypatch,
        [
            ("201", f"zsh -c 'grep {resolved}/Contents/Info.plist'"),
            ("202", f"/usr/bin/open -n {resolved}"),
        ],
        {},
    )

    assert state_module.clone_pids(bundle) == []
    assert state_module.is_clone_running(bundle) is False


def test_running_clone_names_sees_a_renamed_main_process(monkeypatch, tmp_path):
    bundle = tmp_path / "ZCode-b1.app"
    resolved = os.path.realpath(bundle)
    _fake_process_table(
        monkeypatch,
        [("101", "ZCode-b1")],
        {"101": f"{resolved}/Contents/MacOS/ZCode-b1"},
    )
    records = [SimpleNamespace(dest_path=str(bundle), clone_name="ZCode-b1")]

    assert state_module.running_clone_names(records) == {"ZCode-b1"}


def test_signal_clone_targets_the_renamed_main_process(monkeypatch, tmp_path):
    bundle = tmp_path / "ZCode-b1.app"
    resolved = os.path.realpath(bundle)
    _fake_process_table(
        monkeypatch,
        [("101", "ZCode-b1")],
        {"101": f"{resolved}/Contents/MacOS/ZCode-b1"},
    )
    commands: list[list[str]] = []

    def fake_run(command, **kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(
        state_module,
        "subprocess",
        SimpleNamespace(run=fake_run, SubprocessError=subprocess.SubprocessError),
    )

    state_module._signal_clone(str(bundle), "-TERM")

    assert commands == [["kill", "-TERM", "101"]]


def test_graceful_quit_targets_only_the_main_process(monkeypatch, tmp_path):
    bundle = tmp_path / "ZCode-b1.app"
    resolved = os.path.realpath(bundle)
    helper = f"{resolved}/Contents/Frameworks/ZCode Helper.app/Contents/MacOS/ZCode Helper"
    rows = [
        ("101", "ZCode-b1"),
        ("102", f"{helper} --type=gpu-process"),
    ]
    _fake_process_table(
        monkeypatch,
        rows,
        {"101": f"{resolved}/Contents/MacOS/ZCode-b1", "102": helper},
    )
    delivered: list[str] = []
    monkeypatch.setattr(
        state_module, "_send_quit_apple_event", lambda pid: delivered.append(pid) or True
    )

    assert state_module._request_graceful_quit(str(bundle)) is True
    assert delivered == ["101"]


def test_send_quit_apple_event_builds_a_quit_event(monkeypatch):
    calls: list[tuple[str, int]] = []

    class FakeAppleEvents:
        def AECreateDesc(self, kind, *args):
            calls.append(("desc", kind))
            return 0

        def AECreateAppleEvent(self, event_class, event_id, *args):
            calls.append(("event", event_id))
            return 0

        def AESendMessage(self, event, reply, mode, timeout):
            calls.append(("send", mode))
            return 0

        def AEDisposeDesc(self, desc):
            calls.append(("dispose", 0))
            return 0

    monkeypatch.setattr(state_module, "_apple_event_library", lambda: FakeAppleEvents())

    assert state_module._send_quit_apple_event("101") is True
    assert calls == [
        ("desc", state_module._AE_TYPE_KERNEL_PROCESS_ID),
        ("event", state_module._AE_QUIT_APPLICATION),
        ("send", state_module._AE_NO_REPLY),
        ("dispose", 0),
        ("dispose", 0),
    ]
