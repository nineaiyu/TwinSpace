#!/usr/bin/env python3
"""Render every TwinSpace page and save PNG snapshots for visual review.

This is a development tool, not part of the automated test suite. It builds a
throwaway Toga window with the real views, forces the requested appearance, and
uses ``NSView.cacheDisplay`` to write one PNG per page. Run it after UI changes
and compare the images (or attach them to a pull request).

Examples:
    python scripts/ui_snapshot.py --theme dark
    python scripts/ui_snapshot.py --theme light --only clones,environments
    python scripts/ui_snapshot.py --out /tmp/twinspace-ui
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import toga
from toga.style import Pack
from toga.style.pack import ROW

from twinspace.gui.components.sidebar import SidebarNav
from twinspace.gui.patch_cocoa import (
    apply_cocoa_appearance,
    apply_cocoa_sidebar_material,
    configure_cocoa_window_chrome,
    is_dark_mode,
    patch_cocoa_widgets,
)
from twinspace.gui.services.clone_service import CloneService
from twinspace.gui.services.environment_service import EnvironmentService
from twinspace.gui.services.recipe_service import RecipeService
from twinspace.gui.theme import Theme
from twinspace.gui.views.clone_list import CloneListView
from twinspace.gui.views.doctor_view import DoctorView
from twinspace.gui.views.environment_list import EnvironmentListView
from twinspace.gui.views.logs_view import LogsView
from twinspace.gui.views.probe_view import ProbeView
from twinspace.gui.views.recipe_list import RecipeListView
from twinspace.gui.views.settings_view import SettingsView

PAGES = ("clones", "environments", "recipes", "probe", "doctor", "logs", "settings")


class SnapshotApp(toga.App):
    def __init__(self, output_dir: Path, pages: list[str], theme: str):
        super().__init__("TwinSpace Snapshots", "com.twinspace.snapshots")
        self.output_dir = output_dir
        self.pages = pages
        self.requested_theme = theme

    def startup(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

        dark = is_dark_mode() if self.requested_theme == "system" else self.requested_theme == "dark"
        Theme.apply_mode(dark)
        apply_cocoa_appearance(dark)

        self.main_window = toga.MainWindow(title="TwinSpace Snapshots", size=(1280, 820))
        self.sidebar = SidebarNav(
            on_select=lambda key: None,
            active_key=self.pages[0] if self.pages else "clones",
            app=self,
        )
        apply_cocoa_sidebar_material(self.sidebar)
        self.root = toga.Box(style=Pack(direction=ROW, flex=1))
        self.root.add(self.sidebar)
        self.main_window.content = self.root
        self.main_window.show()
        configure_cocoa_window_chrome(self.main_window)

        self.views = {
            "clones": CloneListView(clone_service=CloneService(), app=self),
            "environments": EnvironmentListView(environment_service=EnvironmentService(), app=self),
            "recipes": RecipeListView(recipe_service=RecipeService(), app=self),
            "probe": ProbeView(app=self),
            "doctor": DoctorView(app=self),
            "logs": LogsView(app=self),
            "settings": SettingsView(app=self),
        }
        self.loop.create_task(self._run(self.requested_theme))

    async def _refresh(self, name: str) -> None:
        view = self.views[name]
        if name == "clones":
            await view.refresh_clones()
        elif name == "environments":
            await view.refresh_environments()
        elif name == "recipes":
            await view.refresh_recipes()
        elif name == "doctor":
            await view.run_checks()

    def _capture(self, name: str) -> None:
        from toga_cocoa.images import nsdata_to_bytes

        native = self.main_window._impl.native
        view = native.contentView
        bounds = view.bounds
        representation = view.bitmapImageRepForCachingDisplayInRect_(bounds)
        view.cacheDisplayInRect_toBitmapImageRep_(bounds, representation)
        data = representation.representationUsingType_properties_(4, None)  # PNG
        target = self.output_dir / f"{name}.png"
        target.write_bytes(nsdata_to_bytes(data))
        print(f"[snapshot] {target}", flush=True)

    async def _run(self, theme: str) -> None:
        try:
            for index, name in enumerate(self.pages, start=1):
                for child in list(self.root.children):
                    if child is not self.sidebar:
                        self.root.remove(child)
                self.root.add(self.views[name])
                await self._refresh(name)
                await asyncio.sleep(1.2)
                self._capture(f"{index:02d}-{name}")
            print(f"[snapshot] theme={theme} pages={','.join(self.pages)}", flush=True)
        finally:
            await asyncio.sleep(0.2)
            self.exit()


def main(argv: list[str] | None = None) -> int:
    if sys.platform != "darwin":
        print("ui_snapshot.py requires macOS", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("dist/ui-snapshots"),
        help="Directory for the PNG files (default: dist/ui-snapshots)",
    )
    parser.add_argument(
        "--theme",
        choices=("system", "light", "dark"),
        default="system",
        help="Force an appearance for the snapshots.",
    )
    parser.add_argument(
        "--only",
        default="",
        help=f"Comma-separated subset of pages. Available: {', '.join(PAGES)}",
    )
    args = parser.parse_args(argv)

    pages = [page.strip() for page in args.only.split(",") if page.strip()]
    unknown = [page for page in pages if page not in PAGES]
    if unknown:
        parser.error(f"Unknown page(s): {', '.join(unknown)}")
    if not pages:
        pages = list(PAGES)

    patch_cocoa_widgets()
    SnapshotApp(args.out, pages, args.theme).main_loop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
