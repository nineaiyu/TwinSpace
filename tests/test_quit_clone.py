"""Stopping a clone must escalate when the app ignores SIGTERM."""

import pytest

from twinspace.core import state as state_module


def _patch_process(monkeypatch, *, dies_on: str | None) -> list[str]:
    """Fake the process table; ``dies_on`` is the signal that actually stops it."""
    signals: list[str] = []
    alive = {"value": True}

    def fake_signal(needle: str, signal_name: str) -> None:
        signals.append(signal_name)
        if dies_on is not None and signal_name == dies_on:
            alive["value"] = False

    monkeypatch.setattr(state_module, "is_clone_running", lambda needle: alive["value"])
    monkeypatch.setattr(state_module, "_signal_clone", fake_signal)
    monkeypatch.setattr(
        state_module, "_wait_until_stopped", lambda needle, timeout: not alive["value"]
    )
    return signals


def test_quit_clone_escalates_to_sigkill_when_term_is_ignored(monkeypatch):
    signals = _patch_process(monkeypatch, dies_on="-KILL")

    assert state_module.quit_clone("/Apps/WorkBuddy-b2.app", timeout=0) is True
    assert signals == ["-TERM", "-KILL"]


def test_quit_clone_stops_after_the_first_term(monkeypatch):
    signals = _patch_process(monkeypatch, dies_on="-TERM")

    assert state_module.quit_clone("/Apps/Qoder-b2.app") is True
    assert signals == ["-TERM"]


def test_quit_clone_is_a_no_op_when_nothing_runs(monkeypatch):
    monkeypatch.setattr(state_module, "is_clone_running", lambda needle: False)
    monkeypatch.setattr(
        state_module, "_signal_clone", lambda needle, signal_name: pytest.fail("no signal")
    )

    assert state_module.quit_clone("/Apps/Trae-b2.app") is True


def test_quit_clone_reports_failure_when_the_process_survives_kill(monkeypatch):
    signals = _patch_process(monkeypatch, dies_on=None)

    assert state_module.quit_clone("/Apps/Stubborn.app") is False
    assert signals == ["-TERM", "-KILL"]
