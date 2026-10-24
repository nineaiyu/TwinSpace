"""GUI adapter for the core environment manager."""

from __future__ import annotations

from twinspace.core.environments.apps import (
    KNOWN_APPS,
    EnvironmentApp,
    EnvironmentInfo,
    app_for_key,
    app_key_for_bundle_id,
)
from twinspace.core.environments.manager import EnvironmentManager
from twinspace.core.state import StateManager

from .clone_service import CloneService

__all__ = [
    "KNOWN_APPS",
    "EnvironmentApp",
    "EnvironmentInfo",
    "EnvironmentService",
    "app_for_key",
    "app_key_for_bundle_id",
]


class EnvironmentService(EnvironmentManager):
    """Wire the GUI's async CloneService into the shared environment manager."""

    def __init__(
        self,
        clone_service: CloneService | None = None,
        state_manager: StateManager | None = None,
    ):
        super().__init__(
            clone_service=clone_service or CloneService(),
            state_manager=state_manager,
        )
