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
from twinspace.core.i18n import t
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
        raise click.BadParameter(t("env_err_param_one_key"))
    for key in keys:
        if app_for_key(key) is None:
            raise click.BadParameter(t("env_err_param_unknown_key", key=key))
    return keys


def _parse_clone_names(values: tuple[str, ...]) -> dict[str, str]:
    names: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise click.BadParameter(t("env_err_param_clone_format"))
        key, name = value.split("=", 1)
        key = key.strip()
        name = name.strip()
        if app_for_key(key) is None:
            raise click.BadParameter(t("env_err_param_unknown_key", key=key))
        if not name:
            raise click.BadParameter(t("env_err_param_clone_empty", key=key))
        names[key] = name
    return names


def _progress(index: int, total: int, app, status: str) -> None:
    labels = {
        "checking": t("env_status_checking"),
        "existing": t("env_status_existing"),
        "creating": t("env_status_creating"),
        "created": t("env_status_created"),
        "updating": t("env_status_updating"),
        "updated": t("env_status_updated"),
        "failed": t("env_status_failed"),
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
        console.print(t("env_list_empty"))
        return

    table = Table(title=t("env_list_title", count=len(environments)))
    table.add_column(t("env_col_name"), style="bold")
    table.add_column(t("env_col_apps"))
    table.add_column(t("env_col_state"))
    table.add_column(t("env_col_directory"), style="dim")
    for item in environments:
        labels = []
        for record in item.records:
            key = app_key_for_bundle_id(record.bundle_id)
            app = app_for_key(key)
            labels.append(f"{app.label if app else record.source_app} ({record.clone_name})")
        table.add_row(
            item.name,
            "\n".join(labels) or "-",
            t("env_state_running") if item.running else t("env_state_stopped"),
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
        console.print("[red]" + t("env_no_supported_apps") + "[/red]")
        sys.exit(1)
    names = _parse_clone_names(clone_names)

    if dry_run:
        table = Table(title=t("env_plan_title", name=name))
        table.add_column(t("env_col_app"))
        table.add_column(t("env_col_clone_name"))
        table.add_column(t("env_col_source"))
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
                str(source or t("env_source_missing", path=app.default_path)),
            )
        console.print(table)
        if missing:
            console.print("[red]" + t("env_create_missing_apps") + "[/red]")
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
        "[green]" + t("env_created", name=name, count=len(created), path=path) + "[/green]"
    )


@env.command("open")
@click.argument("name")
@click.option("--apps", help="Comma-separated subset of app keys to launch.")
def env_open(name: str, apps: str | None) -> None:
    """Launch every app in an environment (or a subset)."""
    manager = _manager()
    if manager.environment(name) is None:
        console.print("[red]Error:[/red] " + t("env_err_not_found", name=name))
        sys.exit(1)
    errors = manager.open_environment(name, _parse_app_keys(apps))
    if errors:
        console.print("[red]" + t("env_open_errors") + "[/red]")
        for item in errors:
            console.print(f"  - {item}")
        sys.exit(1)
    console.print("[green]" + t("env_opened", name=name) + "[/green]")


@env.command("remove")
@click.argument("name")
@click.option("--with-data/--keep-data", default=False, help="Delete the environment data too.")
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def env_remove(name: str, with_data: bool, yes: bool) -> None:
    """Remove an environment and its app bundles."""
    manager = _manager()
    env_info = manager.environment(name)
    if env_info is None:
        console.print("[red]Error:[/red] " + t("env_err_not_found", name=name))
        sys.exit(1)
    if not yes and not click.confirm(
        t("env_remove_confirm", name=name, count=len(env_info.records)), default=False
    ):
        return
    try:
        errors = asyncio.run(manager.remove_environment(name, with_data=with_data))
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    if errors:
        console.print("[yellow]" + t("env_remove_errors") + "[/yellow]")
        for item in errors:
            console.print(f"  - {item}")
        sys.exit(1)
    console.print("[green]" + t("env_removed", name=name) + "[/green]")


@env.command("update")
@click.argument("name")
@click.option("--apps", help="Comma-separated subset of app keys to update.")
def env_update(name: str, apps: str | None) -> None:
    """Rebuild every app in an environment from its current source app."""
    manager = _manager()
    if manager.environment(name) is None:
        console.print("[red]Error:[/red] " + t("env_err_not_found", name=name))
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
        console.print("[red]" + t("env_update_errors") + "[/red]")
        for item in errors:
            console.print(f"  - {item}")
        sys.exit(1)
    console.print("[green]" + t("env_updated", name=name) + "[/green]")


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
        console.print("[green]" + t("env_export_wrote", output=output) + "[/green]")


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
        console.print(t("env_import_dry_title", name=target))
        for app in spec.apps:
            state = (
                t("env_import_state_existing")
                if app.key in existing_keys
                else t("env_import_state_new")
            )
            console.print(
                t(
                    "env_import_row",
                    app_key=app.key,
                    clone=app.clone_name or t("env_import_clone_default"),
                    state=state,
                )
            )
        return

    if not new_apps:
        console.print("[yellow]" + t("env_import_all_present", name=target) + "[/yellow]")
        return

    try:
        created = asyncio.run(
            manager.import_environment(spec, target_name=target, on_progress=_progress)
        )
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(
        "[green]" + t("env_import_done", count=len(created), name=target) + "[/green]"
    )


@env.command("templates")
def env_templates() -> None:
    """List built-in environment templates."""
    table = Table(title=t("env_templates_title"))
    table.add_column(t("env_col_template"), style="bold")
    table.add_column(t("env_col_apps"))
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
    console.print("[green]" + t("env_backup_wrote", path=path) + "[/green]")


@env.command("restore")
@click.argument("name")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--yes", is_flag=True, help="Skip confirmation.")
def env_restore(name: str, archive: Path, yes: bool) -> None:
    """Restore app data from a backup into an existing environment."""
    manager = _manager()
    if manager.environment(name) is None:
        console.print("[red]Error:[/red] " + t("env_err_not_found", name=name))
        sys.exit(1)
    if not yes and not click.confirm(
        t("env_restore_confirm", archive=archive, name=name),
        default=False,
    ):
        return
    try:
        restored, errors, safety = manager.restore_environment(name, archive)
    except Exception as exc:
        console.print(f"[red]Error:[/red] {exc}")
        sys.exit(1)
    console.print(f"[dim]{t('env_restore_safety', path=safety)}[/dim]")
    console.print(t("env_restore_done_list", apps=", ".join(restored) if restored else "-"))
    if errors:
        console.print("[red]" + t("env_restore_errors") + "[/red]")
        for item in errors:
            console.print(f"  - {item}")
        sys.exit(1)
    console.print("[green]" + t("env_restored", name=name) + "[/green]")
