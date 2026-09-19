"""Tests for chat channel grouping."""

import pytest

from sonoran.api.channels import (
    CUSTOM_GROUP,
    PRESET_GROUP,
    UNKNOWN_CHANNEL,
    UNKNOWN_LABEL,
    channel_filter,
    classify,
    group_order,
)
from sonoran.db.models import NeighborMetrics


@pytest.mark.parametrize(
    ("channel", "preset"),
    [
        ("LongFast", "LongFast"),
        ("longfast", "LongFast"),
        ("Long-Fast", "LongFast"),
        ("MediumFast", "MediumFast"),
        ("ShortTurbo", "ShortTurbo"),
    ],
)
def test_preset_channels_are_grouped_together(channel: str, preset: str) -> None:
    """A default preset name gives the canonical preset label."""
    result = classify(channel)
    assert result["preset"] == preset
    assert result["label"] == preset
    assert result["group"] == PRESET_GROUP


def test_weather_channels_get_their_own_group() -> None:
    assert classify("AZ-Weather")["group"] == "Weather"
    assert classify("wx-net")["group"] == "Weather"


def test_emergency_channels_get_their_own_group() -> None:
    assert classify("EmComm")["group"] == "Emergency"


def test_other_channels_are_custom() -> None:
    result = classify("PhoenixMetro")
    assert result["group"] == CUSTOM_GROUP
    assert result["preset"] == ""
    assert result["label"] == "PhoenixMetro"


def test_a_missing_channel_has_a_label() -> None:
    result = classify(None)
    assert result["label"] == "(no channel)"
    assert result["group"] == CUSTOM_GROUP


def test_presets_sort_before_custom() -> None:
    assert group_order(PRESET_GROUP) < group_order("Weather") < group_order(CUSTOM_GROUP)


def test_the_query_sentinel_and_the_display_label_are_different() -> None:
    """The URL value and the shown text must not be the same name.

    The sentinel travels in a query string, so it stays a plain word.
    The label is only for display.
    """
    assert UNKNOWN_CHANNEL == "unknown"
    assert UNKNOWN_LABEL == "(no channel)"
    assert UNKNOWN_CHANNEL != UNKNOWN_LABEL


def test_channel_filter_selects_rows_with_no_channel() -> None:
    """The sentinel builds an IS NULL test, not an equality test."""
    clause = channel_filter(NeighborMetrics.channel, UNKNOWN_CHANNEL)
    assert "IS NULL" in str(clause)


def test_channel_filter_selects_one_named_channel() -> None:
    clause = channel_filter(NeighborMetrics.channel, "LongFast")
    assert "IS NULL" not in str(clause)
    assert "channel" in str(clause)


def test_channel_filter_without_a_channel_selects_everything() -> None:
    clause = channel_filter(NeighborMetrics.channel, None)
    assert str(clause) == "true"


class TestTier:
    """Core is the mesh proper. Extra is what runs beside it."""

    def test_a_modem_preset_is_always_core(self) -> None:
        """A preset needs no configuration to count as core."""
        assert classify("LongFast")["tier"] == "core"
        assert classify("MediumFast")["tier"] == "core"
        assert classify("ShortTurbo", core=())["tier"] == "core"

    def test_a_named_channel_is_core(self) -> None:
        assert classify("azmsh", core=("azmsh",))["tier"] == "core"

    def test_the_name_match_ignores_case_and_separators(self) -> None:
        """`AZ-MSH` and `azmsh` are the same channel to a human."""
        assert classify("AZ-MSH", core=("azmsh",))["tier"] == "core"
        assert classify("azmsh", core=("AZ MSH",))["tier"] == "core"

    def test_everything_else_is_extra(self) -> None:
        for name in ("Weather", "Traffic", "Trivia", "PKI"):
            assert classify(name, core=("azmsh",))["tier"] == "extra", name

    def test_an_unlisted_channel_is_extra(self) -> None:
        assert classify("azmsh")["tier"] == "extra"

    def test_no_channel_is_extra(self) -> None:
        assert classify(None)["tier"] == "extra"

    def test_the_tier_does_not_disturb_the_group(self) -> None:
        """A core channel keeps whatever topic group it had."""
        weather = classify("azmsh-weather", core=("azmsh-weather",))
        assert weather["tier"] == "core"
        assert weather["group"] == "Weather"


class TestTopicGroups:
    """The chat page draws one section per group, in `group_order`."""

    def test_trivia_is_a_game(self) -> None:
        assert classify("Trivia")["group"] == "Games"

    def test_a_misspelled_trivia_stays_visible_in_custom(self) -> None:
        """The lowercase variant is a mistake, and hiding it helps nobody.

        A node owner typed `trivia` and made a second channel nobody else
        was on. It showed up in Custom, which is how anyone noticed.
        """
        assert classify("trivia")["group"] == "Custom"
        assert classify("Trivia")["group"] == "Games"

    def test_traffic_has_its_own_group(self) -> None:
        assert classify("Traffic")["group"] == "Traffic"

    def test_a_core_channel_with_no_topic_is_testing(self) -> None:
        """The channels the operators run themselves are not Custom."""
        assert classify("azmsh", core=("azmsh",))["group"] == "Testing"

    def test_an_unclaimed_channel_is_still_custom(self) -> None:
        assert classify("azmsh")["group"] == "Custom"

    def test_a_brand_new_channel_lands_in_custom(self) -> None:
        assert classify("SomeoneJustMadeThisUp")["group"] == "Custom"


class TestGroupOrder:
    def test_presets_sort_first(self) -> None:
        assert group_order("Presets") == 0

    def test_custom_sorts_last(self) -> None:
        """Custom is the inbox: a new name there is the signal to file it."""
        groups = ["Presets", "Weather", "Games", "Traffic", "Emergency", "Telemetry", "Testing"]
        for group in groups:
            assert group_order(group) < group_order("Custom"), group

    def test_testing_sorts_below_every_topic(self) -> None:
        for group in ("Presets", "Weather", "Games", "Traffic", "Emergency", "Telemetry"):
            assert group_order(group) < group_order("Testing"), group

    def test_an_unknown_group_does_not_collide_with_custom(self) -> None:
        """A group added later must not silently take Custom's place."""
        assert group_order("SomethingAddedLater") != group_order("Custom")
