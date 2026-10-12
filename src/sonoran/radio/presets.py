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
    draw against. It is the transmit power the Meshtastic docs assume,
    22 dBm, minus the link budget they publish for the preset. See
    `PRESETS`. It is the best a radio can do: where the band is shared
    and noisy, a real radio does several dB worse.

    A preset with no published link budget has `sensitivity_dbm` None.
    It is recognised by name, so traffic on it is tagged with the right
    preset, and every reader that needs a sensitivity skips it through
    `modelled` instead of guessing one.
    """

    key: str
    name: str
    label: str
    spreading_factor: int
    bandwidth_hz: int
    sensitivity_dbm: float | None


# The transmit power the Meshtastic docs assume for every link budget
# in their preset table, in dBm, with a 0 dB antenna.
DOCS_TX_POWER_DBM = 22.0

# The presets with a published link budget, shortest range first. It is
# the order the pickers show.
#
# Source: the preset table of https://meshtastic.org/docs/overview/radio-settings/
# (read 2026-10-12). It says its link budgets come from "the official
# Semtech LoRa calculator" and "assume a transmit power of 22 dBm and an
# antenna with 0 dB gain". So each sensitivity is 22 dBm minus that
# budget, and each line names the budget it came from.
#
# Spreading factor and bandwidth agree with firmware's own
# `modemPresetToParams` (`src/mesh/MeshRadio.h`), and each name is the
# channel name from `DisplayFormatters::getModemPresetDisplayName`, both
# at firmware v2.8.1.8e6a88d. The bandwidths are for a region without
# wide LoRa.
#
# Before #362 this table read 8 dB better: it was 14 dBm minus the same
# budgets and was labelled "SX1262 data sheet". Every coverage map and
# margin drawn before #362 assumed that much more range.
PRESETS: tuple[ModemPreset, ...] = (
    ModemPreset("SHORT_TURBO", "ShortTurbo", "Short turbo", 7, 500_000, 22 - 140.0),
    ModemPreset("SHORT_FAST", "ShortFast", "Short fast", 7, 250_000, 22 - 143.0),
    ModemPreset("MEDIUM_TURBO", "MediumTurbo", "Medium turbo", 9, 500_000, 22 - 145.0),
    ModemPreset("SHORT_SLOW", "ShortSlow", "Short slow", 8, 250_000, 22 - 145.5),
    ModemPreset("MEDIUM_FAST", "MediumFast", "Medium fast", 9, 250_000, 22 - 148.0),
    ModemPreset("NARROW_FAST", "NarrowFast", "Narrow fast", 7, 62_500, 22 - 149.0),
    ModemPreset("LONG_TURBO", "LongTurbo", "Long turbo", 11, 500_000, 22 - 150.0),
    ModemPreset("MEDIUM_SLOW", "MediumSlow", "Medium slow", 10, 250_000, 22 - 150.5),
    ModemPreset("LITE_FAST", "LiteFast", "Lite fast", 9, 125_000, 22 - 151.0),
    ModemPreset("NARROW_SLOW", "NarrowSlow", "Narrow slow", 8, 62_500, 22 - 151.5),
    ModemPreset("LONG_FAST", "LongFast", "Long fast", 11, 250_000, 22 - 153.0),
    ModemPreset("LITE_SLOW", "LiteSlow", "Lite slow", 10, 125_000, 22 - 153.5),
    ModemPreset("TINY_FAST", "TinyFast", "Tiny fast", 7, 15_600, 22 - 155.0),
    # Firmware names this channel "LongMod", not "LongModerate". The old
    # spelling stays readable, see `ALIASES`.
    ModemPreset("LONG_MODERATE", "LongMod", "Long moderate", 11, 125_000, 22 - 156.0),
    ModemPreset("TINY_SLOW", "TinySlow", "Tiny slow", 8, 15_600, 22 - 157.5),
)

# Presets that older firmware still runs and the docs table no longer
# lists. Their traffic is recognised and tagged. They have no published
# link budget, so the planner and the coverage map do not draw them.
# Very long slow is gone from firmware 2.8.1 (it falls back to Long fast
# settings); Long slow is still in firmware. Remove them when no node on
# this mesh runs them any more.
RECOGNISED_ONLY: tuple[ModemPreset, ...] = (
    ModemPreset("LONG_SLOW", "LongSlow", "Long slow", 12, 125_000, None),
    ModemPreset("VERY_LONG_SLOW", "VeryLongSlow", "Very long slow", 12, 62_500, None),
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
        raise ValueError(f"{preset.key} has no published link budget to model")
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
