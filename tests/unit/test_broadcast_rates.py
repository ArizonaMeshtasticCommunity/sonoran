"""Tests for the broadcast rate report.

This report names real people's nodes, so the rules it applies must be
defensible. It measures a rate and compares it to a firmware default. It
must never claim more than that.
"""

from sonoran.api.routes.stats import (
    BROADCAST_INTERVALS,
    NOTABLE_RATIO,
    ON_MAINS_ABOVE,
    FamilyRate,
    _broadcast_report,
)


def _rate(name: str, count: int, window_seconds: int) -> FamilyRate:
    """Build one family rate the way the endpoint does."""
    default = BROADCAST_INTERVALS[name]
    interval = window_seconds / count
    ratio = default / interval
    return FamilyRate(
        count=count,
        interval_seconds=round(interval),
        default_seconds=default,
        ratio=round(ratio, 1),
        faster_than_default=ratio > 1,
        notable=ratio >= NOTABLE_RATIO,
    )


DAY = 24 * 3600


class TestRates:
    def test_a_node_at_the_default_is_not_flagged(self) -> None:
        """96 positions a day is one every 15 minutes, which is stock."""
        rate = _rate("POSITION_APP", 96, DAY)
        assert rate.interval_seconds == 900
        assert rate.ratio == 1.0
        assert not rate.faster_than_default
        assert not rate.notable

    def test_a_slower_node_is_not_flagged(self) -> None:
        rate = _rate("POSITION_APP", 24, DAY)
        assert rate.ratio < 1
        assert not rate.faster_than_default

    def test_slightly_faster_is_noted_but_not_notable(self) -> None:
        """Twice the default stays inside the noise of reboots."""
        rate = _rate("POSITION_APP", 192, DAY)
        assert rate.ratio == 2.0
        assert rate.faster_than_default
        assert not rate.notable

    def test_three_times_the_default_is_notable(self) -> None:
        rate = _rate("POSITION_APP", 288, DAY)
        assert rate.ratio == 3.0
        assert rate.notable

    def test_node_info_uses_its_own_default(self) -> None:
        """Node info ships at three hours, not fifteen minutes."""
        assert BROADCAST_INTERVALS["NODEINFO_APP"] == 10800
        assert _rate("NODEINFO_APP", 8, DAY).ratio == 1.0

    def test_every_family_has_a_default(self) -> None:
        for name, seconds in BROADCAST_INTERVALS.items():
            assert seconds > 0, name


class TestReport:
    def test_it_collects_the_flagged_families(self) -> None:
        rates = {
            "POSITION_APP": _rate("POSITION_APP", 288, DAY),
            "NODEINFO_APP": _rate("NODEINFO_APP", 8, DAY),
        }
        report = _broadcast_report(0x1234, "Test", rates)
        assert report["node_id"] == "!00001234"
        assert report["packet_count"] == 296
        assert report["notable"] == ["POSITION_APP"]
        assert report["faster_than_default"] == ["POSITION_APP"]

    def test_a_well_behaved_node_flags_nothing(self) -> None:
        report = _broadcast_report(1, "Quiet", {"POSITION_APP": _rate("POSITION_APP", 24, DAY)})
        assert report["notable"] == []
        assert report["faster_than_default"] == []


class TestBattery:
    """The battery is context only (#365).

    The 5-35 % "brownout band" tests that stood here were removed with
    the band: it had no source (AGENTS.md §3A.2), and #365 (its author's
    issue) asks for it to stop deciding anything. A power loop is now
    counted restarts; see `test_power_loop.py`.
    """

    def test_over_a_hundred_percent_means_mains(self) -> None:
        """The firmware reports a powered device above 100, not a full one."""
        assert 101.0 > ON_MAINS_ABOVE
        assert not 101.0 <= ON_MAINS_ABOVE
