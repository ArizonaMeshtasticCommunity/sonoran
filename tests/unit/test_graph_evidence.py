"""A row limit must never decide what evidence exists (AGENTS.md 9.19).

The graph's `strength` -- unknown, one-way, two-way -- and its `each_way`
counts were computed from whatever survived a row cap. The page asks
for no limit, so the default of 2000 applied while a 24 h MediumFast
window held 3367 neighbour and 2867 traceroute rows.

Measured against the deployed instance, the same window at two limits:

    limit=2000   482 nodes  1860 links
    limit=10000  508 nodes  2106 links
    strength changed for 83 of 1860 shared links
    weak->two_way 49, weak->one_way 30, one_way->two_way 4
    246 links absent at 2000

So a link drawn dotted, and described to the reader as "happened, but
too rarely to say it is usable", was solid two-way on the same
window's own evidence. Raising the limit only moved the cut.

Reading the whole window costs 4 ms at the 24 h default and 201 ms at
the 720 h maximum, so the cap was not buying speed.
"""

import inspect

from sonoran.api.routes import graph, leaderboards


def test_the_evidence_readers_take_no_row_limit() -> None:
    """Neither reader may be handed a cap, because both aggregate."""
    for reader in (graph._neighbor_edges, graph._traceroute_edges):
        names = list(inspect.signature(reader).parameters)
        assert "limit" not in names, (
            f"{reader.__name__} still takes a row limit, so the counts it "
            f"produces describe a page of the window rather than the window"
        )


def test_neither_reader_truncates_its_query() -> None:
    """A `.limit(` inside the reader is the same bug written differently."""
    for reader in (graph._neighbor_edges, graph._traceroute_edges):
        source = inspect.getsource(reader)
        assert ".limit(" not in source, (
            f"{reader.__name__} truncates its own read, so the aggregate "
            f"counts only part of the evidence"
        )


def test_the_endpoint_limits_what_is_drawn_not_what_is_counted() -> None:
    """The cut has to happen after the edges are built.

    This reads `_mesh_graph`, which is where the work moved when
    `/api/graph` was given a cache (#148): `mesh_graph` is now the
    wrapper that builds the key. The invariant is unchanged and is
    AGENTS.md 9.19 — a row limit must never decide what evidence
    exists.
    """
    source = inspect.getsource(graph._mesh_graph)
    built = source.index("_traceroute_edges(")
    cut = source.index("ranked[:limit]")
    assert built < cut, "the limit is applied before the evidence is aggregated"
    assert "links_truncated" in source, (
        "a truncated graph does not say so, and a partial picture that "
        "does not admit it is worse than a small one"
    )


def test_the_link_board_reads_the_whole_window() -> None:
    """The leaderboard shared the defect and the same cap.

    72 h of MediumFast already held 9,577 neighbour and 9,332
    traceroute rows against a cap of 10,000 -- 96% of it. Crossing that
    would have demoted links off the board for want of evidence that
    had simply not been read.
    """
    source = inspect.getsource(leaderboards._link_board)
    assert "LINK_ROW_LIMIT" not in source, "the link board still caps its evidence"
    assert not hasattr(leaderboards, "LINK_ROW_LIMIT"), (
        "the cap constant is still defined, so it can be reintroduced by accident"
    )
