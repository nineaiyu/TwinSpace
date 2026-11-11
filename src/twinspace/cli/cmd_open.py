"""CLI command to launch a clone, optionally opening a URL in its browser."""

import sys
from pathlib import Path

import click

from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.core.state import CloneRecord, StateManager, is_clone_running

logger = get_logger("cli.open")


def _find_record(state: StateManager, clone_name: str) -> CloneRecord | None:
    for record in state.load():
        if record.clone_name == clone_name:
            return record
    return None


def _resolve_browser(record: CloneRecord, state: StateManager) -> Path | None:
    """Browser to open a URL with: the clone's binding, itself, or its env browser."""
    overrides = getattr(record, "env_overrides", None) or {}
    bound = overrides.get("TWINSPACE_BROWSER_APP_PATH")
    if bound and Path(bound).exists():
        return Path(bound)

    bundle_id = (record.new_bundle_id or record.bundle_id or "").lower()
    if "chrome" in bundle_id or "chromium" in bundle_id:
        # The clone itself is a browser: URLs belong in its own profile.
        return Path(record.dest_path)

    if record.env_group:
        for sibling in state.load():
            if sibling.env_group != record.env_group:
                continue
            sibling_id = (sibling.new_bundle_id or sibling.bundle_id or "").lower()
            if "chrome" in sibling_id and Path(sibling.dest_path).exists():
                return Path(sibling.dest_path)
    return None


@click.command(name="open")
@click.argument("clone_name")
@click.argument("url", required=False)
def open_clone(clone_name: str, url: str | None) -> None:
    """Open a clone (activating it when already running); pass URL to send a link to its browser."""
    state = StateManager()
    record = _find_record(state, clone_name)
    if record is None:
        click.echo(t("cli_open_not_found", name=clone_name))
        sys.exit(1)

    dest_path = Path(record.dest_path)
    if not dest_path.exists():
        click.echo(t("cli_open_missing", path=str(dest_path)))
        sys.exit(1)

    import subprocess

    if url:
        browser = _resolve_browser(record, state)
        if browser is None:
            click.echo(t("cli_open_no_browser", name=clone_name))
            sys.exit(1)
        try:
            subprocess.Popen(["open", "-na", str(browser), "--args", url])
            click.echo(t("cli_open_url_ok", url=url, name=Path(browser).stem))
        except Exception as exc:
            click.echo(t("cli_open_failed", error=str(exc)))
            sys.exit(1)
        return

    try:
        subprocess.Popen(["open", str(dest_path)])
        state_label = "running" if is_clone_running(str(dest_path)) else "launched"
        click.echo(t("cli_open_ok", name=record.clone_name))
        logger.debug("Open state for %s: %s", record.clone_name, state_label)
    except Exception as exc:
        click.echo(t("cli_open_failed", error=str(exc)))
        sys.exit(1)
