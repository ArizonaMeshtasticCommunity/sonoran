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
