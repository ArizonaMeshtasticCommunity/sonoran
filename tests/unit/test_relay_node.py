"""Which node relayed a packet to each gateway (Logan, 2026-10-17).

`MeshPacket.relay_node` is the last byte of the node that sent the
packet to the gateway (AGENTS.md 9.20). It used to be kept once per
packet, from the first upload, in `mesh_packet_metrics`. Each gateway
hears its own relay, so it is now kept on every upload, in
`packet_seen.relay_node`, and the packet page shows it per gateway.

One byte names no node for sure: in a day with 694 active nodes there
were 3.2 candidates for an average byte and 12 for the worst (9.20). So
the API names the candidates, never one node.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from sonoran.api.routes.packets import relay_candidates
from sonoran.ingest.pipeline import relay_byte
from sonoran.meshtastic import mesh_pb2

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)


def test_the_relay_is_the_low_byte_and_zero_is_none() -> None:
    packet = mesh_pb2.MeshPacket(relay_node=0x4F)
    assert relay_byte(packet) == 0x4F
    assert relay_byte(mesh_pb2.MeshPacket()) is None
    # A wider value is cut to the byte the firmware means.
    assert relay_byte(mesh_pb2.MeshPacket(relay_node=0x1234_564F)) == 0x4F


def test_every_upload_keeps_its_relay() -> None:
    """Both observation builders pass it on, and the row stores it."""
    pipeline = (ROOT / "src/sonoran/ingest/pipeline.py").read_text()
    assert pipeline.count("relay_node=relay_byte(packet)") == 2
    dedup = (ROOT / "src/sonoran/ingest/dedup.py").read_text()
    assert "relay_node=observation.relay_node" in dedup


def _node(num: int, name: str, heard: datetime) -> tuple[int, str, datetime]:
    return (num, name, heard)


def test_candidates_are_every_node_ending_in_the_byte_newest_first() -> None:
    nodes = [
        _node(0xAAAA_AA4F, "Old", NOW - timedelta(hours=20)),
        _node(0xBBBB_BB4F, "New", NOW - timedelta(minutes=5)),
        _node(0xCCCC_CC50, "Other byte", NOW),
    ]
    got = relay_candidates(0x4F, nodes, NOW)
    assert got["byte"] == "4f"
    assert [c["display_name"] for c in got["candidates"]] == ["New", "Old"]
    assert got["candidates"][0]["node_id"] == "!bbbbbb4f"


def test_a_node_not_heard_within_a_day_is_not_a_candidate() -> None:
    """The 3.2 and 12 of AGENTS.md 9.20 were counted over nodes active in a day."""
    nodes = [_node(0xAAAA_AA4F, "Gone", NOW - timedelta(days=2))]
    assert relay_candidates(0x4F, nodes, NOW)["candidates"] == []


def test_no_byte_no_relay() -> None:
    assert relay_candidates(None, [], NOW) is None
