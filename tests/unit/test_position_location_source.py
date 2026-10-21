"""What `position_metrics.location_source` holds (PR 344).

`meshtastic/mesh.proto`, `Position.LocSource`: LOC_UNSET (0),
LOC_MANUAL (1, a position typed in by the owner), LOC_INTERNAL (2, the
node's own GPS), LOC_EXTERNAL (3, a GPS on another device). The heatmap
leaves out LOC_MANUAL. LOC_UNSET means the node did not say, so it is
stored as NULL, as the other fields that a node did not send are.
"""

from sonoran.ingest.handlers.position import location_source_name


def test_a_source_the_node_did_not_give_is_null() -> None:
    assert location_source_name(0) is None


def test_a_known_source_is_stored_by_its_proto_name() -> None:
    assert location_source_name(1) == "LOC_MANUAL"
    assert location_source_name(2) == "LOC_INTERNAL"
    assert location_source_name(3) == "LOC_EXTERNAL"


def test_a_value_newer_than_our_proto_is_null_and_not_an_error() -> None:
    """Would be caught: a newer firmware value must not stop ingest."""
    assert location_source_name(99) is None
