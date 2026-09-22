"""Tests for what ingest keeps of a packet's payload (`decode/stored.py`).

The public API holds no channel key, so what ingest keeps is all the
packet page can ever show. These pin the allowlist: the families that
are kept, the field that is dropped, and the families that must never
be kept.
"""

from sonoran.decode.payloads import decode_payload
from sonoran.decode.stored import stored_payload
from sonoran.meshtastic import mesh_pb2, mqtt_pb2, portnums_pb2, storeforward_pb2, telemetry_pb2


def _kept(portnum: int, payload: bytes) -> dict[str, object] | None:
    return stored_payload(decode_payload(portnum, payload))


def test_node_info_is_kept_without_its_mac_address() -> None:
    user = mesh_pb2.User(  # type: ignore[attr-defined]
        id="!a35c3cdc",
        long_name="The Compound 01",
        short_name="C01",
        macaddr=b"\x01\x02\x03\x04\x05\x06",
        hw_model=mesh_pb2.HELTEC_V3,  # type: ignore[attr-defined]
        role=2,
        public_key=b"k" * 32,
    )
    kept = _kept(portnums_pb2.NODEINFO_APP, user.SerializeToString())  # type: ignore[attr-defined]
    assert kept is not None
    assert kept["long_name"] == "The Compound 01"
    assert kept["hw_model"] == "HELTEC_V3"
    assert "public_key" in kept
    assert "macaddr" not in kept


def test_a_routing_acknowledgement_is_kept() -> None:
    """The reason sits in a oneof, so NONE is sent and kept as a value."""
    routing = mesh_pb2.Routing(error_reason=mesh_pb2.Routing.NONE)  # type: ignore[attr-defined]
    kept = _kept(portnums_pb2.ROUTING_APP, routing.SerializeToString())  # type: ignore[attr-defined]
    assert kept == {"error_reason": "NONE"}


def test_a_routing_error_says_which() -> None:
    routing = mesh_pb2.Routing(error_reason=mesh_pb2.Routing.NO_ROUTE)  # type: ignore[attr-defined]
    kept = _kept(portnums_pb2.ROUTING_APP, routing.SerializeToString())  # type: ignore[attr-defined]
    assert kept == {"error_reason": "NO_ROUTE"}


def test_a_map_report_is_kept() -> None:
    report = mqtt_pb2.MapReport(long_name="Ridge", firmware_version="2.7.1")  # type: ignore[attr-defined]
    kept = _kept(portnums_pb2.MAP_REPORT_APP, report.SerializeToString())  # type: ignore[attr-defined]
    assert kept == {"long_name": "Ridge", "firmware_version": "2.7.1"}


def test_bytes_that_do_not_parse_keep_nothing() -> None:
    assert _kept(portnums_pb2.ROUTING_APP, b"\xff\xff\xff") is None  # type: ignore[attr-defined]


def test_text_is_never_kept() -> None:
    """Only STORE_TEXT_MESSAGES decides whether a body is kept."""
    assert _kept(portnums_pb2.TEXT_MESSAGE_APP, b"meet at the trailhead") is None  # type: ignore[attr-defined]


def test_families_that_can_carry_what_a_person_wrote_are_never_kept() -> None:
    store_forward = storeforward_pb2.StoreAndForward(text=b"old chat")  # type: ignore[attr-defined]
    waypoint = mesh_pb2.Waypoint(name="Camp", description="the blue tent")  # type: ignore[attr-defined]
    for portnum, payload in (
        (portnums_pb2.STORE_FORWARD_APP, store_forward.SerializeToString()),  # type: ignore[attr-defined]
        (portnums_pb2.WAYPOINT_APP, waypoint.SerializeToString()),  # type: ignore[attr-defined]
        (portnums_pb2.RANGE_TEST_APP, b"seq 12"),  # type: ignore[attr-defined]
        (portnums_pb2.ADMIN_APP, b"\x08\x01"),  # type: ignore[attr-defined]
    ):
        assert _kept(portnum, payload) is None, portnum


def test_families_with_their_own_table_are_not_kept_twice() -> None:
    telemetry = telemetry_pb2.Telemetry(time=1)  # type: ignore[attr-defined]
    position = mesh_pb2.Position(latitude_i=334000000)  # type: ignore[attr-defined]
    assert _kept(portnums_pb2.TELEMETRY_APP, telemetry.SerializeToString()) is None  # type: ignore[attr-defined]
    assert _kept(portnums_pb2.POSITION_APP, position.SerializeToString()) is None  # type: ignore[attr-defined]
