"""Resources command for managing host resource mapping (services, caches, configs, shell)."""

from pathlib import Path

import click
from rich.console import Console

from twinspace.core.config import get_config_value, set_config_value
from twinspace.core.host_resources import (
    CONFIG_KEY,
    HOST_RESOURCE_GROUPS,
    RESOURCE_GROUP_ORDER,
    default_selections,
    find_resource_group,
    get_resources_list_path,
    normalize_selections,
    sync_resources_list,
)
from twinspace.core.i18n import t
from twinspace.core.logger import get_logger

console = Console()
logger = get_logger("cli.resources")


def _effective_cfg() -> tuple[bool, dict[str, list[str]]]:
    """Return (enabled, selections) with the recommended fallback before first save."""
    cfg = get_config_value(CONFIG_KEY, None)
    if not isinstance(cfg, dict):
        return True, default_selections()
    return bool(cfg.get("enabled")), normalize_selections(cfg.get("selections"))


def _save_resource_cfg(enabled: bool, selections: dict[str, list[str]]) -> None:
    set_config_value(CONFIG_KEY, {"enabled": enabled, "selections": selections})


def _sync_or_fail() -> Path:
    """Sync the resource list file, turning invalid config entries into clean CLI errors."""
    try:
        return sync_resources_list()
    except ValueError as e:
        console.print(t("clone_error", error=e))
        logger.error(f"Invalid host resource config: {e}")
        raise SystemExit(1)


def _resource_keys() -> list[str]:
    keys: list[str] = []
    for group in RESOURCE_GROUP_ORDER:
        keys.extend(HOST_RESOURCE_GROUPS[group].keys())
    return keys


def _resolve_keys(keys: tuple[str, ...]) -> list[tuple[str, str]]:
    """Resolve requested keys to [(group, resource_key)]; group keys expand to members."""
    resolved: list[tuple[str, str]] = []
    for key in keys:
        name = key.strip()
        group = find_resource_group(name)
        if group is None:
            console.print(
                t(
                    "resources_err_unknown",
                    resource=name,
                    available=", ".join(_resource_keys() + list(RESOURCE_GROUP_ORDER)),
                )
            )
            logger.error(f"Unknown resource requested: {name}")
            raise SystemExit(1)
        if group == name:
            for member in HOST_RESOURCE_GROUPS[group]:
                resolved.append((group, member))
        else:
            resolved.append((group, name))
    return resolved


def _print_status() -> None:
    console.print(t("resources_list_header"))
    enabled, selections = _effective_cfg()
    status = f"[green]{t('resources_status_on')}[/green]" if enabled else f"[dim]{t('resources_status_off')}[/dim]"
    console.print(status)
    for group in RESOURCE_GROUP_ORDER:
        console.print(f"  [bold]{t(f'resources_group_{group}')}[/bold]")
        for key, paths in HOST_RESOURCE_GROUPS[group].items():
            chosen = key in selections.get(group, [])
            mark = "[green]✓[/green]" if (enabled and chosen) else "[dim]·[/dim]"
            console.print(f"    {mark} [bold]{key}[/bold] [dim]({', '.join(paths)})[/dim]")
    console.print(t("resources_list_file", path=get_resources_list_path()))
    console.print(f"[dim]{t('resources_hint_restart')}[/dim]")


@click.group()
def resources():
    """Map host resources (services, caches, configs, shell) into clones."""
    logger.info("Entering resources management command")


@resources.command("list")
def resources_list():
    """Show current mapping configuration and the resource catalog."""
    _print_status()


@resources.command("enable")
@click.argument("keys", nargs=-1, required=True)
def resources_enable(keys: tuple[str, ...]):
    """Enable resources by key or whole groups (e.g. npm pip orbstack cache)."""
    _, selections = _effective_cfg()
    targets = _resolve_keys(keys)
    changed: list[tuple[str, str]] = []
    for group, key in targets:
        bucket = selections.setdefault(group, [])
        if key in bucket:
            console.print(t("resources_err_already_enabled", resource=key))
            continue
        bucket.append(key)
        changed.append((group, key))
    if changed:
        _save_resource_cfg(True, selections)
        written = _sync_or_fail()
        for group, key in changed:
            paths = ", ".join(HOST_RESOURCE_GROUPS[group].get(key, (key,)))
            console.print(t("resources_enable_done", resource=key, paths=paths))
        logger.info(f"Resources enabled: {changed}; list={written}")
        console.print(t("resources_sync_done", path=written))


@resources.command("disable")
@click.argument("keys", nargs=-1, required=True)
def resources_disable(keys: tuple[str, ...]):
    """Disable resources by key or whole groups (e.g. npm ssh cache)."""
    enabled, selections = _effective_cfg()
    targets = _resolve_keys(keys)
    removed: list[str] = []
    for group, key in targets:
        bucket = selections.get(group, [])
        if key not in bucket:
            console.print(t("resources_err_not_enabled", resource=key))
            continue
        bucket.remove(key)
        removed.append(key)
    if removed:
        still_enabled = enabled and any(
            selections.get(group) for group in RESOURCE_GROUP_ORDER
        )
        _save_resource_cfg(still_enabled, selections)
        written = _sync_or_fail()
        for key in removed:
            console.print(t("resources_disable_done", resource=key))
        logger.info(f"Resources disabled: {removed}")
        console.print(t("resources_sync_done", path=written))


@resources.command("sync")
def resources_sync():
    """Rewrite the resource list file from the current configuration."""
    written = _sync_or_fail()
    console.print(t("resources_sync_done", path=written))
    logger.info(f"Resource list synced: {written}")
