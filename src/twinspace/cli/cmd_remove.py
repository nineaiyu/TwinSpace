"""CLI command for removing cloned applications."""

import sys

import click
from rich.console import Console

from twinspace.core.cloning.manager import CloneManager
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger

console = Console()
logger = get_logger("cli.remove")


@click.command(name="remove")
@click.argument("clone_name")
@click.option(
    "--with-data/--keep-data",
    "with_data",
    default=None,
    help="Also delete or keep the data directory.",
)
@click.option(
    "--no-with-data",
    "no_with_data",
    is_flag=True,
    hidden=True,
    help="Alias for --keep-data",
)
def remove(clone_name: str, with_data: bool | None, no_with_data: bool) -> None:
    """Remove a cloned application."""
    manager = CloneManager()
    record = manager.get_clone(clone_name)
    if record is None:
        console.print(t("remove_err_not_found", clone_name=clone_name))
        sys.exit(1)

    if no_with_data:
        with_data = False

    if with_data is True:
        delete_data = True
    elif with_data is False:
        delete_data = False
    else:
        try:
            delete_data = click.confirm(
                t("remove_prompt_delete_data", data_dir=record.data_dir),
                default=False,
            )
        except click.Abort:
            sys.exit(1)

    try:
        manager.remove_clone(clone_name, with_data=delete_data)
    except Exception as exc:
        logger.error("Failed to remove clone '%s': %s", clone_name, exc)
        console.print(f"[bold red]Error:[/bold red] {exc}")
        sys.exit(1)

    console.print(t("remove_success", clone_name=clone_name))
