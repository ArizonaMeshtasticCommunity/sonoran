"""The first screen of a node page (#95, and its collision with #103).

#95's "Done when" has two clauses: the first screen shows the node's
identity and device information without scrolling on a typical laptop,
**and** one widget summarises health.

#103, filed later, asks for a map of the node "below the first row of
panels". Both landed, and together they broke the second clause of #95
while satisfying the first. Measured on a node page with the health
summary inside the grid under the map:

    1440 x 900     Identity 119    map 631    Health 1069   below fold
    1680 x 1050    Identity 119    map 586    Health 1081   below fold

The summary now sits between the identity row and the map:

    1440 x 900     Identity 119    Health 631   map 768     all above
    1680 x 1050    Identity 119    Health 586   map 723     all above

One panel's worth of prose costs the map nothing and puts the health
line where the issue asked for it. Checked at 320 px too: no sideways
scroll, the map still renders (254 x 243), and "View all checks" is
still there — at that width the identity panels stack, so health is far
down the page, which is what a phone does to every page here.
"""

import re
from pathlib import Path

APP = (
    Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static" / "app.js"
).read_text(encoding="utf-8")


def _assembly() -> str:
    """The region of `loadNodeDetail` that lays the node page out.

    From the summary row's construction through the `replace(body, ...)`
    call, not just the call. #193.3 moved the health summary INSIDE the
    summary row -- it shares a grid track with Device, to fill the space
    Activity's height left empty -- so a window over the `replace` call
    alone can no longer see it, and these tests failed with
    `ValueError: substring not found` while the ordering they guard was
    intact and in fact better: health starts where Device ends rather
    than where the whole row ends.

    The assertions below are unchanged. Only the window they read moved,
    which is the third time in this session that a window sized to
    yesterday's code has been mistaken for a broken property.
    """
    start = APP.index("  const summary = el('div', { class: 'grid summary-row' }")
    return APP[start : APP.index("const id = encodeURIComponent(nodeId);", start)]


def test_the_health_summary_comes_before_the_map() -> None:
    """Order is the whole fix, so order is what this asserts.

    Putting the map first is the natural reading of #103 and it pushes
    the health summary off the first screen, which is half of #95.
    """
    body = _assembly()
    health = body.index("health")
    node_map = body.index("nodeMapPanel(detail)")
    assert health < node_map, (
        "the node map is built before the health summary, which puts health "
        "below the fold on a 1440x900 laptop (measured at y=1069) and leaves "
        "#95's second clause unmet"
    )


def test_the_identity_row_still_comes_first() -> None:
    """#95's first clause. The summary row is what it is about.

    Identity is the first cell of the row; health is inside the second,
    stacked under Device. So the check is that `identityPanel` is built
    before `health`, which holds whether health is a row of its own or a
    panel inside the row.
    """
    body = _assembly()
    assert body.index("identityPanel(node)") < body.index("health"), (
        "something now precedes the identity row, which is the one thing #95 asked to be at the top"
    )


def test_the_map_is_still_on_the_page() -> None:
    """#103 must not be undone by making room for #95.

    The lazy way to satisfy #95 is to drop the map. Measured after the
    change, the map is 1102x342 at 1440 and 3502x480 at 3840.
    """
    assert "nodeMapPanel(detail)" in _assembly()


def test_the_full_checklist_is_still_one_click_away() -> None:
    """#95: "All the information ... is still one click away."."""
    assert "View all checks" in APP, "the disclosure that holds the full health list is gone"
    assert re.search(r"health-full", APP), "the full checklist container is gone"
