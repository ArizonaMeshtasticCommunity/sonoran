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

    `sensitivity_dbm` is the threshold the planner and the coverage map
    draw against. **Its source is in doubt (#362):** the table below was
    labelled "SX1262 data sheet", but every figure is 14 dBm minus the
    link budget the Meshtastic docs publish, and those budgets assume a
    22 dBm transmitter, so the figures read about 8 dB better than the
    docs support. Do not add a figure here until #362 settles the source.

    A preset firmware has and this table does not model has
    `sensitivity_dbm` None. It is recognised by name, so traffic on it
    is tagged with the right preset, and every reader that needs a
    sensitivity skips it through `modelled` instead of guessing one.
    """

    key: str
    name: str
    label: str
    spreading_factor: int
    bandwidth_hz: int
    sensitivity_dbm: float | None


# The nine presets this table models, with a sensitivity each.
#
# The order is from the shortest range to the longest. It is the order
# the pickers show. The sensitivities are in doubt: see `ModemPreset`
# and #362 before you use one as a fact or add one.
PRESETS: tuple[ModemPreset, ...] = (
    ModemPreset("SHORT_TURBO", "ShortTurbo", "Short turbo", 7, 500_000, -126.0),
    ModemPreset("SHORT_FAST", "ShortFast", "Short fast", 7, 250_000, -129.0),
    ModemPreset("SHORT_SLOW", "ShortSlow", "Short slow", 8, 250_000, -131.5),
    ModemPreset("MEDIUM_FAST", "MediumFast", "Medium fast", 9, 250_000, -134.0),
    ModemPreset("MEDIUM_SLOW", "MediumSlow", "Medium slow", 10, 250_000, -136.5),
    ModemPreset("LONG_FAST", "LongFast", "Long fast", 11, 250_000, -139.0),
    # Firmware names this channel "LongMod", not "LongModerate"
    # (`DisplayFormatters::getModemPresetDisplayName`, firmware v2.8.1).
    # The old spelling stays readable, see `ALIASES`.
    ModemPreset("LONG_MODERATE", "LongMod", "Long moderate", 11, 125_000, -142.0),
    ModemPreset("LONG_SLOW", "LongSlow", "Long slow", 12, 125_000, -144.5),
    ModemPreset("VERY_LONG_SLOW", "VeryLongSlow", "Very long slow", 12, 62_500, -147.5),
)

# The presets firmware has that this table does not model yet (#362).
#
# Spreading factor and bandwidth are firmware's own, from
# `modemPresetToParams` in `src/mesh/MeshRadio.h`, and the channel names
# from `DisplayFormatters::getModemPresetDisplayName` in
# `src/DisplayFormatters.cpp`, both at firmware v2.8.1.8e6a88d. The
# figures are for a region without wide LoRa. LONG_TURBO is the US
# default for a new node from firmware 2.8.
#
# No sensitivity: see the note on `ModemPreset`. These are not offered
# by the planner or drawn by the coverage map until #362 gives them one.
RECOGNISED_ONLY: tuple[ModemPreset, ...] = (
    ModemPreset("MEDIUM_TURBO", "MediumTurbo", "Medium turbo", 9, 500_000, None),
    ModemPreset("LONG_TURBO", "LongTurbo", "Long turbo", 11, 500_000, None),
    ModemPreset("LITE_FAST", "LiteFast", "Lite fast", 9, 125_000, None),
    ModemPreset("LITE_SLOW", "LiteSlow", "Lite slow", 10, 125_000, None),
    ModemPreset("NARROW_FAST", "NarrowFast", "Narrow fast", 7, 62_500, None),
    ModemPreset("NARROW_SLOW", "NarrowSlow", "Narrow slow", 8, 62_500, None),
    ModemPreset("TINY_FAST", "TinyFast", "Tiny fast", 7, 15_600, None),
    ModemPreset("TINY_SLOW", "TinySlow", "Tiny slow", 8, 15_600, None),
)

# Every preset a channel name or a key can name: the modelled ones and
# the recognised ones. `PRESETS` alone is what a picker offers.
KNOWN: tuple[ModemPreset, ...] = PRESETS + RECOGNISED_ONLY

# Older spellings of a channel name, to the preset they mean. Sonoran
# called LONG_MODERATE "LongModerate" before it followed firmware, and a
# link or a stored tag may still say so.
ALIASES = {"LongModerate": "LONG_MODERATE"}

_BY_KEY = {preset.key: preset for preset in KNOWN}

_WORD = re.compile(r"[^a-z0-9]+")


def _normalise(name: str) -> str:
    """Return a lowercase name with the separators removed."""
    return _WORD.sub("", name.lower())


_BY_NAME = {_normalise(preset.name): preset for preset in KNOWN} | {
    _normalise(alias): _BY_KEY[key] for alias, key in ALIASES.items()
}


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


def modelled(preset: ModemPreset | None) -> ModemPreset | None:
    """Return the preset when this table models its sensitivity, else None.

    Every reader that draws or measures against a sensitivity goes
    through this, so a preset firmware has and the table does not model
    is left out by name, never given a threshold of zero.
    """
    return preset if preset is not None and preset.sensitivity_dbm is not None else None


def sensitivity_of(preset: ModemPreset) -> float:
    """Return the modelled sensitivity of a preset, in dBm.

    For a preset that came through `modelled`. A preset with none is a
    caller that skipped that check, and it is refused here rather than
    drawn against a number nobody chose.
    """
    if preset.sensitivity_dbm is None:
        raise ValueError(f"{preset.key} has no modelled sensitivity (#362)")
    return preset.sensitivity_dbm


def noise_floor_dbm(preset: ModemPreset, noise_figure_db: float = DEFAULT_NOISE_FIGURE_DB) -> float:
    """Return the noise floor of a receiver on this preset, in dBm.

    The floor is the thermal noise in the bandwidth of the preset, plus
    the noise the receiver adds itself.

    A reported SNR is a ratio against this floor. Adding the floor to an
    SNR gives the power that arrived at the radio, which is what a
    propagation model predicts.
    """
    return THERMAL_NOISE_DBM_PER_HZ + 10.0 * math.log10(preset.bandwidth_hz) + noise_figure_db


def required_snr_db(preset: ModemPreset, noise_figure_db: float = DEFAULT_NOISE_FIGURE_DB) -> float:
    """Return the SNR this preset needs to demodulate, in dB.

    The figure is negative. LoRa reads a signal below the noise, which
    is the whole point of a spreading factor, so a reported SNR of
    -20 dB on Long fast is a working link and not a broken one. Long
    fast needs about -25 dB.

    Use it to turn a reported SNR into a margin:

        margin_db = snr_db - required_snr_db(preset)

    The margin is what says whether a link has room to spare. A raw SNR
    does not, because the same number means different things on two
    presets. It is derived from the one preset table, so it cannot
    disagree with the sensitivity the coverage map is drawn against.
    """
    return sensitivity_of(preset) - noise_floor_dbm(preset, noise_figure_db)


def received_dbm_from_snr(
    snr_db: float, preset: ModemPreset, noise_figure_db: float = DEFAULT_NOISE_FIGURE_DB
) -> float:
    """Return the power that arrived at the radio, in dBm.

    Use this for a reported SNR. Prefer a reported RSSI where there is
    one, because it is measured and this is derived.
    """
    return noise_floor_dbm(preset, noise_figure_db) + snr_db
