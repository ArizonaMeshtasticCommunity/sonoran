"""Make the installed-app icons from the tab icon (#322).

Chrome wants a 192 px and a 512 px icon with `"purpose": "any"` before it
offers to install the dashboard. The tab icon is 256 px with a
transparent background. A launcher draws a transparent icon on whatever
it likes, so these two carry a solid tile of the dark page colour, as
the Apple touch icon does.

The mark fills 72 percent of the tile, which is what the touch icon
measures. Run it from the repository root:

    uv run --with pillow python tools/make_app_icons.py

The source is a 256 px raster, so the 512 px icon is an upscale. Make
it from a larger source if one is ever drawn.
"""

from pathlib import Path

from PIL import Image

STATIC = Path("src/sonoran/web/static")
TILE = (0x17, 0x10, 0x0B, 255)
MARK_SHARE = 0.72


def make(size: int) -> Image.Image:
    """Return one square icon of `size` pixels."""
    mark = Image.open(STATIC / "favicon.png").convert("RGBA")
    box = mark.getbbox()
    if box is not None:
        mark = mark.crop(box)
    scale = size * MARK_SHARE / max(mark.size)
    mark = mark.resize(
        (round(mark.width * scale), round(mark.height * scale)), Image.Resampling.LANCZOS
    )
    tile = Image.new("RGBA", (size, size), TILE)
    tile.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return tile.convert("RGB")


def main() -> None:
    for size in (192, 512):
        make(size).save(STATIC / f"icon-{size}.png", optimize=True)


if __name__ == "__main__":
    main()
