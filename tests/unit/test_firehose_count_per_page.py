"""The firehose counts uploads for each row of its page, never as a join.

On 2026-09-30 the count was a LEFT JOIN, PostgreSQL inlined the page
CTE and joined every packet to every observation first, and the parallel
hash overflowed the database container's `/dev/shm`. The firehose then
answered 500 on every load. See `list_packets` in `api/routes/packets.py`.
"""

import inspect

from sonoran.api.routes import packets


def test_the_count_is_a_correlated_read_and_not_a_join() -> None:
    source = inspect.getsource(packets.list_packets)
    assert ".correlate(Packet)" in source
    assert ".scalar_subquery()" in source
    assert "outerjoin(PacketSeen" not in source, "a join lets the planner count every packet"


def test_the_page_is_joined_back_on_its_time_too() -> None:
    """So each lookup reads one chunk of `packet`, not all of them."""
    source = inspect.getsource(packets.list_packets)
    assert "page.c.at == Packet.first_seen_at" in source
