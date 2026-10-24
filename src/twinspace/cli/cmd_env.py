"""CLI commands for managing isolated multi-app environments."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from twinspace.core.environments import (
    TEMPLATES,
    EnvironmentSpec,
    app_for_key,
    app_key_for_bundle_id,
    template_app_keys,
)
from twinspace.core.environments.manager import EnvironmentManager
from twinspace.core.logger import get_logger

console = Console()
logger = get_logger("cli.env")


def _manager() -> EnvironmentManager:
    return EnvironmentManager()


def _parse_app_keys(value: str | None) -> list[str] | None:
    if not value:
        return None
    keys = [part.strip() for part in value.split(",") if part.strip()]
    if not keys:
        raise click.BadParameter("Specify at least one app key.")
    for key in keys:
        if app_for_key(key) is None:
            raise click.BadParameter(f"Unknown app key: {key}")
    return keys


def _parse_clone_names(values: tuple[str, ...]) -> dict[str, str]:
    names: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise click.BadParameter("Use --clone-name APP=NAME.")
        key, name = value.split("=", 1)
        key = key.strip()
        name = name.strip()
        if app_for_key(key) is None:
            raise click.BadParameter(f"Unknown app key: {key}")
        if not name:
            raise click.BadParameter(f"Clone name for {key} cannot be empty.")
        names[key] = name
    return names


def _progress(index: int, total: int, app, status: str) -> None:
    labels = {
        "checking": "checking",
        "existing": "already present",
        "creating": "creating",
        "created": "created",
        "updating": "updating",
        "updated": "updated",
        "failed": "failed",
    }
    console.print(f"[{index}/{total}] {app.label}: {labels.get(status, status)}")


def _selected_keys(apps: str | None, template: str | None) -> list[str]:
    explicit = _parse_app_keys(apps)
    if explicit is not None:
        return explicit
    if template:
        return list(template_app_keys(template))
    return [app.key for app in _manager().available_apps() if app.installed]


@click.group(name="env")
def env() -> None:
    """Manage isolated multi-app environments."""


@env.command("list")
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON.")
def env_list(as_json: bool) -> None:
    """List environments and their apps."""
    manager = _manager()
    environments = manager.list_environments()
    if as_json:
        payload = [
            {
                "name": item.name,
                "env_dir": str(item.env_dir),
                "running": item.running,
                "apps": [
                    {
                        "key": app_key_for_bundle_id(record.bundle_id),
                        "clone_name": record.clone_name,
                        "bundle_id": record.bundle_id,
                        "data_dir": record.data_dir,
                    }
                    for record in item.records
                ],
            }
            for item in environments
        ]
        console.print_json(json.dumps(payload, ensure_ascii=False))
        return

    if not environments:
        console.print("No environments yet. Create one with: twinspace env create <name>")
        return

    table = Table(title=f"TwinSpace environments ({len(environments)})")
    table.add_column("Name", style="bold")
    table.add_column("Apps")
    table.add_column("State")
    table.add_column("Directory", style="dim")
    for item in environments:
        labels = []
        for record in item.records:
            key = app_key_for_bundle_id(record.bundle_id)
            app = app_for_key(key)
            labels.append(f"{app.label if app else record.source_app} ({record.clone_name})")
        table.add_row(
            item.name,
            "\n".join(labels) or "-",
            "running" if item.running else "stopped",
            str(item.env_dir),
        )
    console.print(table)


@env.command("create")
@click.argument("name")
@click.option("--apps", help="Comma-separated app keys (chrome,zcode,...).")
@click.option("--template", type=click.Choice(sorted(TEMPLATES)), help="Built-in app template.")
@click.option(
    "--clone-name",
    "clone_names",
    multiple=True,
    metavar="APP=NAME",
    help="Override the clone name for one app.",
)
@click.option("--dry-run", is_flag=True, help="Validate and print the plan without creating.")
def env_create(
    name: str,
    apps: str | None,
    template: str | None,
    clone_names: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Create a new environment (defaults to every installed supported app)."""
    manager = _manager()
    keys = _selected_keys(apps, template)
    if not keys:
        console.print("[red]No supported apps are installed.[/red]")
        sys.exit(1)
    names = _parse_clone_names(clone_names)

    if dry_run:
        table = Table(title=f"Environment plan: {name}")
        table.add_column("App")
        table.add_column("Clone name")
        table.add_column("Source")
        missing = False
        for key in keys:
            app = app_for_key(key)
            assert app is not None
            source = app.installed_path
            if source is None:
                missing = True
            table.add_row(
                f"{app.label} ({key})",
                names.get(key, f"{app.clone_prefix}-{name}"),
                str(source or f"missing: {app.default_path}"),
            )
        console.print(table)
        if missing:
            console.print("[red]Some apps are not installed; nothing was created.[/red]")
            sys.exit(1)
        return

    try:
        created = asyncio.run(
            manager.create_environment(
                name,
                keys,
                on_progress=_progress,
                clone_names=names or None,
            )
        )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)

    env_info = manager.environment(name)
    path = env_info.env_dir if env_info else ""
    console.print(
        f"[green]Environment {name!r} is ready[/green] "
        f"({len(created)} new app(s)) at {path}"
    )


@env.command("open")
@click.argument("name")
@click.option("--apps", help="Comma-separated subset of app keys to launch.")
def env_open(name: str, apps: str | None) -> None:
    """Launch every app in an environment (or a subset)."""
    manager = _manager()
    if manager.environment(name) is None:
        console.print(f"[red]Error:[/red] Environment {name!r} not found.")
        sys.exit(1)
    errors = manager.open_environment(name, _parse_app_keys(apps))
    if errors:
        console.print("[red]Some apps could not be opened:[/red]")
        for item in errors:
            console.print(f"  - {item}")
        sys.exit(1)
    console.print(f"[green]Opened environment {name!r}.[/green]")


@env.command("remove")
@click.argument("name")
@click.option("--with-data/--keep-data", default=False, help="Delete the environment data too.")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def env_remove(name: str, with_data: bool, yes: bool) -> None:
    """Remove an environment and its app bundles."""
    manager = _manager()
    env_info = manager.environment(name)
    if env_info is None:
        console.print(f"[red]Error:[/red] Environment {name!r} not found.")
        sys.exit(1)
    if not yes and not click.confirm(
        f"Remove environment {name!r} ({len(env_info.records)} app(s))?", default=False
    ):
        return
    try:
        errors = asyncio.run(manager.remove_environment(name, with_data=with_data))
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if errors:
        console.print("[yellow]Environment removed with errors:[/yellow]")
        for item in errors:
            console.print(f"  - {item}")
        sys.exit(1)
    console.print(f"[green]Environment {name!r} removed.[/green]")


@env.command("update")
@click.argument("name")
@click.option("--apps", help="Comma-separated subset of app keys to update.")
def env_update(name: str, apps: str | None) -> None:
    """Rebuild every app in an environment from its current source app."""
    manager = _manager()
    if manager.environment(name) is None:
        console.print(f"[red]Error:[/red] Environment {name!r} not found.")
        sys.exit(1)
    try:
        errors = asyncio.run(
            manager.update_environment(
                name,
                app_keys=_parse_app_keys(apps),
                on_progress=_progress,
            )
        )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if errors:
        console.print("[red]Some apps failed to update:[/red]")
        for item in errors:
            console.print(f"  - {item}")
        sys.exit(1)
    console.print(f"[green]Environment {name!r} updated.[/green]")


@env.command("export")
@click.argument("name")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write YAML to a file (default: stdout).",
)
def env_export(name: str, output: Path | None) -> None:
    """Export an environment as a portable template."""
    try:
        spec = _manager().export_environment(name)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    text = spec.to_yaml()
    if output is None:
        console.print(text, markup=False)
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        console.print(f"[green]Wrote {output}[/green]")


@env.command("import")
@click.argument("source", type=click.File("r"))
@click.option("--name", "target_name", help="Create under a different environment name.")
@click.option("--dry-run", is_flag=True, help="Validate and show the imported apps.")
def env_import(source, target_name: str | None, dry_run: bool) -> None:
    """Import a portable environment template (skips apps that already exist)."""
    try:
        spec = EnvironmentSpec.from_yaml(source.read())
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    target = target_name or spec.name
    manager = _manager()
    existing = manager.environment(target)
    existing_keys = existing.app_keys if existing else set()
    new_apps = [app for app in spec.apps if app.key not in existing_keys]

    if dry_run:
        console.print(f"Environment: {target}")
        for app in spec.apps:
            state = "existing" if app.key in existing_keys else "new"
            console.print(
                f"  - {app.key}: {app.clone_name or '(default)'} (state: {state})"
            )
        return

    if not new_apps:
        console.print(f"[yellow]Environment {target!r} already has all apps from this file.[/yellow]")
        return

    try:
        created = asyncio.run(
            manager.import_environment(spec, target_name=target, on_progress=_progress)
        )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(
        f"[green]Imported {len(created)} app(s) into environment {target!r}.[/green]"
    )


@env.command("templates")
def env_templates() -> None:
    """List built-in environment templates."""
    table = Table(title="Built-in templates")
    table.add_column("Template", style="bold")
    table.add_column("Apps")
    for name, keys in sorted(TEMPLATES.items()):
        labels = []
        for key in keys:
            app = app_for_key(key)
            labels.append(app.label if app else key)
        table.add_row(name, ", ".join(labels))
    console.print(table)


@env.command("backup")
@click.argument("name")
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Archive path (default: ~/TwinSpace/Backups/<name>-<timestamp>.tar.gz).",
)
def env_backup(name: str, output: Path | None) -> None:
    """Back up every app's data directory from an environment."""
    try:
        path = _manager().backup_environment(name, output_path=output)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"[green]Backup written to {path}[/green]")


@env.command("restore")
@click.argument("name")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def env_restore(name: str, archive: Path, yes: bool) -> None:
    """Restore app data from a backup into an existing environment."""
    manager = _manager()
    if manager.environment(name) is None:
        console.print(f"[red]Error:[/red] Environment {name!r} not found.")
        sys.exit(1)
    if not yes and not click.confirm(
        f"Restore {archive} into environment {name!r}? Existing files are overwritten.",
        default=False,
    ):
        return
    try:
        restored, errors, safety = manager.restore_environment(name, archive)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"[dim]Safety backup: {safety}[/dim]")
    console.print(f"Restored: {', '.join(restored) if restored else '-'}")
    if errors:
        console.print("[red]Errors:[/red]")
        for item in errors:
            console.print(f"  - {item}")
        sys.exit(1)
    console.print(f"[green]Environment {name!r} restored.[/green]")
