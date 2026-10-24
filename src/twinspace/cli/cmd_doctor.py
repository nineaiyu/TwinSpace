"""Doctor command for checking environment prerequisites."""

import subprocess
import sys

import click
from rich.console import Console

from twinspace.core.config import check_directory_access, get_apps_dir, get_data_dir
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger

console = Console()
logger = get_logger("cli.doctor")


@click.command()
def doctor():
    """Check environment prerequisites and directory permissions."""
    checks = {
        "codesign": ["/usr/bin/which", "codesign"],
        "xcode-select": ["/usr/bin/xcode-select", "-p"],
        "PlistBuddy": ["/bin/ls", "/usr/libexec/PlistBuddy"],
    }
    all_passed = True

    logger.info("Running environment health checks")
    console.print(t("doctor_running_checks"))
    for name, cmd in checks.items():
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
            console.print(f"[green]✓ {name}[/green]: {out}")
            logger.info(f"Check passed: {name} -> {out}")
        except subprocess.CalledProcessError:
            console.print(f"[red]✗ {name}[/red]: {t('doctor_missing')}")
            logger.error(f"Check failed: {name} is missing or returned error")
            all_passed = False

    # Directory read/write permission checks
    dir_checks = [
        (t("doctor_item_apps_dir"), get_apps_dir()),
        (t("doctor_item_data_dir"), get_data_dir()),
    ]
    for label, d_path in dir_checks:
        passed, detail = check_directory_access(d_path)
        if passed:
            console.print(f"[green]✓ {label}[/green]: {t('doctor_rw_normal')} ({d_path})")
            logger.info(f"Check passed: {label} -> {d_path}")
        else:
            console.print(f"[red]✗ {label}[/red]: {t('doctor_rw_failed')} ({d_path}) - {detail}")
            logger.error(f"Check failed: {label} -> {d_path}: {detail}")
            all_passed = False

    if not all_passed:
        logger.error("Environment checks completed with failures")
        sys.exit(1)
    logger.info("All environment health checks passed successfully")
