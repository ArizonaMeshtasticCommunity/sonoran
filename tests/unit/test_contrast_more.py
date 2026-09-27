"""More contrast when the system asks for it, and forced colours (#285).

Most of the small text on the site is `--muted`. It clears the 4.5:1
floor and nothing more, and there was no `prefers-contrast` rule at all.
These tests read the `prefers-contrast: more` block out of `app.css`,
lay it over each theme, and compute the ratios again, so a value that
drifts under its floor fails here. The e2e journey "more contrast
reaches the page" checks that a browser applies it.
"""

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).parents[2] / "src/sonoran/web/static/app.css").read_text(encoding="utf-8")
TOKEN = re.compile(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;")


def _rule(source: str, opening: str) -> dict[str, str]:
    start = source.index(opening)
    return dict(TOKEN.findall(source[start : source.index("}", start)]))


def _media(query: str) -> str:
    start = CSS.index(f"@media ({query})")
    # The block ends at the first closing brace at the start of a line.
    return CSS[start : CSS.index("\n}", start)]


MORE = _media("prefers-contrast: more")
DARK = _rule(CSS, ":root {")
LIGHT = DARK | _rule(CSS, ':root[data-theme="light"] {')
THEMES = {
    "dark": DARK | _rule(MORE, ":root {"),
    "light": LIGHT | _rule(MORE, ':root[data-theme="light"] {'),
}


def _luminance(colour: str) -> float:
    channels = [int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _ratio(first: str, second: str) -> float:
    one, two = _luminance(first), _luminance(second)
    return (max(one, two) + 0.05) / (min(one, two) + 0.05)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("surface", ["bg", "panel", "panel-2"])
def test_muted_text_reaches_seven_to_one(theme: str, surface: str) -> None:
    """WCAG 1.4.6 (AAA), which is what "more contrast" asks for."""
    values = THEMES[theme]
    assert values["muted"] != (DARK if theme == "dark" else LIGHT)["muted"], "not strengthened"
    assert _ratio(values["muted"], values[surface]) >= 7.0, f"--muted on --{surface} in {theme}"


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("surface", ["bg", "panel", "panel-2"])
def test_rules_reach_three_to_one(theme: str, surface: str) -> None:
    """WCAG 1.4.11: a border that separates one thing from another."""
    values = THEMES[theme]
    assert _ratio(values["line"], values[surface]) >= 3.0, f"--line on --{surface} in {theme}"


def test_table_headings_take_the_text_colour() -> None:
    assert re.search(r"\bth\s*\{\s*color:\s*var\(--text\)", MORE)


def test_the_block_comes_after_the_light_theme() -> None:
    """Same selector weight, so the later rule wins. Before the light
    theme, the light values here would lose to the ordinary ones."""
    assert CSS.index("@media (prefers-contrast: more)") > CSS.index(':root[data-theme="light"] {')


def test_forced_colours_keep_the_legend_swatches() -> None:
    """A swatch whose colour is replaced by the system palette says nothing."""
    forced = _media("forced-colors: active")
    assert ".swatch" in forced
    assert "forced-color-adjust: none" in forced
