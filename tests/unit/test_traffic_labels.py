"""A `portnum` of 0 must not be drawn as `UNKNOWN_APP` (#157).

0 is both the real Meshtastic port `UNKNOWN_APP` and the sentinel the
ingest writes when it could not read a packet. Three route modules held
a byte-identical `_portnum_name` and all three resolved 0 to
`UNKNOWN_APP`. A census against production over 168 h measured what
those rows really were:

    pki_to_one_recipient   8342   91.7%
    opaque_no_key_opened    743    8.2%
    decoded_with_payload      7    0.1%
    decoded_empty_payload     1    0.0%

So the label was right about roughly one packet in a thousand, and the
chart told operators their mesh was full of unknown application traffic
when it was full of direct messages.
"""

import pytest

from sonoran.decode.payload_state import PayloadState
from sonoran.decode.portnums import (
    NO_KEY_LABEL,
    PKI_LABEL,
    UNRECORDED_LABEL,
    portnum_name,
    traffic_label,
)


def test_a_real_port_is_unchanged_whatever_the_state_says() -> None:
    """Only port 0 is ambiguous, so only port 0 consults the state.

    This is the non-regression half. Every other band on every chart
    has to keep the name it had, or this change is a rename of the
    whole dashboard rather than a fix to one bucket.
    """
    for state in (None, PayloadState.READABLE, PayloadState.NO_KEY, PayloadState.PKI):
        assert traffic_label(1, state) == "TEXT_MESSAGE_APP"
        assert traffic_label(3, state) == "POSITION_APP"
        assert traffic_label(67, state) == "TELEMETRY_APP"


def test_the_three_unreadable_states_get_three_names() -> None:
    """The whole point: one bucket becomes the things it was made of."""
    assert traffic_label(0, PayloadState.PKI) == PKI_LABEL
    assert traffic_label(0, PayloadState.NO_KEY) == NO_KEY_LABEL
    assert len({PKI_LABEL, NO_KEY_LABEL, UNRECORDED_LABEL}) == 3


def test_a_readable_packet_on_port_zero_is_still_unknown_app() -> None:
    """The 0.1% that the old label was right about keeps its name.

    A key opened this packet and the port it carried really was 0, so
    `UNKNOWN_APP` is the true answer and must survive the change.
    """
    assert traffic_label(0, PayloadState.READABLE) == "UNKNOWN_APP"


def test_a_row_with_no_recorded_state_says_so() -> None:
    """NULL is not folded into the commonest value.

    Every packet stored before revision 0015 is NULL here. Calling them
    PKI because 91.7% of a later window was PKI would be inventing
    evidence -- the move that put `WEAK` on 90% of the links in #149.
    """
    assert traffic_label(0, None) == UNRECORDED_LABEL
    assert traffic_label(0, None) not in {PKI_LABEL, "UNKNOWN_APP"}


def test_the_new_names_cannot_collide_with_a_port_name() -> None:
    """`UNREADABLE_*` must not be, or become, a real Meshtastic port.

    If firmware ever shipped a port with one of these names, a chart
    band would merge two unrelated things silently. Cheap to check, and
    it fails on the day the vendored protobuf changes rather than on
    the day somebody notices the chart.
    """
    for label in (PKI_LABEL, NO_KEY_LABEL, UNRECORDED_LABEL):
        assert portnum_name_is_unknown(label)


def portnum_name_is_unknown(label: str) -> bool:
    """True when no port number in the vendored schema has this name."""
    from sonoran.meshtastic import portnums_pb2

    try:
        portnums_pb2.PortNum.Value(label)  # type: ignore[attr-defined]
    except ValueError:
        return True
    return False


def test_the_collision_check_can_fail() -> None:
    """Positive control for the test above.

    An emptiness check that cannot find anything proves nothing, and
    this repository has shipped that mistake more than once.
    """
    assert portnum_name_is_unknown("TEXT_MESSAGE_APP") is False


def test_an_unknown_state_string_does_not_crash_the_chart() -> None:
    """A value this code does not know about is a bug, and it says so.

    Better a loud failure here than a band quietly named after a port
    number that the row does not have.
    """
    with pytest.raises(ValueError):
        traffic_label(0, "something_else_entirely")


def test_portnum_name_still_answers_the_number_for_an_unknown_port() -> None:
    """The three route copies answered `str(value)`, not `UNKNOWN_n`.

    `decode/payloads.py` keeps its own helper that answers
    `UNKNOWN_{n}`, because it names a decoded payload rather than a
    chart band. Folding the two together to reduce a count of copies
    would change one of those answers.
    """
    assert portnum_name(9999) == "9999"
