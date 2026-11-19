"""Tests for MQTT topic parsing."""

import pytest

from sonoran.mqtt.topics import TopicParseError, parse_topic


def test_parse_encrypted_topic() -> None:
    topic = "msh/US/AZ/2/e/LongFast/!abcd1234"
    parsed = parse_topic(topic)
    assert parsed.region_path == "US/AZ/2"
    assert parsed.payload_format == "e"
    assert parsed.channel == "LongFast"
    assert parsed.gateway_id == "!abcd1234"
    assert parsed.raw == topic


def test_parse_json_topic() -> None:
    parsed = parse_topic("msh/US/json/LongFast/!abcd1234")
    assert parsed.payload_format == "json"


def test_parse_topic_without_gateway_id() -> None:
    """The main broker can put the gateway ID only in the envelope."""
    parsed = parse_topic("msh/US/2/e/LongFast")
    assert parsed.region_path == "US/2"
    assert parsed.payload_format == "e"
    assert parsed.channel == "LongFast"
    assert parsed.gateway_id is None


def test_reject_short_topic() -> None:
    with pytest.raises(TopicParseError):
        parse_topic("msh/US")


def test_reject_wrong_root() -> None:
    with pytest.raises(TopicParseError):
        parse_topic("other/US/AZ/2/e/LongFast/!abcd1234")


def test_reject_unknown_format() -> None:
    with pytest.raises(TopicParseError):
        parse_topic("msh/US/AZ/2/x/LongFast/!abcd1234")


def test_parse_map_report_topic() -> None:
    """Firmware publishes map reports on `<root>/2/map/` (#406).

    Topic seen on the azmsh broker on 2026-11-19. It has no channel and
    no gateway ID; the envelope carries the gateway.
    """
    parsed = parse_topic("msh/US/AZ/Phoenix/2/map/")
    assert parsed.payload_format == "map"
    assert parsed.region_path == "US/AZ/Phoenix/2"
    assert parsed.channel == ""
    assert parsed.gateway_id is None


def test_parse_map_report_topic_with_a_space_in_the_root() -> None:
    """A gateway configured the root `msh/US/AZ/Phoenix ` (trailing space)."""
    parsed = parse_topic("msh/US/AZ/Phoenix /2/map/")
    assert parsed.payload_format == "map"


def test_parse_map_report_topic_without_the_trailing_slash() -> None:
    assert parse_topic("msh/US/AZ/2/map").payload_format == "map"


def test_a_channel_named_map_is_still_a_channel() -> None:
    """Would catch a parser that treats any `map` segment as a map report."""
    parsed = parse_topic("msh/US/AZ/2/e/map/!abcd1234")
    assert parsed.payload_format == "e"
    assert parsed.channel == "map"
