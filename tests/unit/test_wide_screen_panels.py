"""Panels stop growing somewhere (#70).

Tyler, on a 4K monitor: *"in general, UI is worse on larger screens."*
Measured on the dashboard before the fix, `main` at three viewports:

    1440 x 900    main 1200   4 stat tiles at 272 px   fine
    2560 x 1440   main 2320   4 tiles at 552 px
    3840 x 2160   main 3600   4 tiles at 872 px        absurd

`auto-fit` **collapses** the tracks it cannot fill — at 3840 the grid
declared twelve and zeroed eight — so extra width never becomes extra
columns. It is shared among however many panels exist, and a tile
holding one number ends up 872 px wide.

**The cap is on the grid, not on the track, and that is the whole
point of this file.** Capping the track also fixes 3840 — measured,
872 px down to 416 — and it BREAKS 1440, taking the dashboard from four
columns to two, because `auto-fit` computes its repetition count from
the track's max sizing function when that is definite: 1200 / 26rem = 2.
A container cap leaves the track `1fr`, so the count still comes off
the 17 rem floor and every width below the cap is unchanged.

Verified in a browser at four widths after the change, on the dashboard
and on a node page:

    320 px    unchanged, no sideways scroll
    1440 px   4 tiles at 272 px — byte-for-byte what it was
    2560 px   4 tiles at 388 px, grid capped at 1600
    3840 px   4 tiles at 388 px, grid capped at 1600

and the planner map still measures 3182 x 1728 at 3840, so the fix for
the panels did not undo the fix for the map that this same issue opened
with.
"""

import re
from pathlib import Path

CSS = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "app.css"
).read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    """The body of the first rule for a selector, comments stripped."""
    body = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    start = body.index(selector)
    return body[start : body.index("}", start)]


def test_the_panel_grid_has_a_ceiling() -> None:
    rule = _rule(".grid {")
    assert "max-width:" in rule, (
        "the panel grid has no maximum width, so at 3840 px four stat tiles "
        "share the whole row and each is 872 px wide"
    )
    assert "margin-inline: auto" in rule, "the capped grid is not centred, so it hugs one edge"


def test_the_track_is_still_a_fraction_and_not_a_fixed_ceiling() -> None:
    """The regression this fix went through once, held as a test.

    `auto-fit` takes its repetition count from the track's MAX sizing
    function when that is definite. Give the track a rem ceiling and
    1440 px goes from four columns to two — a regression at the
    commonest desktop width, in the name of fixing 4K.
    """
    rule = _rule(".grid {")
    columns = re.search(r"grid-template-columns:([^;]+);", rule)
    assert columns, "the panel grid no longer declares its columns here"
    assert "1fr" in columns.group(1), (
        f"the panel grid's track has a definite maximum "
        f"({columns.group(1).strip()!r}). `auto-fit` then computes its column "
        f"count from that maximum, and 1440 px drops from four columns to two. "
        f"Cap the grid, not the track."
    )


def test_the_floor_that_keeps_320px_working_is_untouched() -> None:
    """WCAG 2.2 SC 1.4.10 Reflow, which `min(..., 100%)` exists for.

    A bare `minmax(17rem, ...)` floor lays out 272 px of content inside
    a 320 px window and scrolls the document sideways.
    """
    for selector in (".grid {", ".grid.two {"):
        rule = _rule(selector)
        assert "min(" in rule and "100%)" in rule, (
            f"{selector} lost its `min(<track>, 100%)` floor guard, so it can "
            f"lay out wider than its container at 320 px"
        )


def test_maps_are_not_capped_by_the_same_rule() -> None:
    """#70 opened with "map should probably fill the whole div".

    The fix for the panels must not undo the fix for the map. Measured
    after this change: the planner map is 3182 x 1728 at 3840 x 2160.
    """
    rule = _rule(".grid {")
    assert "leaflet" not in rule and "map" not in rule, (
        "the grid cap now names a map selector, which would bound the map too"
    )
