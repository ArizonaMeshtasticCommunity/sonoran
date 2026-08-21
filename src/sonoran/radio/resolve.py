"""The radio characteristics of one node.

This module is the only place that decides what radio a node has. The
coverage job, the calibration job, and the API all read it, so they
cannot disagree about the power a node transmits with.

It is the same arrangement as `sonoran/positions.py`, which holds the
one test for a usable position, and `sonoran/api/traces.py`, which holds
the one reading of a traceroute row.

Three sources are put together, weakest first:

1. The hardware model, which gives a first guess.
2. The overrides file, which gives what an operator knows.
3. The calibration job, which gives what the mesh measured.

Every value carries the name of the source it came from. A page that
shows a number can then say where the number came from, and a reader
can tell a measurement from a guess.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from sonoran.radio.hardware import hardware_profile
from sonoran.radio.overrides import EMPTY, NodeOverride, Overrides

# The height of an antenna above the ground, in metres, when nobody
# says otherwise.
#
# This is the largest unknown in the whole prediction. Three metres
# describes a node on a roof edge or a short pole, which is the common
# case. A node on a tower is many times higher and reaches many times
# further, so a tower must be named in the overrides file.
DEFAULT_ANTENNA_HEIGHT_M = 3.0

# The loss between the radio and the antenna, in dB, when nobody says
# otherwise.
#
# A stock device has its antenna screwed straight on, so the loss is
# near zero. A site with a cable run has several dB. Inventing a loss
# that is not there would understate every stock node, so the default is
# zero and a real cable must be named in the overrides file. The
# calibration job takes up whatever loss is left unnamed.
DEFAULT_CABLE_LOSS_DB = 0.0

# The largest correction the calibration job may apply, in dB.
#
# A fit outside this range is not a wrong antenna. It is a wrong
# position, a wrong preset, or a fault. Clamping keeps one bad node from
# drawing coverage that reaches the next state.
MAX_CALIBRATION_DB = 15.0


class Source(StrEnum):
    """Where one value came from."""

    # A figure this module holds, used because nothing better exists.
    DEFAULT = "default"
    # A figure that follows from the hardware model.
    HARDWARE = "hardware"
    # A figure an operator wrote in the overrides file.
    OVERRIDE = "override"
    # A figure the calibration job measured.
    CALIBRATED = "calibrated"


@dataclass(frozen=True)
class RadioProfile:
    """Everything a prediction needs to know about one node.

    `sources` names where each value came from. Its keys are the field
    names of this class.
    """

    node_id: str
    tx_power_dbm: float
    antenna_gain_dbi: float
    antenna_height_m: float
    cable_loss_db: float
    above_clutter: bool
    calibration_offset_db: float
    locked: bool
    chipset: str
    hardware_inferred: bool
    sources: Mapping[str, str]

    @property
    def eirp_dbm(self) -> float:
        """Return the power leaving the antenna, in dBm.

        This is the nameplate figure. It does not hold the calibration
        correction. Use `effective_eirp_dbm` to predict with.
        """
        return self.tx_power_dbm + self.antenna_gain_dbi - self.cable_loss_db

    @property
    def effective_eirp_dbm(self) -> float:
        """Return the power the mesh behaves as if the node transmits.

        This is the figure to predict with. It is the nameplate power
        plus what the measurements say the nameplate got wrong.
        """
        return self.eirp_dbm + self.calibration_offset_db

    @property
    def is_measured(self) -> bool:
        """Return true when measurements moved this profile."""
        return self.calibration_offset_db != 0.0


def clamp_calibration(offset_db: float) -> float:
    """Return a calibration offset held inside the allowed range."""
    return max(-MAX_CALIBRATION_DB, min(MAX_CALIBRATION_DB, offset_db))


def resolve_profile(
    node_id: str,
    hw_model: str | None,
    overrides: Overrides = EMPTY,
    calibration_offset_db: float | None = None,
) -> RadioProfile:
    """Return the radio profile of one node.

    `calibration_offset_db` is what the calibration job measured. Pass
    None when there is no fit yet. A node the overrides file locks keeps
    its nameplate figures whatever the fit says.
    """
    hardware = hardware_profile(hw_model)
    override = overrides.for_node(node_id)
    sources: dict[str, str] = {}

    tx_power = _pick(
        sources,
        "tx_power_dbm",
        override.tx_power_dbm,
        hardware.assumed_tx_power_dbm,
        Source.HARDWARE if not hardware.inferred else Source.DEFAULT,
    )
    gain = _pick(
        sources,
        "antenna_gain_dbi",
        override.antenna_gain_dbi,
        hardware.assumed_antenna_gain_dbi,
        Source.HARDWARE if not hardware.inferred else Source.DEFAULT,
    )
    height = _pick(
        sources,
        "antenna_height_m",
        override.antenna_height_m,
        DEFAULT_ANTENNA_HEIGHT_M,
        Source.DEFAULT,
    )
    cable = _pick(
        sources,
        "cable_loss_db",
        override.cable_loss_db,
        DEFAULT_CABLE_LOSS_DB,
        Source.DEFAULT,
    )
    above_clutter = _pick(
        sources,
        "above_clutter",
        override.above_clutter,
        False,
        Source.DEFAULT,
    )

    offset, offset_source = _calibration(override, calibration_offset_db)
    sources["calibration_offset_db"] = offset_source

    return RadioProfile(
        node_id=node_id,
        tx_power_dbm=tx_power,
        antenna_gain_dbi=gain,
        antenna_height_m=height,
        cable_loss_db=cable,
        above_clutter=above_clutter,
        calibration_offset_db=offset,
        locked=override.lock_calibration,
        chipset=hardware.chipset,
        hardware_inferred=hardware.inferred,
        sources=sources,
    )


def _calibration(override: NodeOverride, offset_db: float | None) -> tuple[float, str]:
    """Return the calibration offset to use, and where it came from."""
    if override.lock_calibration or offset_db is None:
        return 0.0, Source.DEFAULT
    return clamp_calibration(offset_db), Source.CALIBRATED


def _pick[T](
    sources: dict[str, str],
    name: str,
    override: T | None,
    fallback: T,
    fallback_source: Source,
) -> T:
    """Return the override where there is one, and record the source."""
    if override is not None:
        sources[name] = Source.OVERRIDE
        return override
    sources[name] = fallback_source
    return fallback
