"""Tests for scheduling UI work produced by native (AppKit) callbacks."""

import asyncio
from unittest.mock import MagicMock

from twinspace.core.state import StateManager
from twinspace.gui.services.environment_service import EnvironmentService
from twinspace.gui.views.environment_list import EnvironmentListView


def _view(tmp_path) -> EnvironmentListView:
    return EnvironmentListView(
        environment_service=EnvironmentService(
            state_manager=StateManager(state_file=tmp_path / "clones.yaml")
        )
    )


def test_schedule_uses_the_running_loop(toga_app, tmp_path):
    view = _view(tmp_path)
    seen: list[str] = []

    async def work() -> None:
        seen.append("ran")

    async def runner() -> None:
        view._schedule(work())
        await asyncio.sleep(0)

    asyncio.run(runner())
    assert seen == ["ran"]


def test_schedule_falls_back_to_the_app_loop(toga_app, tmp_path):
    view = _view(tmp_path)
    loop = MagicMock()
    loop.is_running.return_value = True
    view.app_instance = MagicMock()
    view.app_instance.loop = loop

    async def work() -> None:
        return None

    coro = work()
    view._schedule(coro)

    loop.call_soon_threadsafe.assert_called_once()
    assert loop.call_soon_threadsafe.call_args[0][0] == loop.create_task
    asyncio.run(_drain(coro))


async def _drain(coro) -> None:
    coro.close()


def test_schedule_drops_work_loudly_without_a_loop(toga_app, tmp_path, caplog):
    view = _view(tmp_path)
    view.app_instance = None

    async def work() -> None:
        return None

    coro = work()
    with caplog.at_level("WARNING"):
        view._schedule(coro)

    assert coro.cr_frame is None or coro.cr_frame.f_lasti == -1
    assert any("Dropped UI action" in record.message for record in caplog.records)
