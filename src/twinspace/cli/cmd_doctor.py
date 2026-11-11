"""Doctor command for checking environment prerequisites."""

import sys

import click
from rich.console import Console

from twinspace.core.doctor import run_all_checks
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger

console = Console()
logger = get_logger("cli.doctor")


@click.command()
def doctor():
    """Check environment prerequisites and directory permissions."""
    logger.info("Running environment health checks")
    console.print(t("doctor_running_checks"))
    all_passed = True
    for item in run_all_checks():
        if item.passed:
            console.print(f"[green]✓ {item.name}[/green]: {item.details}")
            logger.info(f"Check passed: {item.key or item.name} -> {item.details}")
        else:
            all_passed = False
            console.print(f"[red]✗ {item.name}[/red]: {item.details or t('doctor_missing')}")
            if item.hint:
                console.print(f"  [yellow]↳ {item.hint}[/yellow]")
            logger.error(f"Check failed: {item.key or item.name} -> {item.details}")

    if not all_passed:
        logger.error("Environment checks completed with failures")
        sys.exit(1)
    logger.info("All environment health checks passed successfully")
