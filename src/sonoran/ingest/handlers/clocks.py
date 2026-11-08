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

**A clock that was never set is refused too (#408).** Telemetry is
stamped with `getTime()`, which is seconds since boot plus an offset
that stays 0 until a time source sets it (firmware v2.7.26.54e0d8d,
`src/gps/RTC.cpp:440-447`, `src/modules/Telemetry/DeviceTelemetry.cpp:98`).
A node with no GPS, no phone and no NTP therefore says 1970. Stored as
given, the row lands in a 1970 chunk and retention deletes it, so the
node page shows no telemetry while the packets keep arriving. Position
is not affected: it uses `getValidTime`, which sends 0 instead
(`PositionModule.cpp:206-213`). The floor is the first commit of the
firmware (`FIRMWARE_EPOCH`). No device clock before it can be real.

This mirrors `rf/store.py:guarded_time`, which the RF side has had
from the start. The slack is wider here because that guard is for
receivers running NTP and this one is for a battery-powered radio.
"""

from datetime import UTC, datetime, timedelta

from sonoran.logging import get_logger

logger = get_logger(__name__)

# The first commit of the Meshtastic firmware: meshtastic/firmware
# cdb7153071, 2020-02-01T16:30:53Z. No device clock before it is real.
# A stamp before it is seconds since boot from a clock never set (#408).
FIRMWARE_EPOCH = datetime(2020, 2, 1, 16, 30, 53, tzinfo=UTC)


def device_time(
    claimed: datetime, received: datetime, slack: timedelta, *, kind: str, node_num: int | None
) -> datetime:
    """Return the time to store for a device-stamped reading.

    `claimed` is the device's own stamp, `received` is ours. A claim
    beyond `received + slack` is refused and the receipt time used
    instead, because it names a moment that had not happened yet. A
    claim before `FIRMWARE_EPOCH` is a clock that was never set, and the
    receipt time is used for it as well.

    The slack absorbs our own clock being a little behind, which is a
    fault on this side rather than the node's and should not be
    recorded against it.
    """
    if claimed < FIRMWARE_EPOCH:
        # Not logged: a node with no time source does this on every
        # reading, and it is not a fault of the node.
        return received
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
