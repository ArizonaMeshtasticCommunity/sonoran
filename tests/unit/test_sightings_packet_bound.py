"""The `packet` side of the sightings join is bounded by time (#304).

`packet` is a hypertable on `first_seen_at`. With no bound on that
column TimescaleDB excluded none of its chunks, so the join read all
30 days of `packet` for a window of any size, and `/routes` took 5.6 s
uncached on the slowest node.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from sonoran.api.sightings import PACKET_SLACK, sightings
from sonoran.db.models import PacketSeen

SINCE = datetime(2026, 10, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 7, tzinfo=UTC)


def _sql(*where, **bounds) -> str:  # type: ignore[no-untyped-def]
    query = select(sightings(*where, **bounds))
    return str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_the_joined_half_is_bounded_on_packet_time() -> None:
    sql = _sql(PacketSeen.seen_at >= SINCE, since=SINCE, until=NOW)
    joined = sql.split("UNION ALL", 1)[1]
    assert "packet.first_seen_at >=" in joined
    assert str((SINCE - PACKET_SLACK).date()) in joined
    assert "packet.first_seen_at <=" in joined
    # The half that reads `packet_seen` alone has no `packet` to bound.
    assert "first_seen_at" not in sql.split("UNION ALL", 1)[0]


def test_no_bound_is_added_when_none_is_given() -> None:
    assert "first_seen_at" not in _sql(PacketSeen.seen_at >= SINCE)


def test_the_slack_is_a_day() -> None:
    """Relays and late uploads arrive within minutes. A day is far
    beyond that, and still lets the planner skip every older chunk."""
    assert timedelta(hours=1) < PACKET_SLACK <= timedelta(days=1)
