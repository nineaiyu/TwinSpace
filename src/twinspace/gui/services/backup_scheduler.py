"""Daily automatic environment backups with retention pruning."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Callable

from twinspace.core.config import get_config_value, set_config_value
from twinspace.core.environments.backup import prune_backups
from twinspace.core.logger import get_logger
from twinspace.core.timestamps import parse_iso_timestamp

logger = get_logger("gui.backup_scheduler")

# A "daily" backup runs at most once per 20 hours, re-checked every hour.
_MIN_INTERVAL_SECONDS = 20 * 3600
_CHECK_INTERVAL_SECONDS = 3600


async def run_auto_backup_if_due(service: Any) -> None:
    """Back up every idle environment once the daily timer is due.

    Running environments are skipped (backups refuse to run on live data), and
    only the newest ``backup_retention`` archives per environment survive.
    """
    if not bool(get_config_value("auto_backup", False)):
        return
    now = datetime.now(timezone.utc)
    last_raw = str(get_config_value("last_auto_backup", "") or "")
    last = parse_iso_timestamp(last_raw) if last_raw else None
    if last is not None and (now - last).total_seconds() < _MIN_INTERVAL_SECONDS:
        return
    try:
        retention = max(1, int(get_config_value("backup_retention", 5) or 5))
    except (TypeError, ValueError):
        retention = 5
    # Mark the attempt first: a failed backup retries tomorrow, not in a loop.
    set_config_value("last_auto_backup", now.isoformat(timespec="seconds"))

    loop = asyncio.get_running_loop()
    try:
        environments = await loop.run_in_executor(None, service.list_environments)
        running = await loop.run_in_executor(None, service.running_clones)
    except Exception:
        logger.debug("Auto backup could not list environments", exc_info=True)
        return
    for env in environments:
        if any(record.clone_name in running for record in env.records):
            logger.info("Auto backup skipped (environment running): %s", env.name)
            continue
        try:
            await loop.run_in_executor(None, service.backup_environment, env.name)
            await loop.run_in_executor(None, prune_backups, env.name, retention)
            logger.info("Auto backup completed: %s", env.name)
        except Exception as exc:
            logger.warning("Auto backup failed for %s: %s", env.name, exc)


async def auto_backup_loop(service: Any, is_exiting: Callable[[], bool]) -> None:
    """Re-check the daily backup timer hourly until the app exits."""
    while not is_exiting():
        try:
            await run_auto_backup_if_due(service)
        except Exception:
            logger.debug("Auto backup pass failed", exc_info=True)
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
