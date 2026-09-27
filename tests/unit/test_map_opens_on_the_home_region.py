"""The live map opens on a region, not a zoom number (#195).

Two causes, both measured on the running instance on 2026-09-23 at a
1879x622 map box, preset MediumFast:

1. **One far node cancelled the zoom in.** #114 stopped a distant node
   zooming the map *out*. All 401 positioned nodes fit at zoom 6, below
   the configured 7, so no fit ran at all; the 400 inside Arizona fit at
   7, which would have. One node near Oakland decided the opening view
   for the whole mesh.

2. **A fixed integer zoom shows a different area on every screen.** At
   that box, zoom 7 shows about 20 degrees of longitude and Arizona --
   about 6 degrees wide -- filled under a third of the width.

The issue asked which of two readings was wanted: (a) open on Arizona
and let the reader zoom out, or (b) stop them zooming out past it.
**(a)**, because (b) would hide the 148 out-of-state nodes entirely and
#114 requires that they stay reachable.
"""

import re
from pathlib import Path

from sonoran.config import Settings

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"


def _code(name: str) -> str:
    """Return a static file with its comments removed.

    A grep over raw source has produced a false pass in this repository
    four times, most memorably a check for `--set` that matched the
    comment forbidding it.
    """
    text = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


def test_the_home_region_defaults_to_this_deployments_state() -> None:
    """Arizona, and a box that really contains it."""
    settings = Settings(_env_file=None)
    assert settings.map_home_south < 31.4, "the southern border is about 31.33 N"
    assert settings.map_home_north > 37.0, "the northern border is 37.00 N"
    assert settings.map_home_west < -114.8, "the western border reaches about -114.81"
    assert settings.map_home_east > -109.1, "the eastern border is -109.05"


def test_the_home_region_is_a_setting_and_not_a_constant() -> None:
    """Another mesh sets four numbers and app.js does not change.

    #114 and #195 both ask for no geography in the JavaScript. This
    asserts the mechanism exists, and the case below asserts the
    JavaScript does not quietly carry its own copy.
    """
    settings = Settings(
        _env_file=None,
        map_home_south=50.0,
        map_home_west=-5.0,
        map_home_north=59.0,
        map_home_east=2.0,
    )
    assert settings.map_home_south == 50.0
    assert settings.map_home_east == 2.0


def test_no_geography_is_written_into_the_browser_code() -> None:
    """The negative half of the case above.

    A hardcoded Arizona box in app.js would pass every other test here
    and be wrong for every other deployment.
    """
    app = _code("app.js")
    for latitude in ("31.2", "37.1", "-115.0", "-108.9"):
        assert latitude not in app, f"{latitude} is a home-region bound, hardcoded in app.js"


def test_the_map_fits_the_region_rather_than_setting_a_zoom() -> None:
    """`fitBounds` on the home box, so it fills any shape of screen."""
    app = _code("app.js")
    assert "function homeBounds()" in app
    assert "map.fitBounds(home" in app


def test_the_zoom_can_land_between_whole_numbers() -> None:
    """Without a fractional snap the fit rounds down and under-fills.

    This is the second cause, and it is the one a reader sees on a wide
    short window. `fitBounds` with the default `zoomSnap: 1` rounds to a
    whole zoom, which is how a fixed zoom 7 got here in the first place.
    """
    app = _code("app.js")
    assert "zoomSnap" in app
    assert re.search(r"zoomSnap:\s*0\.\d+", app), "zoomSnap is not a fraction"


def test_a_node_outside_the_region_does_not_decide_the_view() -> None:
    """The first cause, closed.

    The fit is computed from nodes inside the home box. Everything else
    is still drawn -- this filters the *vote*, not the map.
    """
    app = _code("app.js")
    assert "home.contains(" in app, "the fit still counts every node, wherever it is"


def test_nodes_outside_the_region_are_still_drawn() -> None:
    """#114 requires they stay reachable by panning or zooming out.

    The filter must apply to the bounds used for fitting and to nothing
    else. If the drawing loop ever filtered on the same test, 148 nodes
    would vanish from the map -- which is reading (b), the one this
    issue decided against.
    """
    app = _code("app.js")
    # The filter is applied to `bounds`, the fit input, and produces a
    # separate name. Drawing reads `nodes`, not `voting`.
    assert "const voting = home" in app
    drawing = app[app.index("const positions = new Map(") :][:400]
    assert "voting" not in drawing, "the draw step is using the filtered set"


def test_the_first_fit_still_never_opens_wider_than_home() -> None:
    """#114's rule survives: the fit only runs when it zooms in."""
    app = _code("app.js")
    assert "if (fitted >= wanted)" in app


# --- and the planner's map, which had the same two causes (§6.5) -------
#
# "The map centred on Arizona rather than the United States" is §6.5's
# wording, and it is the same complaint as #195 on a different page. The
# planner opened with `setView(mapCenter, mapZoom)` and no fractional
# snap, and its first-visit fit counted every node wherever it was.
#
# Measured on this instance, an 842x840 map box at 1500x1050, with the
# node list blocked so the first fit could not hide the answer:
#
#     before  zoom 7,    9.25 deg of longitude, -116.13 to -106.88
#     after   zoom 7.25, 7.78 deg of longitude, -115.84 to -108.06
#
# Arizona is 5.8 degrees wide: 63% of the width and left of centre,
# against 75% and centred.


def test_the_planner_opens_on_the_same_region_as_the_live_map() -> None:
    """The whole statement, condition included.

    Asserting only that `map.fitBounds(home, ...)` appears somewhere let a
    mutation to `if (false)` survive: the call was still in the file and
    never ran. A source check has to read the branch as well as the call,
    and the browser measurement above is what actually proves the view.
    """
    planner = _code("planner.js")
    assert "homeBounds()" in planner, "the planner does not ask for the home region"
    assert "if (home) map.fitBounds(home, { padding: [20, 20] });" in planner, (
        "the planner does not fit the region, or fits it behind a condition that is not "
        "'is there one'"
    )
    assert re.search(r"zoomSnap:\s*0\.\d+", planner), (
        "without a fractional snap the fit rounds down to a whole zoom and under-fills"
    )


def test_the_planner_writes_no_geography_of_its_own() -> None:
    """A hardcoded Arizona box here would be wrong for every other mesh
    and would pass the case above."""
    planner = _code("planner.js")
    for latitude in ("31.2", "37.1", "-115.0", "-108.9"):
        assert latitude not in planner, (
            f"{latitude} is a home-region bound, hardcoded in planner.js"
        )


def test_a_node_outside_the_region_does_not_decide_the_planners_view() -> None:
    """#114's rule, which the planner's own first fit did not have.

    One node near Oakland used to drag the live map over four states. The
    planner had the same fit with the same hole in it, and it matters more
    here: the terrain service holds nothing where that node is.
    """
    planner = _code("planner.js")
    fit = planner[planner.index("const first = !state.nodes.length;") :][:900]
    assert "home.contains([node.lat, node.lon])" in fit, (
        "the planner's first fit still counts every node, wherever it is"
    )


def test_the_planner_still_draws_every_node() -> None:
    """The filter applies to the vote and to nothing else (#114 reading a)."""
    planner = _code("planner.js")
    draw = planner[planner.index("function drawNodes()") :][:600]
    assert "homeBounds" not in draw and "contains(" not in draw, (
        "the drawing loop filters on the home region too, so out-of-state nodes vanish"
    )


def test_the_planner_falls_back_where_no_region_is_configured() -> None:
    planner = _code("planner.js")
    assert "else map.setView(CONFIG.mapCenter" in planner, "the fallback path is gone"


def test_a_deployment_with_no_region_keeps_the_old_behaviour() -> None:
    """`mapHome` absent must fall back, not break the map.

    Every other page still uses the centre and zoom, and a deployment
    upgrading with an old config file has no `mapHome` until it sets
    one.
    """
    app = _code("app.js")
    assert "map.setView(CONFIG.mapCenter" in app, "the fallback path is gone"
