"""Pytest configuration and global fixtures for TwinSpace test suite."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest


def _keep_temp_out_of_twinspace() -> None:
    """Never let pytest write its temp trees into the TwinSpace data dir.

    Sessions that run inside a clone inherit ``TMPDIR=<...>/Environments/<env>/
    <app>/Tmp``, and pytest would then drop hundreds of megabytes of
    ``pytest-of-*`` directories inside the user's real clone data.
    """
    raw = os.environ.get("TMPDIR", "")
    if not raw:
        return
    try:
        candidate = Path(raw).expanduser().resolve()
    except OSError:  # pragma: no cover - malformed TMPDIR
        return
    if "TwinSpace" not in candidate.parts or "Data" not in candidate.parts:
        return
    fallback = Path("/tmp")
    if not fallback.is_dir():
        return
    os.environ["TMPDIR"] = str(fallback)
    # ``tempfile`` caches the first lookup; reset it so pytest picks the new root.
    tempfile.tempdir = None


_keep_temp_out_of_twinspace()

# Keep pytest output out of the user's operational log file: a test run inside a
# clone would otherwise append thousands of fake records to ~/TwinSpace/twinspace.log.
os.environ.setdefault("TWINSPACE_LOG_DISABLE", "1")

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


