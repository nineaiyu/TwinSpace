import click
from rich.console import Console

from twinspace import __version__

from .cmd_clone import clone
from .cmd_doctor import doctor
from .cmd_env import env
from .cmd_list import list_clones
from .cmd_migrate import migrate
from .cmd_probe import probe
from .cmd_recipe import recipe
from .cmd_remove import remove
from .cmd_update import update
from .cmd_version import version
from .cmd_wizard import wizard

console = Console()


@click.group()
@click.version_option(__version__, "-v", "--version", message="%(prog)s %(version)s")
def cli():
    """TwinSpace - macOS application cloning engine."""
    # Probe the UI language once per invocation; without this every t() call
    # re-runs system detection (config file + up to two `defaults read`).
    from twinspace.core.i18n import detect_system_language, set_language

    set_language(detect_system_language())


cli.add_command(clone)
cli.add_command(doctor)
cli.add_command(env)
cli.add_command(list_clones)
cli.add_command(migrate)
cli.add_command(probe)
cli.add_command(recipe)
cli.add_command(remove)
cli.add_command(update)
cli.add_command(version)
cli.add_command(wizard)


def legacy_cli() -> None:
    """Compatibility entry point for the pre-3.0 `atbclone` command."""
    click.echo(
        "Warning: the 'atbclone' command is deprecated; use 'twinspace' instead.",
        err=True,
    )
    cli()


if __name__ == "__main__":
    cli()

