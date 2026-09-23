"""A device's own clock does not get to say when we heard it.

AGENTS.md 9.4: node clocks are wrong, sometimes badly. Position and
telemetry messages carry a timestamp the device wrote, and it used to
be stored unconditionally as the `time` column of five hypertables.

Measured on production before this landed: **79 `device_metrics` rows
dated in the future, across 13 nodes, the furthest at 2036-02-07**.
One node had 31 of its 55 rows in a 24 hour window ahead of now.

That damage is permanent in a way most bad data is not. Retention
deletes by `time`, so a row claiming 2036 is never old enough to
expire, and every "last N hours" window includes it for the next ten
years. The query side was taught to bound its windows (see
`test_node_clocks.py`), but that is whack-a-mole: every new query has
to remember, and the row is still wrong.

**Only the impossible direction is clamped.** A timestamp AHEAD of
when we received the packet cannot be right -- we cannot receive
something before it is sent, so any future stamp is either a clock
fault or a lie. A timestamp BEHIND is ordinary: the mesh stores and
forwards, a gateway can upload a backlog, and one measured upload lag
on this deployment was 19.5 days. Clamping that would throw away
real readings to tidy a column.

This mirrors `rf/store.py:guarded_time`, which the RF side has had
from the start. The slack is wider here because that guard is for
receivers running NTP and this one is for a battery-powered radio.
"""

from datetime import datetime, timedelta

from sonoran.logging import get_logger

logger = get_logger(__name__)


def device_time(
    claimed: datetime, received: datetime, slack: timedelta, *, kind: str, node_num: int | None
) -> datetime:
    """Return the time to store for a device-stamped reading.

    `claimed` is the device's own stamp, `received` is ours. A claim
    beyond `received + slack` is refused and the receipt time used
    instead, because it names a moment that had not happened yet.

    The slack absorbs our own clock being a little behind, which is a
    fault on this side rather than the node's and should not be
    recorded against it.
    """
    if claimed <= received + slack:
        return claimed
    # Said once per reading rather than swallowed. An operator seeing
    # this at a steady rate for one node has learned something true
    # about that node, which a silent clamp would hide.
    logger.warning(
        "%s from %s claimed %s, which is ahead of when we heard it (%s); "
        "storing the receipt time instead. The node's clock is wrong.",
        kind,
        node_num if node_num is not None else "an unknown node",
        claimed.isoformat(),
        received.isoformat(),
    )
    return received
