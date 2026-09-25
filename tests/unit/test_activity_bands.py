"""One row per band in the activity chart, not per (port, state) (#198 regression).

#198 grouped the activity query by `payload_state` as well as
`portnum`, so that a `portnum` of 0 could be told apart -- a PKI direct
message from a genuine `UNKNOWN_APP`. That grouping is right and stays.

What it also did was produce a label more than once. **Every port except
0 maps to the same band whatever its state**, so a node with both
readable and unrecorded traffic on one port appeared twice, with its
count split between the copies.

Measured on the running instance before the fix: sixteen rows for nine
bands, with TEXT_MESSAGE_APP, TRACEROUTE_APP, TELEMETRY_APP,
NODEINFO_APP, NEIGHBORINFO_APP, ROUTING_APP and POSITION_APP each listed
twice.
"""

from dataclasses import dataclass

from sonoran.api.routes.nodes import _bands


@dataclass
class Row:
    """One grouped row as the query returns it."""

    portnum: int
    payload_state: str | None
    total: int


def test_one_port_in_two_states_is_one_band() -> None:
    """The regression, stated as the shape that produced it.

    A real node had TEXT_MESSAGE_APP traffic both readable and from
    before `payload_state` was recorded.
    """
    bands = _bands([Row(1, "readable", 40), Row(1, None, 12)])
    assert len(bands) == 1, bands
    assert bands[0] == {"portnum": "TEXT_MESSAGE_APP", "count": 52}


def test_the_counts_are_summed_not_overwritten() -> None:
    """Two halves of one port's traffic are one number.

    A merge that assigned rather than added would silently report only
    the last row, which is a quieter version of the same bug.
    """
    bands = _bands([Row(3, "readable", 100), Row(3, None, 1), Row(3, "no_key", 9)])
    assert bands == [{"portnum": "POSITION_APP", "count": 110}]


def test_port_zero_still_splits_by_state() -> None:
    """The thing #198 was for must survive the fix.

    Port 0 is the one place the state changes the label, so these are
    genuinely different bands and must NOT be merged.
    """
    bands = _bands(
        [
            Row(0, "pki", 8342),
            Row(0, "no_key", 743),
            Row(0, "readable", 7),
            Row(0, None, 15),
        ]
    )
    labels = {band["portnum"] for band in bands}
    assert labels == {
        "UNREADABLE_PKI",
        "UNREADABLE_NO_KEY",
        "UNKNOWN_APP",
        "UNREADABLE_UNRECORDED",
    }, labels
    assert sum(int(band["count"]) for band in bands) == 9107


def test_the_busiest_band_leads() -> None:
    """A stacked chart reads from the bottom, so order carries meaning.

    Merging can move a band past one below it, so the order is settled
    after the merge rather than inherited from the query.
    """
    bands = _bands([Row(1, "readable", 10), Row(3, "readable", 50), Row(1, None, 45)])
    assert [band["portnum"] for band in bands] == ["TEXT_MESSAGE_APP", "POSITION_APP"]
    assert bands[0]["count"] == 55


def test_ties_are_ordered_predictably() -> None:
    """Equal counts must not reorder between requests.

    An unstable order makes a chart's colours shuffle on every poll,
    which reads as data changing when nothing has.
    """
    once = _bands([Row(1, "readable", 5), Row(3, "readable", 5), Row(4, "readable", 5)])
    again = _bands([Row(4, "readable", 5), Row(1, "readable", 5), Row(3, "readable", 5)])
    assert once == again


def test_no_rows_is_no_bands() -> None:
    """A node that sent nothing in the window."""
    assert _bands([]) == []
