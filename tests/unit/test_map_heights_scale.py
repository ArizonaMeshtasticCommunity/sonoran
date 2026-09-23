"""Every map on the site grows with the screen (#70).

The report was a planner map that looked "very short" on a 4K monitor:
"map should probably fill the whole div instead of having a max height.
**this may apply to other places maps appear idk yet.**"

It did. The planner was fixed first; `#gaps-map` was the one left, at a
flat `26rem`. Measured at 3320x1797, the resolution it was reported
from:

    #map           1258 px   70% of viewport
    #planner-map   1438 px   80%
    #coverage-map  1258 px   70%
    #rf-map        1258 px   70%
    #gaps-map       416 px   23%   <- the outlier

After, at three viewports:

    3320x1797   gaps 1258 px (70%)
    1440x900    gaps  630 px (70%)
    390x844     gaps  591 px (70%)

It was an outlier at every size, not only on a 4K monitor, so this makes
the gaps map taller on a phone too (416 -> 591 px) -- the same 70% every
other map already took there.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
SHEETS = {name: (STATIC / name).read_text(encoding="utf-8") for name in ("app.css", "gaps.css")}

# Every map container the pages mount a Leaflet map into. `#i-map` is an
# SVG icon symbol, not a map, and is deliberately not here.
MAPS = ("#map", "#planner-map", "#coverage-map", "#rf-map", "#gaps-map")


def _height_rule(selector: str) -> str:
    for source in SHEETS.values():
        for match in re.finditer(rf"{re.escape(selector)}\s*\{{(.*?)\}}", source, flags=re.S):
            block = match.group(1)
            found = re.search(r"(?<!line-)height:\s*([^;]+);", block)
            if found:
                return found.group(1).strip()
    raise AssertionError(f"no height rule found for {selector}")


def test_every_map_height_follows_the_viewport() -> None:
    """A length with no viewport unit cannot grow with the screen."""
    for selector in MAPS:
        rule = _height_rule(selector)
        assert re.search(r"\d+(svh|vh|dvh)", rule), (
            f"{selector} has height {rule!r}, which is a fixed length: it "
            f"stays the same size on a 4K monitor as on a laptop"
        )


def test_every_map_keeps_a_floor() -> None:
    """`70svh` alone collapses the map on a short window.

    The pattern is `max(<floor>, <n>svh)`, so a landscape phone or a
    short browser window still gets a map it can use.
    """
    for selector in MAPS:
        rule = _height_rule(selector)
        assert rule.startswith("max("), (
            f"{selector} has height {rule!r} with no floor, so a short window collapses it"
        )


def test_the_gaps_floor_is_not_lower_than_it_used_to_be() -> None:
    """The fix must not shorten any screen's map.

    The other maps floor at 20rem; the gaps map keeps its old fixed
    26rem, so wherever the floor applies it draws exactly what it drew
    before rather than 6rem less.
    """
    assert "max(26rem," in _height_rule("#gaps-map"), (
        "the gaps map floor moved below the 26rem it was fixed at, which "
        "makes it shorter than before on the screens where the floor wins"
    )
