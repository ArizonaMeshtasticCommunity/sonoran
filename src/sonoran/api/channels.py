"""Channel grouping for the chat page.

The chat page shows one section for each channel that the system detects.
Each section belongs to a group. The group is the LoRa modem preset when
the channel uses a default preset name. Other channels go to a topic
group, such as Weather, or to the Custom group.
"""

import re

from sqlalchemy import ColumnElement, true
from sqlalchemy.orm import InstrumentedAttribute

from sonoran.radio.presets import PRESETS as _PRESET_TABLE

# The query value that selects links with no stored channel. Rows
# written before migration 0007 have no channel. Keep this a plain word,
# because it travels in a URL query string.
UNKNOWN_CHANNEL = "unknown"

# The text shown for a channel that has no name.
UNKNOWN_LABEL = "(no channel)"

_WORD = re.compile(r"[^a-z0-9]+")


def _normalise(name: str) -> str:
    """Return a lowercase name with separators removed."""
    return _WORD.sub("", name.lower())


# The default channel name of each LoRa modem preset.
#
# The names come from `sonoran.radio.presets`, which is the one preset
# table. This module held its own copy of the nine names until the
# coverage work needed the bandwidth and the sensitivity beside them.
# Two lists of the same nine names would drift.
PRESETS: dict[str, str] = {_normalise(preset.name): preset.name for preset in _PRESET_TABLE}

# Groups decided by the exact channel name, tested before the word match.
#
# A near-miss spelling deliberately falls through to Custom instead of
# joining its group. That is not pedantry: a lowercase `trivia` sitting
# in Custom beside the real `Trivia` is how the operators discovered
# somebody had typed the name wrong and quietly created a second channel
# that nobody else was on. Filing the typo next to the original would
# have hidden exactly the thing worth seeing.
EXACT_GROUPS: dict[str, str] = {
    "Trivia": "Games",
}

# Topic groups matched by a word anywhere in the channel name, ignoring
# case and separators. These are subjects a channel can be about however
# its operator spelled it.
TOPICS: dict[str, tuple[str, ...]] = {
    "Weather": ("weather", "wx"),
    "Traffic": ("traffic", "roads"),
    "Emergency": ("emergency", "emcomm", "ares", "races"),
    "Telemetry": ("telemetry", "sensor"),
}

PRESET_GROUP = "Presets"
CUSTOM_GROUP = "Custom"

# The group for a channel this deployment claims as its own but which
# matches no topic.
#
# `core_channels` names them. They are the channels the operators run
# themselves, so they are where local experiments land, and they belong
# above Custom rather than mixed into it.
#
# A core channel that DOES match a topic keeps that topic: the tier says
# whether a channel is part of this mesh, the group says what it is
# about, and the two are not the same question.
OWN_GROUP = "Testing"

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
    exact = EXACT_GROUPS.get(channel)
    if exact is not None:
        return {
            "channel": channel,
            "label": channel,
            "group": exact,
            "preset": "",
            "tier": tier,
        }
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
        "group": OWN_GROUP if tier == CORE_TIER else CUSTOM_GROUP,
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
    # Custom sorts last on purpose. It is where a channel nobody has
    # classified yet arrives, so it reads as the inbox at the foot of the
    # page: a new name showing up there is the signal to file it above.
    order = [
        PRESET_GROUP,
        "Weather",
        "Games",
        "Traffic",
        "Emergency",
        "Telemetry",
        OWN_GROUP,
    ]
    if group == CUSTOM_GROUP:
        return len(order) + 1
    return order.index(group) if group in order else len(order)
