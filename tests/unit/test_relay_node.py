"""Which node relayed a packet to each gateway (Logan, 2026-10-17).

`MeshPacket.relay_node` is the last byte of the node that sent the
gateway its copy (AGENTS.md 9.20). Each upload keeps it, in
`packet_seen.relay_node`, and the packet page names it per gateway.

The firmware never matches that byte against the whole mesh. A byte only
has to be unique among the receiving node's direct neighbours, the
nodes it heard at 0 hops (`NodeDB::resolveLastByte`, NodeDB.cpp:4179-4182,
firmware v2.8.1.8e6a88d). A gateway heard the relay directly, so the
candidates are the nodes that gateway uploaded at 0 hops. A node on
another preset is never one: the gateway cannot hear it. Live,
2026-10-18, 12,645 relayed uploads: one candidate for 79.9 %, at most 6.
Matching the whole mesh listed a LongFast-only node (!9ee99504) on a
MediumFast gateway's upload (!8fa02db0/2591142278, UA Desk).
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


GW = 0xE00C_E8F4
OTHER_GW = 0x5758_0103


def test_candidates_are_this_gateways_direct_neighbours_newest_first() -> None:
    neighbours = {
        GW: [
            _node(0xAAAA_AA4F, "Old", NOW - timedelta(hours=20)),
            _node(0xBBBB_BB4F, "New", NOW - timedelta(minutes=5)),
            _node(0xCCCC_CC50, "Other byte", NOW),
        ]
    }
    got = relay_candidates(0x4F, GW, neighbours, sender=SENDER, hops_taken=2)
    assert got["byte"] == "4f"
    assert [c["display_name"] for c in got["candidates"]] == ["New", "Old"]
    assert got["candidates"][0]["node_id"] == "!bbbbbb4f"


def test_a_node_only_another_gateway_hears_directly_is_not_a_candidate() -> None:
    """The case on !8fa02db0/2591142278: UA Desk never heard DataDemonio (LongFast)."""
    neighbours = {
        GW: [_node(0xD328_D104, "UA Solar", NOW)],
        OTHER_GW: [_node(0x9EE9_9504, "DataDemonio", NOW)],
    }
    got = relay_candidates(0x04, GW, neighbours, sender=SENDER, hops_taken=6)
    assert [c["display_name"] for c in got["candidates"]] == ["UA Solar"]


def test_a_gateway_with_no_direct_neighbour_on_the_byte_names_none() -> None:
    got = relay_candidates(0x4F, GW, {}, sender=SENDER, hops_taken=2)
    assert got["candidates"] == []
    assert got["exact"] is False


def test_no_byte_no_relay() -> None:
    assert relay_candidates(None, GW, {}, sender=SENDER, hops_taken=2) is None


# --- Firmware rules (meshtastic/firmware v2.8.1.8e6a88d) -----------------
# The radio header carries the relay as one byte (RadioInterface.h:54).
# Every send writes the sender's own byte first (FloodingRouter.cpp:22,
# NextHopRouter.cpp:116), and each rebroadcast overwrites it with the
# relayer's. Live check, 2026-10-18: 563 of 563 zero-hop uploads carried
# the sender's byte.


def test_with_no_hop_the_relay_is_the_sender_itself() -> None:
    """Also when the gateway is the sender: its own upload has no neighbour row."""
    got = relay_candidates(
        0xB6, GW, {}, sender=SENDER, sender_name="Cactus Gaming Lounge", hops_taken=0
    )
    assert got["exact"] is True
    assert got["candidates"] == [{"node_id": "!96cc67b6", "display_name": "Cactus Gaming Lounge"}]


def test_a_muted_node_never_relays() -> None:
    """CLIENT_MUTE is not a rebroadcaster (FloodingRouter.cpp:154-158)."""
    nodes = [
        _node(0x0A46_070F, "Meshtastic 070f", NOW, "CLIENT_MUTE"),
        _node(0x567C_E90F, "Buckeye City Hall", NOW, "ROUTER_LATE"),
    ]
    got = relay_candidates(0x0F, GW, {GW: nodes}, sender=SENDER, hops_taken=2)
    assert [c["display_name"] for c in got["candidates"]] == ["Buckeye City Hall"]
    assert got["exact"] is False


def test_after_a_hop_the_sender_is_not_its_own_relay() -> None:
    """A node never rebroadcasts its own packet (isFromUs, NextHopRouter.cpp:34)."""
    nodes = [_node(SENDER, "Sender", NOW), _node(0x2222_22B6, "Relay", NOW)]
    got = relay_candidates(0xB6, GW, {GW: nodes}, sender=SENDER, hops_taken=1)
    assert [c["display_name"] for c in got["candidates"]] == ["Relay"]


def test_hops_unknown_keeps_the_sender_but_not_muted_nodes() -> None:
    """Without hop_start the sender may still be the byte; a muted other node may not."""
    nodes = [
        _node(0x0A46_0700 | 0xB6, "Muted", NOW, "CLIENT_MUTE"),
        _node(SENDER, "Sender", NOW, "CLIENT_MUTE"),
    ]
    got = relay_candidates(0xB6, GW, {GW: nodes}, sender=SENDER, hops_taken=None)
    assert [c["display_name"] for c in got["candidates"]] == ["Sender"]


def test_byte_ff_also_names_a_node_ending_in_00() -> None:
    """getLastByteOfNodeNum sends 0xFF for a node whose last byte is 0 (NodeDB.h:431)."""
    nodes = [_node(0x1234_5600, "Ends in 00", NOW), _node(0x1234_56FF, "Ends in ff", NOW)]
    got = relay_candidates(0xFF, GW, {GW: nodes}, sender=SENDER, hops_taken=1)
    assert sorted(c["display_name"] for c in got["candidates"]) == ["Ends in 00", "Ends in ff"]
