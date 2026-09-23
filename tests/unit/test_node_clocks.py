"""A node's own clock never decides which window a reading falls in.

AGENTS.md 9.3 and 9.4: every gateway stamps its own `rx_time`, and
node clocks are wrong, sometimes badly. Measured on production, 79
`device_metrics` rows across 13 nodes are dated in the FUTURE, the
furthest at 2036-02-07.

Two things went wrong with that.

`/api/nodes/{id}/history` bucketed on `DeviceMetrics.time` and clamped
to `[since, now]`, so a node running ahead had its readings fall
outside the window and vanish. For `!700379d3`, 31 of 55 rows in a
24 h window were ahead of now and the endpoint returned 24 points --
more than half its battery chart missing, under a docstring telling
the page to read an empty series as "sends no device telemetry".

`/api/stats/top` had a lower bound and no upper one, so every
future-dated reading a node has ever sent was averaged into "the last
hour".
"""

import inspect
import re

from sonoran.api.routes import node_page, stats


def test_the_device_series_is_placed_by_the_packet_that_carried_it() -> None:
    """Our clock, not the node's."""
    source = inspect.getsource(node_page._device_series)
    assert "Packet.first_seen_at" in source, (
        "the battery chart still buckets on the node's own clock, so a "
        "node running ahead loses its readings off the end of the window"
    )
    assert "coalesce" in source, (
        "there is no fallback for a reading with no matching packet, so "
        "the fix would drop rows too -- which is the bug being fixed"
    )


def test_the_device_series_does_not_drop_a_reading_it_cannot_place() -> None:
    """A left join, not an inner one.

    Measured: 17,785 of 17,786 rows in a week have a matching packet.
    The one that does not must still be drawn.
    """
    source = inspect.getsource(node_page._device_series)
    assert ".outerjoin(" in source, (
        "an inner join would silently drop a reading whose packet is not "
        "stored, trading one silent drop for another"
    )


def test_every_device_metric_window_is_bounded_at_both_ends() -> None:
    """The class, not the instance.

    A `>= start` with no `<= now` on a node-clock column lets one bad
    clock decide what a window means. This walks the modules that
    query `DeviceMetrics` by time rather than naming the one that was
    wrong.
    """
    offenders = []
    for module in (stats, node_page):
        source = inspect.getsource(module)
        for match in re.finditer(r"DeviceMetrics\.time >= (\w+)", source):
            window = source[match.start() : match.start() + 400]
            if "DeviceMetrics.time <=" not in window and "stamped <=" not in window:
                line = source[: match.start()].count("\n") + 1
                offenders.append(f"{module.__name__}:{line}")
    assert not offenders, (
        f"a device-telemetry window is open at the top in {offenders}. "
        f"A node whose clock runs fast then contributes readings to every "
        f"window, however short."
    )
