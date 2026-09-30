"""The packet listing picks its page before it counts observations.

`/api/packets` backs the firehose. It used to group the whole join of
`packet` to `packet_seen` before applying the limit, so the limit could
not push down: the planner read every chunk of `packet` on every
request and spilled the sort to disk, to return a hundred rows.

Measured on production, for the same hundred rows:

    old   5 sequential scans, external merge ~10 MB, 207-227 ms
    new   0 sequential scans, quicksort 28 kB,         9-14 ms

Both return the same rows -- checked with EXCEPT in both directions,
0 and 0.

This is the shape `map.py` already uses, and its comment describes the
same failure. The test is here so the third recurrence is caught in
review rather than in a profile.

**The CTE alone did not hold (2026-09-30).** PostgreSQL inlines it, and
with the count as a LEFT JOIN the planner joined every packet to every
observation first: a parallel hash of 7.7M rows that overflowed the
database container's `/dev/shm`, and the firehose answered 500 on every
load. The count is a correlated read of each row of the page now, which
leaves no join to reorder.
"""

import inspect
import re

from sonoran.api.routes import packets


def _source() -> str:
    return inspect.getsource(packets.list_packets)


def _picked(source: str) -> int:
    """Where the page statement starts, however the formatter wraps it."""
    found = re.search(r"picked = \(?\s*select\(", source)
    assert found is not None, "the listing no longer picks its page"
    return found.start()


def test_the_page_is_chosen_before_the_observations_are_counted() -> None:
    """A CTE that limits `packet` first, then counts."""
    source = _source()
    assert ".cte(" in source, (
        "the listing does not pick its page in a separate statement, so the LIMIT cannot push down"
    )
    counted = source.index(".correlate(Packet)")
    assert _picked(source) < counted, "the page must be chosen before uploads are counted"


def test_the_count_is_a_correlated_read_and_not_a_join() -> None:
    """A join lets the planner count every packet before it picks the page."""
    source = _source()
    assert ".scalar_subquery()" in source
    assert "outerjoin(PacketSeen" not in source


def test_the_page_is_joined_back_on_its_time_too() -> None:
    """So each lookup reads one chunk of `packet`, not all of them."""
    assert "page.c.at == Packet.first_seen_at" in _source()


def test_every_filter_narrows_the_page_not_the_result() -> None:
    """A filter applied after the limit would return too few rows.

    This is the way to get the restructure subtly wrong: leave a
    `where` on the outer statement and the limit picks a hundred rows
    before the filter runs, so a narrow search quietly returns nothing.
    """
    source = _source()
    body = source[_picked(source) :]
    page_built = body.index('page = picked.cte("page")')
    before = body[:page_built]
    after = body[page_built:]
    for name in ("portnum", "from_node", "to_node", "channel", "since", "before"):
        assert f"if {name}" in before, f"the {name} filter is not applied to the page"
    assert "statement = statement.where(" not in after, (
        "a filter is applied after the page was picked, so it narrows the "
        "hundred rows already chosen instead of choosing which hundred"
    )
