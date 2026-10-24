"""Pytest configuration and global fixtures for TwinSpace test suite."""

import asyncio
import os

import pytest

from twinspace.core.i18n import set_language


@pytest.fixture(autouse=True)
def default_test_environment(monkeypatch):
    """Default test environment to English and standard asyncio event loop."""
    if "TWINSPACE_LANG" not in os.environ:
        monkeypatch.setenv("TWINSPACE_LANG", "en")
    set_language(None)
    asyncio.set_event_loop_policy(asyncio.DefaultEventLoopPolicy())
    from twinspace.core.logger import clear_log_listeners
    clear_log_listeners()
    yield
    clear_log_listeners()
    set_language(None)


