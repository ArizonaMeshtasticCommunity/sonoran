"""Tests for the time the ingest records against a packet.

This is a trap the project has already fallen into once. `rx_time` comes
from whichever gateway relayed the packet, stamped with that gateway's
own clock, and those clocks are wrong. Using it put 349 packet rows in
the future, some more than a day ahead.

See AGENTS.md 9.3 and 9.4.
"""

from datetime import UTC, datetime, timedelta

from sonoran.ingest.pipeline import heard_at
from sonoran.mqtt.client import RawMqttMessage
from sonoran.mqtt.topics import parse_topic

TOPIC = "msh/US/AZ/2/e/LongFast/!00001092"


def _message(received_at: datetime) -> RawMqttMessage:
    """Build a message that says only when this process received it."""
    return RawMqttMessage(
        topic=parse_topic(TOPIC),
        payload=b"",
        received_at=received_at,
    )


def test_it_returns_the_time_this_process_received_the_message() -> None:
    now = datetime.now(UTC)
    assert heard_at(_message(now)) == now


def test_the_time_carries_its_timezone() -> None:
    """A naive time would be compared against aware ones and raise."""
    result = heard_at(_message(datetime.now(UTC)))
    assert result.tzinfo is not None


def test_two_relays_of_one_packet_get_their_own_times() -> None:
    """Each relay is heard when it arrives, not when a gateway says.

    The same packet arrives from many gateways. Each arrival is its own
    observation, and each is stamped with our clock.
    """
    first = datetime.now(UTC)
    second = first + timedelta(seconds=5)
    assert heard_at(_message(first)) == first
    assert heard_at(_message(second)) == second
