"""Observations with the hop count they started with (#304).

Whether a sighting was direct is `hop_start = hop_limit` (AGENTS.md
9.5). `hop_limit` is on `packet_seen`, and `hop_start` used to be on
`packet` only, so every such question joined the two.

`/api/nodes/{id}/routes` took 8.3 s on s.azmsh.dev for `!576b1bbe`, and
5.1 s of it was one query over its 156,000 sightings as a gateway. The
join was not the cost: without it the query still took 5.7 s. The
rows were. A node's sightings are spread over about 100,000 heap
pages, and this host cannot hold them in memory. So revision 0017
makes both time indexes of `packet_seen` covering, and a query that
reads only the columns in `models.SIGHTING_INCLUDE` never visits the
heap. On a copy of that node's rows it took 44 ms.

Since revision 0017 ingest writes `hop_start` on each sighting as
well, from the same header as its `hop_limit`. The sender sets it and
a relay does not change it, so it is the value `packet` holds.

**Rows written before 0017 have NULL there, and are never backfilled.**
Rewriting `packet_seen` would rewrite gigabytes on a small host. So a
sighting with its own value is read on its own, and one without it is
joined to `packet` as before. The joined half shrinks as retention
expires the old rows, and after that holds only the packets whose
header had no `hop_start` at all (about 3 in 100 in live data).
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, select, union_all

from sonoran.db.models import Packet, PacketSeen

# The columns a caller may read from `sightings(...)`, plus `hop_start`.
_COLUMNS = (
    PacketSeen.from_node_num,
    PacketSeen.packet_id,
    PacketSeen.gateway_node_num,
    PacketSeen.rx_snr,
    PacketSeen.rx_rssi,
    PacketSeen.hop_limit,
    PacketSeen.seen_at,
)


# How long before a window a packet first seen then can still have a
# sighting inside it. Relays and late uploads arrive within minutes; a
# day is far beyond that, and still lets the planner skip every older
# chunk of `packet`.
PACKET_SLACK = timedelta(days=1)


def sightings(*where: Any, since: datetime | None = None, until: datetime | None = None) -> Any:
    """Return the `packet_seen` rows `where` selects, with `hop_start`.

    `where` is written against `PacketSeen`, and each half gets all of
    it, so the index on the node and the time bound work in both.

    `since` and `until` bound the joined half's `packet` rows as well
    (#304). `packet` is a hypertable on `first_seen_at`, and with no
    bound on it TimescaleDB excluded none of its chunks ("Chunks
    excluded during startup: 0"), so the join read all 30 days of
    `packet` for a window of any size. A packet is first seen before
    any of its sightings, so `until` holds exactly; `since` allows
    `PACKET_SLACK` for a packet first seen just before the window.

    A sighting whose packet row is gone is kept when it carries its own
    `hop_start`. The join dropped it. Both tables expire after the same
    30 days, so this changes only a row at the very edge of retention.
    """
    own = select(*_COLUMNS, PacketSeen.hop_start.label("hop_start")).where(
        PacketSeen.hop_start.is_not(None), *where
    )
    joined = (
        select(*_COLUMNS, Packet.hop_start.label("hop_start"))
        .select_from(PacketSeen)
        .join(
            Packet,
            and_(
                Packet.from_node_num == PacketSeen.from_node_num,
                Packet.packet_id == PacketSeen.packet_id,
            ),
        )
        .where(PacketSeen.hop_start.is_(None), *where)
    )
    if since is not None:
        joined = joined.where(Packet.first_seen_at >= since - PACKET_SLACK)
    if until is not None:
        joined = joined.where(Packet.first_seen_at <= until)
    return union_all(own, joined).subquery("sightings")


def direct(rows: Any) -> Any:
    """No hop used, and uploaded by a node that is not the sender.

    AGENTS.md 9.5 and 9.5.1. `rows` is a `sightings(...)` subquery.
    """
    return and_(
        rows.c.hop_start == rows.c.hop_limit,
        rows.c.from_node_num != rows.c.gateway_node_num,
    )
