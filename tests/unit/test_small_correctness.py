"""Four small defects that each made the app state something untrue.

Grouped because each is a few lines; separated here so a failure names
which one came back.
"""

import inspect

from sonoran.api.app import STATIC_DIR
from sonoran.api.routes import graph, leaderboards, nodes


def test_the_leaderboard_cache_is_keyed_on_the_resolved_preset() -> None:
    """`preset_for_channel` strips every non-alphanumeric character.

    So `LongFast`, `l.o.n.g.f.a.s.t` and `--LoNg----FaSt--` all resolve
    to the same preset -- and all three used to be echoed back as
    `preset` and used as the key of a module-global cache that is never
    evicted. A caller could mint unbounded cache entries and miss the
    900-second hold on every one, which is the expensive read that hold
    exists for. Confirmed against the deployed instance before the fix.
    """
    source = inspect.getsource(leaderboards.leaderboards)
    assert "preset = modem.name" in source, (
        "the preset is still taken from the caller's spelling, so the "
        "cache key and the reported preset are both attacker-chosen"
    )
    key = source.index("_link_caches.setdefault(")
    resolved = source.index("preset = modem.name")
    assert resolved < key, "the cache is keyed before the preset is resolved"


def test_the_heard_listing_does_not_guess_how_late_a_gateway_uploads() -> None:
    """A planner hint must not decide what exists.

    The listing assumed a gateway uploads within an hour of a packet
    first being seen. Measured over 24 h: 4,764 of 258,487 observations
    lagged by more than an hour, the worst by 19.5 days. Those packets
    were dropped from the rows AND from X-Total-Count, so the total
    agreed with the listing and both were wrong.
    """
    source = inspect.getsource(nodes.node_packets)
    assert "timedelta(hours=1)" not in source, (
        "the one-hour upload assumption is back; it silently drops the "
        "packets of any gateway that uploads a backlog"
    )


def test_a_link_reports_the_window_not_the_slice() -> None:
    """`report_count` was `len()` of an already-truncated list.

    A link with 71 reports told the reader 50, while the graph edge for
    the same window said 71.
    """
    source = inspect.getsource(graph.link_detail) if hasattr(graph, "link_detail") else ""
    if not source:  # the route function is named by its decorator
        source = inspect.getsource(graph)
        source = source[source.index('@router.get("/link")') :][:2500]
    assert '"report_count": len(reports)' in source, "the count is not of the whole window"
    assert '"reports": shown' in source, "the list is not the truncated slice"
    assert "reports_shown" in source, (
        "nothing tells the reader the list was cut, so a short list reads as the whole evidence"
    )


def test_an_unassessed_board_does_not_claim_nothing_qualifies() -> None:
    """A measurement and an admission must not read the same."""
    source = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    start = source.index("Nothing qualifies in the window.")
    window = source[start - 700 : start + 120]
    assert "data.assessed === false" in window, (
        "an unassessed preset still reports that nothing qualified, which "
        "is a claim about a mesh nobody measured"
    )
