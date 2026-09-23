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

RG-58 and RG-8X are here as **one manufacturer's part each** -- Belden
8259 and 9258 -- because "RG-58" alone is a MIL designation that many
firms make to varying quality, and a figure for "RG-58" with no part
number behind it is not a sourced figure. Their datasheets print a table
and no formula, so those two are interpolated between the printed
points, which is what #112 asks for.

The numbers are worth seeing beside the LMR ones. At 900 MHz, Belden's
RG-58 loses **21.1 dB/100ft** against LMR-400's 3.9 -- more than five
times as much. A 30 ft run throws away 76% of the power in RG-58 and
24% in LMR-400.

**U.FL pigtails are deliberately absent, and this is why.** Hirose's
published attenuation for the 1.13 mm cable starts at **3 GHz**
(6.5 dB/m, then 9.5 at 6 GHz and 11.7 at 8 GHz). There is no published
figure anywhere near 915 MHz. Scaling the 3 GHz value down by the usual
square-root-of-frequency rule gives about 3.6 dB/m, and that number
would be a model rather than a measurement -- the square-root rule
under-reads on thin lossy cable, where the dielectric term is linear in
frequency. So it is not in the table.

What is worth knowing about them is a length argument rather than a
figure: a U.FL pigtail is a few centimetres, so even at several dB per
metre it costs a fraction of a dB. The cable on the mast is the one
that decides a link, not the one inside the box.

**Connector and adapter loss lives in `adapters.py`**, with its own
datasheets. This file said for a while that the figures were not
sourceable -- that every number found was a generalisation and the
reachable datasheets refused automated fetches or quoted VSWR with no
insertion loss. That was true of the pages I had tried and false as a
statement about the world: Mini-Circuits publishes both, per part.

The answer to #112's "is 0.1-0.5 dB per adapter realistic": **0.1 dB is
the published typical across DC-18 GHz**, so at 915 MHz it is a ceiling
rather than an estimate, and 0.5 dB is five times a good adapter's
whole-band typical. The mismatch note that used to be here -- that on
cheap adapters the reflection loss dominates the insertion loss -- is
right for a poor part and wrong for a good one, and `adapters.py`
carries the arithmetic that says where the line falls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import pairwise

# The planner works in metres; datasheets in this band are in feet.
FEET_PER_METRE = 3.280839895


@dataclass(frozen=True)
class Cable:
    """One coaxial cable, as its maker's datasheet describes it."""

    key: str
    name: str
    maker: str
    # The product LINE, not the vendor. Diameter predicts loss inside
    # one of these and nowhere else -- see `test_cable_loss.py`.
    family: str
    # Times Microwave's own coefficients: dB/100ft = k*sqrt(f) + m*f.
    # Both zero where the datasheet printed no formula; `table` is then
    # the source and is interpolated.
    k: float
    m: float
    # The datasheet's printed value at 900 MHz, kept so the formula can
    # be checked against the table it came from rather than trusted.
    printed_900_db_per_100ft: float
    outer_diameter_in: float
    good_for: str
    url: str
    checked: str
    # Anything about the figure a buyer should know. Empty when there is
    # nothing to say.
    caveat: str = ""
    # The datasheet's printed attenuation table, MHz -> dB/100ft. Empty
    # where a printed formula is the source instead.
    table: tuple[tuple[float, float], ...] = ()


CABLES: tuple[Cable, ...] = (
    Cable(
        key="belden-8216-rg174",
        family="RG-174",
        name="RG-174 (Belden 8216)",
        maker="Belden",
        k=0.0,
        m=0.0,
        printed_900_db_per_100ft=31.0,
        outer_diameter_in=0.110,
        good_for=(
            "A pigtail of a few inches inside an enclosure. Over any real "
            "distance it is the worst choice here."
        ),
        url="https://catalog.belden.com/techdata/EN/8216_techdata.pdf",
        checked="2026-09-23",
        caveat="Belden 8216 specifically. 31 dB/100ft at 900 MHz -- eight times LMR-400.",
        table=(
            (1, 1.9),
            (10, 3.3),
            (50, 5.8),
            (100, 8.4),
            (200, 12.5),
            (400, 19.0),
            (700, 27.0),
            (900, 31.0),
            (1000, 34.0),
        ),
    ),
    Cable(
        key="belden-84316-rg316",
        family="RG-316",
        name="RG-316 (Belden 84316)",
        maker="Belden",
        k=0.0,
        m=0.0,
        printed_900_db_per_100ft=27.3,
        outer_diameter_in=0.098,
        good_for=(
            "A short pigtail that has to take heat or tight bends. PTFE, so "
            "it survives more than RG-174 does."
        ),
        url="https://catalog.belden.com/techdata/EN/84316_techdata.pdf",
        checked="2026-09-23",
        caveat=(
            "Thinner than RG-174 and yet less lossy: PTFE and silvered "
            "copper beat polyethylene and copper-covered steel."
        ),
        table=(
            (1, 1.2),
            (10, 2.7),
            (50, 5.6),
            (100, 8.3),
            (200, 12.0),
            (400, 17.5),
            (700, 23.7),
            (900, 27.3),
            (1000, 29.0),
            (1500, 36.5),
        ),
    ),
    Cable(
        key="lmr-195",
        family="LMR",
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
        key="belden-8259-rg58",
        family="RG-58",
        name="RG-58 (Belden 8259)",
        maker="Belden",
        k=0.0,
        m=0.0,
        table=(
            (1, 0.4),
            (10, 1.5),
            (50, 3.7),
            (100, 5.4),
            (200, 8.1),
            (400, 12.4),
            (700, 17.7),
            (900, 21.1),
            (1000, 22.8),
        ),
        printed_900_db_per_100ft=21.1,
        outer_diameter_in=0.193,
        good_for=(
            "Patch leads of a foot or two. Cheap and everywhere, and the "
            "lossiest thing here by a wide margin at this frequency."
        ),
        url="https://catalog.belden.com/techdata/EN/8259_techdata.pdf",
        checked="2026-09-23",
        caveat=(
            '"RG-58" is a MIL designation many firms make to varying '
            "quality. These figures are Belden 8259 specifically; another "
            "maker's RG-58 may be worse."
        ),
    ),
    Cable(
        key="belden-9258-rg8x",
        family="RG-8X",
        name="RG-8X (Belden 9258)",
        maker="Belden",
        k=0.0,
        m=0.0,
        table=(
            (1, 0.3),
            (10, 0.9),
            (50, 2.1),
            (100, 3.1),
            (200, 4.5),
            (400, 6.6),
            (700, 9.1),
            (900, 10.7),
            (1000, 11.2),
        ),
        printed_900_db_per_100ft=10.7,
        outer_diameter_in=0.242,
        good_for="A short indoor run where LMR is hard to get hold of.",
        url="https://catalog.belden.com/techdata/EN/9258_techdata.pdf",
        checked="2026-09-23",
        caveat=(
            "Belden 9258 specifically. Note it loses more than LMR-240 "
            "despite being slightly thicker: foam dielectric and bonded "
            "foil beat braid at the same diameter."
        ),
    ),
    Cable(
        key="lmr-240",
        family="LMR",
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
        family="LMR",
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


def _from_table(table: tuple[tuple[float, float], ...], frequency_mhz: float) -> float:
    """Interpolate a printed attenuation table.

    Coax attenuation rises roughly with the square root of frequency, so
    the interpolation is linear in sqrt(f) rather than in f. Across the
    tight spacing these tables use near 900 MHz the difference is small,
    but it is the right curve and it costs nothing.

    Outside the table the nearest printed value is returned rather than
    an extrapolation. A datasheet says nothing about frequencies it does
    not list, and inventing a number there would look exactly like a
    sourced one.
    """
    points = sorted(table)
    if frequency_mhz <= points[0][0]:
        return points[0][1]
    if frequency_mhz >= points[-1][0]:
        return points[-1][1]
    for (low_f, low_db), (high_f, high_db) in pairwise(points):
        if low_f <= frequency_mhz <= high_f:
            span = math.sqrt(high_f) - math.sqrt(low_f)
            along = (math.sqrt(frequency_mhz) - math.sqrt(low_f)) / span
            return low_db + along * (high_db - low_db)
    return points[-1][1]


def db_per_100ft(cable: Cable, frequency_mhz: float) -> float:
    """Attenuation at a frequency, in dB per 100 ft.

    Uses the maker's formula where the datasheet printed one, the
    maker's table where it printed a table, and the single printed
    900 MHz figure flat where it gave neither -- because a curve fitted
    through one point would be indistinguishable from a sourced one.
    """
    if cable.k or cable.m:
        return cable.k * math.sqrt(frequency_mhz) + cable.m * frequency_mhz
    if cable.table:
        return _from_table(cable.table, frequency_mhz)
    return cable.printed_900_db_per_100ft


def loss_db(cable: Cable, metres: float, frequency_mhz: float) -> float:
    """The loss of a run of this cable, in dB."""
    if metres <= 0:
        return 0.0
    return db_per_100ft(cable, frequency_mhz) * (metres * FEET_PER_METRE) / 100.0
