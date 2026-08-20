"""Radio characteristics of the nodes on the mesh.

The mesh reports what a node is. It does not report how the node is
built. A node tells us its hardware model, and nothing about its
antenna, its mast, or the power it transmits with.

This package holds the three answers to that gap:

- `presets` is the modem preset table. A preset sets the sensitivity of
  every receiver on it.
- `hardware` maps a hardware model to the radio inside it.
- `overrides` reads the facts an operator knows and the mesh cannot
  report.

`resolve` puts the three together. It is the only place that decides
the radio characteristics of a node.

This package has the same rule as `decode` and `crypto`. It must never
touch the database.
"""

from sonoran.radio.hardware import HardwareProfile, hardware_profile
from sonoran.radio.overrides import NodeOverride, Overrides, load_overrides
from sonoran.radio.presets import (
    DEFAULT_NOISE_FIGURE_DB,
    PRESETS,
    ModemPreset,
    noise_floor_dbm,
    preset_by_key,
    preset_for_channel,
)
from sonoran.radio.resolve import RadioProfile, Source, resolve_profile

__all__ = [
    "DEFAULT_NOISE_FIGURE_DB",
    "PRESETS",
    "HardwareProfile",
    "ModemPreset",
    "NodeOverride",
    "Overrides",
    "RadioProfile",
    "Source",
    "hardware_profile",
    "load_overrides",
    "noise_floor_dbm",
    "preset_by_key",
    "preset_for_channel",
    "resolve_profile",
]
