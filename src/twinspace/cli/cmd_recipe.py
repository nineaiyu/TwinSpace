"""CLI commands for managing and inspecting recipes."""

import sys

import click
import yaml  # type: ignore[import-untyped]
from rich.console import Console
from rich.table import Table

from twinspace.core.i18n import t
from twinspace.core.logger import get_logger
from twinspace.recipes.loader import RecipeLoader

console = Console()
logger = get_logger("cli.recipe")


@click.group(name="recipe")
def recipe() -> None:
    """Manage and inspect application clone recipes."""


@recipe.command(name="list")
def recipe_list() -> None:
    """List all built-in and custom recipes."""
    logger.info("Listing all recipes (built-in and custom)")
    entries: list[dict] = []  # (data, origin)

    builtin_dir = RecipeLoader.BUILTIN_DIR
    for yf in sorted(builtin_dir.glob("*.yaml")):
        try:
            with open(yf, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception as exc:
            logger.warning("Skipping unreadable built-in recipe %s: %s", yf, exc)
            continue
        entries.append({"data": data, "origin": "builtin"})

    custom_dir = RecipeLoader.get_local_dir()
    if custom_dir.is_dir():
        for yf in sorted(custom_dir.glob("*.yaml")):
            if not yf.is_file():
                continue
            try:
                with open(yf, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            except Exception as exc:
                logger.warning("Skipping unreadable recipe %s: %s", yf, exc)
                continue
            entries.append({"data": data, "origin": "custom"})

    # Sort rows by origin (builtin first), then strategy, then app_name
    entries.sort(
        key=lambda item: (
            0 if item["origin"] == "builtin" else 1,
            0 if item["data"].get("strategy") == "hard_clone" else 1,
            str(item["data"].get("app_name", "")).lower(),
        )
    )

    table = Table()
    table.add_column(t("recipe_col_bundle_id"))
    table.add_column(t("recipe_col_app_name"))
    table.add_column(t("recipe_col_strategy"))
    table.add_column(t("recipe_col_strip_sandbox"))
    table.add_column(t("recipe_col_origin"))

    for item in entries:
        r = item["data"]
        strip_sb = "✅" if r.get("strip_sandbox", False) else "✘"
        origin = "🔧" if item["origin"] == "custom" else ""
        table.add_row(
            str(r.get("bundle_id", "")),
            str(r.get("app_name", "")),
            str(r.get("strategy", "")),
            strip_sb,
            origin,
        )

    console.print(table)


@recipe.command(name="show")
@click.argument("bundle_id")
def recipe_show(bundle_id: str) -> None:
    """Show recipe details for a specific bundle ID."""
    from twinspace.validation import validate_bundle_id
    try:
        validate_bundle_id(bundle_id)
    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        sys.exit(1)

    logger.info(f"Showing recipe details for bundle_id='{bundle_id}'")
    local_file = RecipeLoader.get_local_dir() / f"{bundle_id}.yaml"
    builtin_file = RecipeLoader.BUILTIN_DIR / f"{bundle_id}.yaml"

    if local_file.is_file():
        console.print(t("recipe_local_override"))
        console.print(local_file.read_text(encoding="utf-8").rstrip())
    elif builtin_file.is_file():
        console.print(builtin_file.read_text(encoding="utf-8").rstrip())
    else:
        logger.error(f"Recipe not found for bundle_id='{bundle_id}'")
        console.print(t("recipe_err_not_found", bundle_id=bundle_id))
        sys.exit(1)


from .cmd_probe import probe as probe_cmd

recipe.add_command(probe_cmd, name="probe")
