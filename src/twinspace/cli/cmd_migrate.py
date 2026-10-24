"""Migrate a pre-3.0 ATBClone data root to TwinSpace."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click
import yaml
from rich.console import Console

from twinspace.core.config import LEGACY_TWINSPACE_DIR
from twinspace.core.state import StateManager, is_clone_running

console = Console()


def _rewrite_state_paths(state_file: Path, old_root: Path, new_root: Path) -> None:
    if not state_file.is_file():
        return
    backup = state_file.with_suffix(state_file.suffix + ".pre-twinspace.bak")
    shutil.copy2(state_file, backup)
    data = yaml.safe_load(state_file.read_text(encoding="utf-8")) or []
    old = str(old_root)
    new = str(new_root)
    for record in data if isinstance(data, list) else []:
        if not isinstance(record, dict):
            continue
        for field in ("dest_path", "data_dir", "env_dir"):
            value = record.get(field)
            if isinstance(value, str) and (value == old or value.startswith(old + "/")):
                record[field] = new + value[len(old):]
    state_file.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _rewrite_config_base(config_file: Path, old_root: Path, new_root: Path) -> None:
    if not config_file.is_file():
        return
    data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return
    base = data.get("base_dir")
    if isinstance(base, str):
        old = str(old_root)
        if base == old or base.startswith(old + "/"):
            data["base_dir"] = str(new_root) + base[len(old):]
            config_file.write_text(
                yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )


@click.command(name="migrate")
@click.option(
    "--from",
    "source_dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=LEGACY_TWINSPACE_DIR,
    show_default=True,
    help="Legacy ATBClone data root.",
)
@click.option(
    "--to",
    "target_dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    show_default=True,
    help="New TwinSpace data root.",
)
@click.option(
    "--move",
    is_flag=True,
    help="Move data instead of creating a compatibility symlink (advanced).",
)
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def migrate(source_dir: Path, target_dir: Path, move: bool, yes: bool) -> None:
    """Make existing ATBClone data available to TwinSpace.

    The default creates ~/TwinSpace as a symlink to the legacy directory, so
    existing clone launchers keep working. --move physically relocates the
    directory and rewrites state paths, but generated launchers may then need
    to be rebuilt with `twinspace env update`.
    """
    source = Path(source_dir).expanduser()
    if target_dir is None:
        # Follow the configured TwinSpace root (TWINSPACE_HOME / base_dir)
        # instead of assuming ~/TwinSpace.
        from twinspace.core.config import DEFAULT_TWINSPACE_DIR

        target_dir = DEFAULT_TWINSPACE_DIR
    target = Path(target_dir).expanduser()
    if not source.is_dir():
        console.print(f"[red]Error:[/red] legacy data root not found: {source}")
        sys.exit(1)
    if target.exists() or target.is_symlink():
        console.print(f"[red]Error:[/red] target already exists: {target}")
        sys.exit(1)
    if source.resolve() == target.resolve():
        console.print("[red]Error:[/red] source and target are the same directory.")
        sys.exit(1)

    records = StateManager(state_file=source / "clones.yaml").load()
    if any(is_clone_running(record.dest_path) for record in records):
        console.print("[red]Please quit all TwinSpace/ATBClone apps before migrating.[/red]")
        sys.exit(1)

    action = "move data" if move else f"create symlink {target} -> {source}"
    if not yes and not click.confirm(f"{action}?", default=True):
        return

    if move:
        shutil.move(str(source), str(target))
        _rewrite_state_paths(target / "clones.yaml", source, target)
        _rewrite_config_base(target / "config.yaml", source, target)
        console.print(f"[green]Moved data to {target}.[/green]")
        console.print(
            "[yellow]Existing launchers may still contain the old absolute path. "
            "Run `twinspace env update <name>` to rebuild them.[/yellow]"
        )
    else:
        target.symlink_to(source, target_is_directory=True)
        console.print(f"[green]Linked {target} -> {source}.[/green]")
        console.print(
            "Existing clones and their data remain usable; new data is written through "
            "the TwinSpace path."
        )
