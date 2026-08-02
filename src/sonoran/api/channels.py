"""Channel grouping for the chat page.

The chat page shows one section for each channel that the system detects.
Each section belongs to a group. The group is the LoRa modem preset when
the channel uses a default preset name. Other channels go to a topic
group, such as Weather, or to the Custom group.
"""

import re

from sqlalchemy import ColumnElement, true
from sqlalchemy.orm import InstrumentedAttribute

# The query value that selects links with no stored channel. Rows
# written before migration 0007 have no channel. Keep this a plain word,
# because it travels in a URL query string.
UNKNOWN_CHANNEL = "unknown"

# The text shown for a channel that has no name.
UNKNOWN_LABEL = "(no channel)"

# The default channel name of each LoRa modem preset.
PRESETS: dict[str, str] = {
    "longfast": "LongFast",
    "longslow": "LongSlow",
    "longmoderate": "LongModerate",
    "verylongslow": "VeryLongSlow",
    "mediumfast": "MediumFast",
    "mediumslow": "MediumSlow",
    "shortfast": "ShortFast",
    "shortslow": "ShortSlow",
    "shortturbo": "ShortTurbo",
}

# Topic groups matched by a word in the channel name.
TOPICS: dict[str, tuple[str, ...]] = {
    "Weather": ("weather", "wx"),
    "Emergency": ("emergency", "emcomm", "ares", "races"),
    "Telemetry": ("telemetry", "sensor"),
}

PRESET_GROUP = "Presets"
CUSTOM_GROUP = "Custom"

# Channels also fall into two tiers, which is what the pickers show.
#
# A core channel is one the mesh proper runs on: any LoRa modem preset,
# and whatever channels the deployment claims as its own. Everything
# else is extra, which is where the special interest channels live.
#
# The tier is not the group. The group says what a channel is about. The
# tier says whether it is part of the mesh or something running beside
# it.
CORE_TIER = "core"
EXTRA_TIER = "extra"

_WORD = re.compile(r"[^a-z0-9]+")


def _normalise(name: str) -> str:
    """Return a lowercase name with separators removed."""
    return _WORD.sub("", name.lower())


def classify(channel: str | None, core: tuple[str, ...] = ()) -> dict[str, str]:
    """Return the label, group, preset, and tier for one channel name.

    The `preset` value is the canonical preset name, or an empty string
    when the channel does not use a default preset name.

    `core` names the channels this deployment claims as its own. A modem
    preset counts as core whether it is listed there or not.
    """
    if not channel:
        return {
            "channel": "",
            "label": UNKNOWN_LABEL,
            "group": CUSTOM_GROUP,
            "preset": "",
            "tier": EXTRA_TIER,
        }

    key = _normalise(channel)
    preset = PRESETS.get(key)
    if preset is not None:
        return {
            "channel": channel,
            "label": preset,
            "group": PRESET_GROUP,
            "preset": preset,
            "tier": CORE_TIER,
        }

    tier = CORE_TIER if key in {_normalise(name) for name in core} else EXTRA_TIER
    for group, words in TOPICS.items():
        if any(word in key for word in words):
            return {
                "channel": channel,
                "label": channel,
                "group": group,
                "preset": "",
                "tier": tier,
            }

    return {
        "channel": channel,
        "label": channel,
        "group": CUSTOM_GROUP,
        "preset": "",
        "tier": tier,
    }


def channel_filter(
    column: InstrumentedAttribute[str | None], channel: str | None
) -> ColumnElement[bool]:
    """Return the filter that selects one channel.

    A value of None selects every channel. The value `unknown` selects
    the rows that have no channel.
    """
    if channel is None:
        return true()
    if channel == UNKNOWN_CHANNEL:
        return column.is_(None)
    return column == channel


def group_order(group: str) -> int:
    """Return the sort position of one group. Lower sorts first."""
    order = [PRESET_GROUP, "Weather", "Emergency", "Telemetry", CUSTOM_GROUP]
    return order.index(group) if group in order else len(order)
