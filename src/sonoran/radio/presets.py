"""The LoRa modem presets.

A preset is a radio configuration. It is not only a sensitivity figure.
A node on Long fast cannot hear a node on Medium fast at all. Every
prediction and every measurement must name the preset it belongs to.
See `AGENTS.md` 9.7.

This module is the source of truth for the preset table. The planner
form in `web/static/planner-params.js` holds the same figures, because
that page runs in the browser and reads no Python. A test keeps the two
tables the same.
"""

import math
import re
from dataclasses import dataclass

# The noise figure of the receiver, in dB.
#
# The SX1262 data sheet does not give one figure. Measurements of the
# part put it near 6 dB. The number is used to turn a reported SNR into
# a received power, so it moves every calibration result by the same
# amount. Change it in one place only.
DEFAULT_NOISE_FIGURE_DB = 6.0

# Thermal noise in one hertz at room temperature, in dBm.
THERMAL_NOISE_DBM_PER_HZ = -174.0


@dataclass(frozen=True)
class ModemPreset:
    """One LoRa modem preset.

    `name` is the channel name the firmware uses by default. It is the
    value stored in `neighbor_metrics.channel` and in `node.last_channel`.

    `sensitivity_dbm` is the figure from the SX1262 data sheet. It is
    the best a radio can do. Where the band is shared and noisy, a real
    radio does several dB worse.
    """

    key: str
    name: str
    label: str
    spreading_factor: int
    bandwidth_hz: int
    sensitivity_dbm: float


# The nine presets, from the SX1262 data sheet.
#
# The order is from the shortest range to the longest. It is the order
# the pickers show.
PRESETS: tuple[ModemPreset, ...] = (
    ModemPreset("SHORT_TURBO", "ShortTurbo", "Short turbo", 7, 500_000, -126.0),
    ModemPreset("SHORT_FAST", "ShortFast", "Short fast", 7, 250_000, -129.0),
    ModemPreset("SHORT_SLOW", "ShortSlow", "Short slow", 8, 250_000, -131.5),
    ModemPreset("MEDIUM_FAST", "MediumFast", "Medium fast", 9, 250_000, -134.0),
    ModemPreset("MEDIUM_SLOW", "MediumSlow", "Medium slow", 10, 250_000, -136.5),
    ModemPreset("LONG_FAST", "LongFast", "Long fast", 11, 250_000, -139.0),
    ModemPreset("LONG_MODERATE", "LongModerate", "Long moderate", 11, 125_000, -142.0),
    ModemPreset("LONG_SLOW", "LongSlow", "Long slow", 12, 125_000, -144.5),
    ModemPreset("VERY_LONG_SLOW", "VeryLongSlow", "Very long slow", 12, 62_500, -147.5),
)

# The preset this mesh runs on when nothing says otherwise.
DEFAULT_PRESET_KEY = "LONG_FAST"

_BY_KEY = {preset.key: preset for preset in PRESETS}

_WORD = re.compile(r"[^a-z0-9]+")


def _normalise(name: str) -> str:
    """Return a lowercase name with the separators removed."""
    return _WORD.sub("", name.lower())


_BY_NAME = {_normalise(preset.name): preset for preset in PRESETS}


def preset_by_key(key: str) -> ModemPreset | None:
    """Return the preset with this key, or None."""
    return _BY_KEY.get(key)


def preset_for_channel(channel: str | None) -> ModemPreset | None:
    """Return the preset a channel name names, or None.

    A channel that is not a default preset name returns None. Such a
    channel rides on top of a preset and does not name one. Weather and
    PKI are the examples this mesh has.
    """
    if not channel:
        return None
    return _BY_NAME.get(_normalise(channel))


def noise_floor_dbm(preset: ModemPreset, noise_figure_db: float = DEFAULT_NOISE_FIGURE_DB) -> float:
    """Return the noise floor of a receiver on this preset, in dBm.

    The floor is the thermal noise in the bandwidth of the preset, plus
    the noise the receiver adds itself.

    A reported SNR is a ratio against this floor. Adding the floor to an
    SNR gives the power that arrived at the radio, which is what a
    propagation model predicts.
    """
    return THERMAL_NOISE_DBM_PER_HZ + 10.0 * math.log10(preset.bandwidth_hz) + noise_figure_db


def received_dbm_from_snr(
    snr_db: float, preset: ModemPreset, noise_figure_db: float = DEFAULT_NOISE_FIGURE_DB
) -> float:
    """Return the power that arrived at the radio, in dBm.

    Use this for a reported SNR. Prefer a reported RSSI where there is
    one, because it is measured and this is derived.
    """
    return noise_floor_dbm(preset, noise_figure_db) + snr_db
