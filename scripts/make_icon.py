#!/usr/bin/env python3
"""Generate the TwinSpace application icon (logo.icns + logo.png).

Design: an Apple Big Sur style rounded tile with a blue gradient, carrying two
overlapping application-window cards — a translucent "ghost" window behind and
a solid window in front with macOS traffic-light controls — reading directly as
"one app, many isolated instances".

Requires Pillow (``pip install pillow``) and macOS ``iconutil``.
Usage: python scripts/make_icon.py   (writes resource/images/logo.png/.icns)
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESOURCE_DIR = PROJECT_ROOT / "resource" / "images"

S = 2048  # supersample canvas; final icon is 1024

TILE_TOP = 102
TILE_BOTTOM = S - 102
TILE_LEFT = 102
TILE_RIGHT = S - 102
TILE_RADIUS = 400  # ≈22% of the tile edge, Apple squircle feel

GRAD_TOP = (64, 156, 255)    # light Apple blue
GRAD_BOTTOM = (0, 84, 200)   # deep Apple blue


def rounded_tile(size: int) -> Image.Image:
    """Build the gradient rounded-rect tile with a soft top-left highlight."""
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (TILE_LEFT, TILE_TOP, TILE_RIGHT, TILE_BOTTOM), radius=TILE_RADIUS, fill=255
    )

    gradient = Image.new("RGBA", (size, size))
    top, bottom = GRAD_TOP, GRAD_BOTTOM
    span = TILE_BOTTOM - TILE_TOP
    px = gradient.load()
    for y in range(TILE_TOP, TILE_BOTTOM):
        ratio = (y - TILE_TOP) / span
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3)) + (255,)
        for x in range(TILE_LEFT, TILE_RIGHT):
            px[x, y] = color

    tile.paste(gradient, (0, 0), mask)

    # Soft radial highlight in the upper-left for a glassy feel.
    highlight = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(highlight).ellipse(
        (-500, -650, 1250, 900), fill=(255, 255, 255, 70)
    )
    highlight = highlight.filter(ImageFilter.GaussianBlur(180))
    tile = Image.alpha_composite(tile, Image.composite(highlight, Image.new("RGBA", tile.size, (0, 0, 0, 0)), mask))

    # Hairline inner border.
    border = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(border).rounded_rectangle(
        (TILE_LEFT, TILE_TOP, TILE_RIGHT, TILE_BOTTOM),
        radius=TILE_RADIUS,
        outline=(255, 255, 255, 90),
        width=8,
    )
    tile = Image.alpha_composite(tile, border)
    return tile


def window_card(
    box: tuple[int, int, int, int],
    radius: int,
    fill: tuple[int, int, int, int],
    chrome: bool,
) -> Image.Image:
    """Draw one floating app-window card (optionally with traffic lights)."""
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    left, top, right, bottom = box
    draw.rounded_rectangle(box, radius=radius, fill=fill)
    if chrome:
        title_h = 130
        draw.rounded_rectangle(
            (left, top, right, top + title_h + radius),
            radius=radius,
            fill=(238, 240, 246, 255),
        )
        draw.rectangle((left, top + title_h, right, top + title_h), fill=(210, 214, 224, 255))
        draw.rectangle((left, top + title_h + radius // 2, right, bottom), fill=fill)
        dot_r = 26
        cy = top + title_h // 2 + 8
        for i, color in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
            cx = left + 90 + i * 84
            draw.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r), fill=color + (255,))
        # Two content rows suggest an app body (opaque tones render cleanly).
        draw.rounded_rectangle(
            (left + 110, top + title_h + 120, right - 380, top + title_h + 210),
            radius=44,
            fill=(168, 190, 222, 255),
        )
        draw.rounded_rectangle(
            (left + 110, top + title_h + 280, right - 620, top + title_h + 370),
            radius=44,
            fill=(198, 212, 232, 255),
        )
    return layer


def build_icon() -> Image.Image:
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    canvas = Image.alpha_composite(canvas, rounded_tile(S))

    back_box = (830, 350, 1780, 1180)
    front_box = (300, 620, 1400, 1700)
    front_radius = 120

    # Drop shadow under the front card.
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (front_box[0] - 10, front_box[1] + 20, front_box[2] + 10, front_box[3] + 60),
        radius=front_radius,
        fill=(10, 40, 90, 110),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(60))
    canvas = Image.alpha_composite(canvas, shadow)

    # Ghost window behind.
    canvas = Image.alpha_composite(
        canvas, window_card(back_box, 110, (255, 255, 255, 88), chrome=False)
    )
    # Solid window in front.
    canvas = Image.alpha_composite(
        canvas, window_card(front_box, front_radius, (255, 255, 255, 250), chrome=True)
    )
    return canvas


ICONSET_SIZES = [16, 32, 64, 128, 256, 512, 1024]


def write_iconset(master_1024: Image.Image, iconset_dir: Path) -> None:
    iconset_dir.mkdir(parents=True, exist_ok=True)
    for size in ICONSET_SIZES:
        img = master_1024.resize((size, size), Image.LANCZOS)
        img.save(iconset_dir / f"icon_{size}x{size}.png")
        if size <= 512:
            img = master_1024.resize((size * 2, size * 2), Image.LANCZOS)
            img.save(iconset_dir / f"icon_{size}x{size}@2x.png")


def main() -> None:
    master = build_icon()
    master_1024 = master.resize((1024, 1024), Image.LANCZOS)

    RESOURCE_DIR.mkdir(parents=True, exist_ok=True)
    master_1024.save(RESOURCE_DIR / "logo.png")

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "logo.iconset"
        write_iconset(master_1024, iconset)
        out = RESOURCE_DIR / "logo.icns"
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True
        )

    # Keep the documentation site logo in sync.
    for site_logo in (
        PROJECT_ROOT / "docs/guide/en/assets/images/logo.png",
        PROJECT_ROOT / "docs/guide/zh-cn/assets/images/logo.png",
    ):
        if site_logo.parent.exists():
            shutil.copyfile(RESOURCE_DIR / "logo.png", site_logo)

    print(f"wrote {RESOURCE_DIR / 'logo.png'} and {RESOURCE_DIR / 'logo.icns'}")


if __name__ == "__main__":
    main()
