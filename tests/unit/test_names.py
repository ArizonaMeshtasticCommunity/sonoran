"""Tests for node display names."""

from sonoran.api.names import BROADCAST_NODE_NUM, display_name, format_node_id, name_of


def test_node_id_uses_the_documented_form() -> None:
    assert format_node_id(0x1092) == "!00001092"


def test_broadcast_has_its_own_form() -> None:
    assert format_node_id(BROADCAST_NODE_NUM) == "^all"
    assert format_node_id(None) == "^all"


def test_long_name_wins() -> None:
    assert display_name(0x1092, "Sonoran Peak", "SPK") == "Sonoran Peak"


def test_short_name_is_the_fallback() -> None:
    assert display_name(0x1092, None, "SPK") == "SPK"
    assert display_name(0x1092, "   ", "SPK") == "SPK"


def test_node_id_is_the_last_fallback() -> None:
    assert display_name(0x1092, None, None) == "!00001092"


def test_broadcast_is_named() -> None:
    assert display_name(BROADCAST_NODE_NUM) == "Everyone"


def test_name_of_handles_an_unknown_node() -> None:
    assert name_of({}, 0x1092) == "!00001092"


def test_name_of_reads_the_resolved_map() -> None:
    names = {0x1092: {"display_name": "Sonoran Peak", "node_id": "!00001092"}}
    assert name_of(names, 0x1092) == "Sonoran Peak"
