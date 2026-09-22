"""The palette meets its contrast floors in both themes (#49, #50).

`docs/design/palette.md` states the floors. These tests read the values
out of `app.css`, so a token changed in one theme and not checked in the
other fails here rather than on somebody's screen.
"""

import re
from pathlib import Path

import pytest

CSS = (Path(__file__).parents[2] / "src/sonoran/web/static/app.css").read_text(encoding="utf-8")
INDEX = (Path(__file__).parents[2] / "src/sonoran/web/static/index.html").read_text(
    encoding="utf-8"
)
TOKEN = re.compile(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})\s*;")


def _block(opening: str) -> dict[str, str]:
    start = CSS.index(opening)
    return dict(TOKEN.findall(CSS[start : CSS.index("\n}", start)]))


DARK = _block(":root {")
LIGHT = DARK | _block(':root[data-theme="light"] {')
THEMES = {"dark": DARK, "light": LIGHT}


def _luminance(colour: str) -> float:
    channels = [int(colour[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _ratio(first: str, second: str) -> float:
    one, two = _luminance(first), _luminance(second)
    return (max(one, two) + 0.05) / (min(one, two) + 0.05)


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("token", ["text", "muted", "accent", "good", "warn", "bad", "map-link"])
def test_text_meets_four_and_a_half_to_one(theme: str, token: str) -> None:
    """WCAG 1.4.3: text on a panel."""
    values = THEMES[theme]
    assert _ratio(values[token], values["panel"]) >= 4.5, f"--{token} in {theme}"


@pytest.mark.parametrize("theme", THEMES)
def test_every_mark_meets_three_to_one(theme: str) -> None:
    """WCAG 1.4.11: a packet family or a role drawn on the page."""
    values = THEMES[theme]
    marks = [name for name in values if name.startswith(("pkt-", "role-")) and name != "role-stale"]
    assert marks
    for name in marks:
        assert _ratio(values[name], values["bg"]) >= 3.0, f"--{name} in {theme}"


def test_the_light_theme_gives_every_colour_token_a_value() -> None:
    """A token with no light value keeps its dark value on a light page."""
    light_only = _block(':root[data-theme="light"] {')
    missing = [name for name in DARK if name not in light_only and not name.startswith("safe-")]
    assert not missing, f"no light value for: {missing}"


def test_the_theme_is_set_before_the_page_paints() -> None:
    """The script sits in the head, before any stylesheet, so a light
    reader never sees a dark frame first."""
    head = INDEX[: INDEX.index("</head>")]
    assert head.index("data-theme") < head.index('rel="stylesheet"')
    assert "sonoran.theme" in head
