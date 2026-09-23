"""Coax loss at the mesh's own frequency, from the makers' datasheets (#112).

The planner has one "Cable loss (dB)" box. A newcomer has no way to know
what to put in it, and the difference between a guess and the truth is
large: **30 ft of LMR-195 throws away 3.3 dB and the same run in LMR-400
loses 1.2 dB** -- better than half the power, decided by which cable is
on the roof.

Every figure here was read off the manufacturer's datasheet, and the
datasheet link and the date are recorded per cable. That mattered more
than usual: a web search for these numbers returned "LMR-195: ~3.5 dB
per 100 ft" and "LMR-240: ~2.2", against datasheet values of **11.1**
and **7.6**. Both summaries were wrong by about three times, in the
direction that makes a link look workable when it is not. #112 asked for
datasheets and not forum posts for exactly this reason.

Loss is computed, not looked up. Times Microwave prints a formula beside
each table,

    attenuation (dB per 100 ft) = k * sqrt(f_MHz) + m * f_MHz

which is what lets the planner ask at its own frequency rather than
assuming 915. The coefficients are theirs, and each one is checked
against its own printed table in `test_cable_loss.py`: they agree to
within 0.05 dB/100 ft from 30 MHz to 2500 MHz.

**Not included:** RG-58, RG-8X, RG-174, RG-316 and the U.FL pigtails
that #112 also lists. Those are generic designations rather than one
maker's product, their loss varies by who made the spool, and no single
datasheet covers them. Adding them means picking a manufacturer's part
and citing it, the same way as these. They are absent rather than
guessed.

Connector and adapter loss is also absent. #112 suggests 0.1-0.5 dB per
adapter and asks whether that is realistic; it is a plausible range and
not a sourced figure, so it is not a number in this file yet.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# The planner works in metres; datasheets in this band are in feet.
FEET_PER_METRE = 3.280839895


@dataclass(frozen=True)
class Cable:
    """One coaxial cable, as its maker's datasheet describes it."""

    key: str
    name: str
    maker: str
    # Times Microwave's own coefficients: dB/100ft = k*sqrt(f) + m*f.
    k: float
    m: float
    # The datasheet's printed value at 900 MHz, kept so the formula can
    # be checked against the table it came from rather than trusted.
    printed_900_db_per_100ft: float
    outer_diameter_in: float
    good_for: str
    url: str
    checked: str


CABLES: tuple[Cable, ...] = (
    Cable(
        key="lmr-195",
        name="LMR-195",
        maker="Times Microwave",
        k=0.0,  # replaced below; see LMR195_NOTE
        m=0.0,
        printed_900_db_per_100ft=11.1,
        outer_diameter_in=0.195,
        good_for="Short jumpers inside a box. Thin and easy to route, and costly over distance.",
        url="https://powerfulsignal.com/content/lmr-195-spec-sheet.pdf",
        checked="2026-09-23",
    ),
    Cable(
        key="lmr-240",
        name="LMR-240",
        maker="Times Microwave",
        k=0.242080,
        m=0.000330,
        printed_900_db_per_100ft=7.6,
        outer_diameter_in=0.240,
        good_for="A short mast run where LMR-400 is too stiff to bend.",
        url="https://www.talleycom.com/images/pdf/TIMLMR-240.pdf",
        checked="2026-09-23",
    ),
    Cable(
        key="lmr-400",
        name="LMR-400",
        maker="Times Microwave",
        k=0.12229,
        m=0.00026,
        printed_900_db_per_100ft=3.9,
        outer_diameter_in=0.405,
        good_for="A roof or tower run. Thick and stiff, and the least lossy of these by far.",
        url="https://www.gpsnetworking.com/system/datasheets/132/original/LMR400A.pdf",
        checked="2026-09-23",
    ),
)

# The LMR-195 datasheet page carries the attenuation TABLE but not the
# formula the other two print. Its coefficients are therefore not
# recorded, and `loss_db` falls back to the printed 900 MHz figure for
# it rather than inventing coefficients that would look identical to the
# sourced ones.
LMR195_NOTE = "table only; no printed formula on the datasheet page read"

BY_KEY: dict[str, Cable] = {cable.key: cable for cable in CABLES}


def db_per_100ft(cable: Cable, frequency_mhz: float) -> float:
    """Attenuation at a frequency, in dB per 100 ft.

    Uses the maker's formula where the datasheet printed one. Where it
    did not, the printed 900 MHz figure is returned unchanged at every
    frequency -- deliberately flat, because a made-up curve through one
    point would be indistinguishable from a sourced one.
    """
    if cable.k == 0.0 and cable.m == 0.0:
        return cable.printed_900_db_per_100ft
    return cable.k * math.sqrt(frequency_mhz) + cable.m * frequency_mhz


def loss_db(cable: Cable, metres: float, frequency_mhz: float) -> float:
    """The loss of a run of this cable, in dB."""
    if metres <= 0:
        return 0.0
    return db_per_100ft(cable, frequency_mhz) * (metres * FEET_PER_METRE) / 100.0
