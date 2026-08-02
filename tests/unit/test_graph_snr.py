"""Tests for traceroute hop SNR reading."""

from datetime import UTC, datetime

from sonoran.api.routes.graph import Edge, _add
from sonoran.api.traces import hop_snr

NOW = datetime(2026, 8, 1, tzinfo=UTC)


def test_hop_snr_scales_quarter_db() -> None:
    assert hop_snr([20], 0) == 5.0


def test_unmeasured_hop_is_not_a_reading() -> None:
    """INT8_MIN means the firmware could not measure the hop."""
    assert hop_snr([-128], 0) is None


def test_missing_trailing_hop_is_unknown() -> None:
    """A report can be shorter than the hop list."""
    assert hop_snr([4, 8], 2) is None


def test_measured_snr_replaces_an_unmeasured_link() -> None:
    """A later report with a value fills a link that had none."""
    edges: dict[tuple[int, int], Edge] = {}
    _add(edges, Edge(source=1, target=2, kind="traceroute", snr=None, time=NOW))
    _add(edges, Edge(source=1, target=2, kind="traceroute", snr=6.0, time=NOW))
    edge = next(iter(edges.values()))
    assert edge.snr == 6.0
    assert edge.count == 2


def test_a_link_keeps_its_reading_when_a_later_report_has_none() -> None:
    edges: dict[tuple[int, int], Edge] = {}
    _add(edges, Edge(source=1, target=2, kind="traceroute", snr=6.0, time=NOW))
    _add(edges, Edge(source=1, target=2, kind="traceroute", snr=None, time=NOW))
    assert next(iter(edges.values())).snr == 6.0
