"""Land cover classes and the clutter they stand for.

The terrain model says where the ground is. It does not say what stands
on the ground. A signal that clears a ridge can still be stopped by the
houses or the trees at either end of the path.

ITM has no clutter model of its own. It treats both ends as if they
stood in open country. ITU-R P.2108 is the correction for that, and
ITU-R P.1812 uses the same method. Both need to know how tall the
clutter is, and that is what this table gives.

The classes are the eleven of the ESA WorldCover 10 m product. The
heights are nominal figures for a propagation model, not measurements.
Arizona is mostly shrubland and bare ground, which is why a prediction
with no clutter at all has worked tolerably here. What it gets wrong is
Phoenix and Tucson, and that is class 50.
"""

from dataclasses import dataclass

# The value of a cell with no land cover data.
UNKNOWN_CLASS = 0


@dataclass(frozen=True)
class LandCover:
    """One land cover class."""

    code: int
    name: str
    # The nominal height of what stands on the ground, in metres.
    clutter_height_m: float


# The ESA WorldCover classes, by their own code.
CLASSES: dict[int, LandCover] = {
    10: LandCover(10, "Tree cover", 15.0),
    20: LandCover(20, "Shrubland", 2.0),
    30: LandCover(30, "Grassland", 0.5),
    40: LandCover(40, "Cropland", 1.0),
    50: LandCover(50, "Built-up", 9.0),
    60: LandCover(60, "Bare or sparse vegetation", 0.0),
    70: LandCover(70, "Snow and ice", 0.0),
    80: LandCover(80, "Permanent water", 0.0),
    90: LandCover(90, "Herbaceous wetland", 0.5),
    95: LandCover(95, "Mangroves", 10.0),
    100: LandCover(100, "Moss and lichen", 0.0),
}

# What to assume where there is no land cover data.
#
# Zero, which is what the planner has always assumed. It is the honest
# value: a guess at clutter that is not there would move every
# prediction for no reason. A page that draws a prediction with no
# clutter data must say so.
UNKNOWN = LandCover(UNKNOWN_CLASS, "Unknown", 0.0)


def land_cover(code: int) -> LandCover:
    """Return the class for a code. An unknown code gives `UNKNOWN`."""
    return CLASSES.get(code, UNKNOWN)


def clutter_height_m(code: int) -> float:
    """Return the nominal clutter height of a class, in metres."""
    return land_cover(code).clutter_height_m
