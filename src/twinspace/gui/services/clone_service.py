"""Async GUI adapter for the core clone manager."""

from __future__ import annotations

import asyncio
from pathlib import Path

from twinspace.core.clone_task import CloneTask
from twinspace.core.cloning.manager import CloneManager
from twinspace.core.config import DEFAULT_STATE_FILE
from twinspace.core.state import CloneRecord, StateManager


class CloneService:
    """Keep the GUI's async API while delegating all lifecycle work to core."""

    def __init__(self, state_file: Path = DEFAULT_STATE_FILE):
        self.manager = CloneManager(state_file=state_file)
        self.state_manager: StateManager = self.manager.state_manager
        self._busy_clones = self.manager.busy_clones

    async def list_clones(self) -> list[CloneRecord]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.manager.list_clones)

    async def get_clone(self, clone_name: str) -> CloneRecord | None:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.manager.get_clone, clone_name)

    async def create_clone(self, task: CloneTask) -> CloneRecord:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.manager.create_clone, task)

    async def update_clone(self, clone_name: str) -> CloneRecord:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.manager.update_clone, clone_name)

    async def update_clone_record(self, record: CloneRecord) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.state_manager.add, record)

    async def remove_clone(self, clone_name: str, with_data: bool = False) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.manager.remove_clone, clone_name, with_data)
