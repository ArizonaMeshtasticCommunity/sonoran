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


def _node(
    num: int, name: str, heard: datetime, role: str | None = "CLIENT"
) -> tuple[int, str, datetime, str | None]:
    return (num, name, heard, role)


SENDER = 0x96CC_67B6


def test_candidates_are_every_node_ending_in_the_byte_newest_first() -> None:
    nodes = [
        _node(0xAAAA_AA4F, "Old", NOW - timedelta(hours=20)),
        _node(0xBBBB_BB4F, "New", NOW - timedelta(minutes=5)),
        _node(0xCCCC_CC50, "Other byte", NOW),
    ]
    got = relay_candidates(0x4F, nodes, NOW, sender=SENDER, hops_taken=2)
    assert got["byte"] == "4f"
    assert [c["display_name"] for c in got["candidates"]] == ["New", "Old"]
    assert got["candidates"][0]["node_id"] == "!bbbbbb4f"


def test_a_node_not_heard_within_a_day_is_not_a_candidate() -> None:
    """The 3.2 and 12 of AGENTS.md 9.20 were counted over nodes active in a day."""
    nodes = [_node(0xAAAA_AA4F, "Gone", NOW - timedelta(days=2))]
    assert relay_candidates(0x4F, nodes, NOW, sender=SENDER, hops_taken=2)["candidates"] == []


def test_no_byte_no_relay() -> None:
    assert relay_candidates(None, [], NOW, sender=SENDER, hops_taken=2) is None


# --- Firmware rules (meshtastic/firmware v2.8.1.8e6a88d) -----------------
# The radio header carries the relay as one byte (RadioInterface.h:54).
# Every send writes the sender's own byte first (FloodingRouter.cpp:22,
# NextHopRouter.cpp:116), and each rebroadcast overwrites it with the
# relayer's. Live check, 2026-10-18: 563 of 563 zero-hop uploads carried
# the sender's byte.


def test_with_no_hop_the_relay_is_the_sender_itself() -> None:
    nodes = [
        _node(SENDER, "Cactus Gaming Lounge", NOW),
        _node(0x1111_11B6, "Same byte", NOW),
    ]
    got = relay_candidates(0xB6, nodes, NOW, sender=SENDER, hops_taken=0)
    assert got["exact"] is True
    assert [c["node_id"] for c in got["candidates"]] == ["!96cc67b6"]


def test_a_muted_node_never_relays() -> None:
    """CLIENT_MUTE is not a rebroadcaster (FloodingRouter.cpp:154-158)."""
    nodes = [
        _node(0x0A46_070F, "Meshtastic 070f", NOW, "CLIENT_MUTE"),
        _node(0x567C_E90F, "Buckeye City Hall", NOW, "ROUTER_LATE"),
    ]
    got = relay_candidates(0x0F, nodes, NOW, sender=SENDER, hops_taken=2)
    assert [c["display_name"] for c in got["candidates"]] == ["Buckeye City Hall"]
    assert got["exact"] is False


def test_after_a_hop_the_sender_is_not_its_own_relay() -> None:
    """A node never rebroadcasts its own packet (isFromUs, NextHopRouter.cpp:34)."""
    nodes = [_node(SENDER, "Sender", NOW), _node(0x2222_22B6, "Relay", NOW)]
    got = relay_candidates(0xB6, nodes, NOW, sender=SENDER, hops_taken=1)
    assert [c["display_name"] for c in got["candidates"]] == ["Relay"]


def test_hops_unknown_keeps_the_sender_but_not_muted_nodes() -> None:
    """Without hop_start the sender may still be the byte; a muted other node may not."""
    nodes = [
        _node(0x0A46_0700 | 0xB6, "Muted", NOW, "CLIENT_MUTE"),
        _node(SENDER, "Sender", NOW, "CLIENT_MUTE"),
    ]
    got = relay_candidates(0xB6, nodes, NOW, sender=SENDER, hops_taken=None)
    assert [c["display_name"] for c in got["candidates"]] == ["Sender"]


def test_byte_ff_also_names_a_node_ending_in_00() -> None:
    """getLastByteOfNodeNum sends 0xFF for a node whose last byte is 0 (NodeDB.h:431)."""
    nodes = [_node(0x1234_5600, "Ends in 00", NOW), _node(0x1234_56FF, "Ends in ff", NOW)]
    got = relay_candidates(0xFF, nodes, NOW, sender=SENDER, hops_taken=1)
    assert sorted(c["display_name"] for c in got["candidates"]) == ["Ends in 00", "Ends in ff"]
