"""Spreading crowded nodes apart is not every-pair-against-every-other (#146).

This issue listed an O(n²) layout pass. I told the issue the function
"does not exist anywhere in the static tree" — a negative search result
reported as a fact about the codebase. It is at `app.js`, called for
the DEFAULT `spread` layout, and the complaint was right.

Timed with the function lifted out verbatim:

    859 nodes (the mesh today)      121 ms
    1500 nodes (the old ceiling)    366 ms

Two points further apart than `gap` can never push each other, so the
comparison only has to happen between near neighbours. Bucketing into
cells of `gap` a side and comparing each point against its own cell and
the eight around it:

    859 nodes    121 ms -> 27 ms    4.5x
    1500 nodes   366 ms -> 49 ms    7.5x
    3000 nodes   (used to bail out) -> 135 ms

**The layout is the same.** Median nearest-neighbour distance, which is
what the separation is for:

             original   gridded
     500       41.4      41.3
     859       33.4      33.5
    1500       21.0      20.9

and the 10th percentile — the worst crowding left — comes out slightly
better gridded (17.7 vs 16.5 at 859; 8.4 vs 6.4 at 1500).

It is not bit-identical and cannot be: points move as they are compared,
so a different visiting order gives different floats. My first attempt
to compare quality used the single closest pair and was too noisy to
conclude anything from — 4.9 against 2.7 at one size and 0.5 against 1.2
at the next. A distribution was the right instrument; one extreme value
was not.

Verified in a browser afterwards: the graph page draws on the default
`spread` layout, 501 nodes, no page errors.
"""

import re
from pathlib import Path

APP = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "app.js"
).read_text(encoding="utf-8")


def _body() -> str:
    start = APP.index("function separatePositions(")
    return APP[start : APP.index("\n}", start)]


def test_the_function_is_still_here() -> None:
    """The control, and the reason this file exists.

    Every assertion below is of the form "the source looks like X". If
    the function were renamed or moved, `_body()` would raise rather
    than quietly passing — but a reader deserves the check named.
    """
    assert "function separatePositions(" in APP
    assert "separatePositions(graphSeeds, data.nodes)" in APP, (
        "nothing calls it any more, so this file is guarding dead code"
    )


def test_it_does_not_compare_every_pair() -> None:
    """The O(n²) sweep was `for (let b = a + 1; b < points.length; ...)`.

    Its replacement walks a 3x3 neighbourhood of buckets, so the inner
    loop iterates a cell rather than the whole array.
    """
    body = _body()
    assert "b < points.length" not in body, (
        "the inner loop runs over every point again, which is the O(n²) "
        "sweep this issue is about: 121 ms at 859 nodes, 366 ms at 1500"
    )
    assert "cells" in body and "Math.floor(" in body, (
        "the spatial bucketing is gone, so near-neighbour lookup is no longer bounded"
    )


def test_the_neighbourhood_is_the_eight_cells_around() -> None:
    """A cell is `gap` wide, so two points within `gap` are at most one
    cell apart on each axis. Checking fewer than 3x3 would miss pairs
    that should push; checking more would be wasted work.
    """
    body = _body()
    assert re.search(r"ox\s*=\s*-1;\s*ox\s*<=\s*1", body), "the x neighbourhood is not -1..1"
    assert re.search(r"oy\s*=\s*-1;\s*oy\s*<=\s*1", body), "the y neighbourhood is not -1..1"


def test_each_pair_is_still_pushed_once() -> None:
    """`b <= a` does what `b = a + 1` did in the old inner loop.

    Without it a pair inside one cell is pushed twice per pass, at
    double strength, and the layout stops matching the measurements
    above.
    """
    assert "if (b <= a) continue;" in _body()


def test_the_node_ceiling_was_raised_with_the_speedup() -> None:
    """The guard existed because of the complexity, not the mesh.

    Leaving it at 1,500 would keep the spread layout silently switching
    itself off as the mesh grows, which is the part of this that will
    actually bite.
    """
    ceiling = re.search(r"ids\.length > (\d+)", _body())
    assert ceiling, "the node ceiling is gone entirely"
    assert int(ceiling.group(1)) >= 3000, (
        f"the ceiling is still {ceiling.group(1)}, which was set for the "
        f"O(n²) cost that no longer applies"
    )
