"""CLI command for updating cloned applications."""

import sys
from pathlib import Path

import click
from rich.console import Console

from twinspace.core.cloning.manager import CloneManager
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger

console = Console()
logger = get_logger("cli.update")


@click.command(name="update")
@click.argument("clone_name")
def update(clone_name: str) -> None:
    """Update a cloned application."""
    manager = CloneManager()
    record = manager.get_clone(clone_name)
    if record is None:
        console.print(t("update_err_not_found", clone_name=clone_name))
        sys.exit(1)

    if not Path(record.source_path).exists():
        console.print(t("update_err_source_not_found", source_path=record.source_path))
        sys.exit(1)

    logger.info(
        "Starting update for clone '%s' (source='%s', strategy='%s')",
        clone_name,
        record.source_path,
        record.strategy,
    )
    console.print(t("update_starting", clone_name=clone_name))

    try:
        manager.update_clone(clone_name)
    except Exception as exc:
        logger.error("Failed to update clone '%s': %s", clone_name, exc)
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)

    console.print(t("update_success", clone_name=clone_name))
