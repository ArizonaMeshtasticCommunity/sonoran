"""What counts as a usable position.

A Meshtastic node that has never had a fix, or whose owner never set a
fixed position, still sends a position packet. The coordinates in it are
not a place. They are whatever the field held, which is usually zero or
near it, and that lands the node in the Gulf of Guinea.

This module holds the one test for that, so the ingest and the API agree
on it. It has no dependencies and touches nothing.
"""

# How close to (0, 0) a position must be before it is rejected.
#
# Null Island is open ocean off West Africa. Half a degree around it is
# about 55 km of sea in every direction, so nothing real is lost. The
# margin is needed because an unset position is not always exactly zero:
# a node was seen at 0.0262144, which is 262144 over ten million, and
# 262144 is two to the eighteenth. That is a bit pattern, not a place.
NULL_ISLAND_MARGIN = 0.5


def is_usable(latitude: float | None, longitude: float | None) -> bool:
    """Return true when a position names somewhere a node could be.

    A position fails when any of these hold:

    - Either value is missing.
    - Either value is outside the range the earth has.
    - Both values sit within `NULL_ISLAND_MARGIN` of zero.

    The last test needs both values, not either. A node really can sit
    on the equator, and one really can sit on the Greenwich meridian.
    Only a node at both at once is telling us it does not know.
    """
    if latitude is None or longitude is None:
        return False
    if not (-90.0 <= latitude <= 90.0):
        return False
    if not (-180.0 <= longitude <= 180.0):
        return False
    return not (abs(latitude) < NULL_ISLAND_MARGIN and abs(longitude) < NULL_ISLAND_MARGIN)


def clean(latitude: float | None, longitude: float | None) -> tuple[float | None, float | None]:
    """Return the position, or a pair of None when it is not usable."""
    if not is_usable(latitude, longitude):
        return (None, None)
    return (latitude, longitude)


# How coarse a position may be and still name a place, in bits.
#
# Meshtastic can send a position with fewer bits than it measured. The
# firmware calls it `position_precision`, and the public broker at
# mqtt.meshtastic.org limits what it relays to between 10 and 16 bits.
# Map reporting defaults to 14, which is about 1459 m.
#
# Sixteen bits is about 365 m. The terrain under a prediction is 90 m
# across, so even the finest setting the public broker allows is four
# terrain cells of doubt. Below that the node could be on the other
# side of a ridge, and a coverage footprint drawn around it describes
# ground that has no radio on it.
MIN_SITE_PRECISION_BITS = 16

# What each precision setting costs, in metres of deviation.
#
# The firmware table. Only the values the public broker sends are
# listed; a node that reports its position in full sends 32.
PRECISION_DEVIATION_M: dict[int, float] = {
    10: 23300.0,
    11: 11700.0,
    12: 5800.0,
    13: 2900.0,
    14: 1459.0,
    15: 729.0,
    16: 364.7,
    17: 182.4,
    18: 91.2,
    19: 45.6,
    32: 0.0,
}


def precision_deviation_m(bits: int | None) -> float | None:
    """Return how far a position of this precision may be from the truth.

    None when nothing is known about the precision. A value between two
    listed settings takes the coarser of the two, because each bit
    halves the deviation.
    """
    if bits is None or bits <= 0:
        return None
    if bits >= 32:
        return 0.0
    known = sorted(PRECISION_DEVIATION_M)
    for value in known:
        if bits <= value:
            return PRECISION_DEVIATION_M[value]
    return 0.0


def is_precise_enough(bits: int | None, minimum: int = MIN_SITE_PRECISION_BITS) -> bool:
    """Return true when a position may anchor a coverage prediction.

    **A missing value is true, and that is the decision this function
    exists to make.** `ingest/handlers/position.py` writes

        "precision_bits": position.precision_bits or None,

    so a node that sent no precision field at all and a node that sent
    zero both arrive as NULL. The first is the common case for a node
    heard directly over the radio, and it is full precision.

    So the rule is to exclude a position **known** to be coarse, never
    one that failed to say. A run reports the two counts apart, so
    nobody has to guess which one a mesh is made of.

    A `minimum` of zero turns the test off, for a deployment that reads
    its own broker and trusts every position it is given.
    """
    if minimum <= 0:
        return True
    if bits is None or bits <= 0:
        return True
    return bits >= minimum


# The two site-selection rules for position precision (#315).
#
# `precise` is what every published coverage map predicts from. A
# position must be `MIN_SITE_PRECISION_BITS` or better, or an operator
# must give one. This is the decision Logan and Tyler asked for and Will
# made on 2026-10-08: a footprint drawn from a rounded point can sit in
# the wrong valley, and the compute it costs is wasted.
#
# `approximate` also takes positions rounded down to
# `APPROXIMATE_SITE_PRECISION_BITS`. A host may publish such a map as a
# separate site set, beside the precise one and never instead of it. The
# public embed never reads it. See `docs/COVERAGE.md` 9.1.2.
SITE_PRECISION_PRECISE = "precise"
SITE_PRECISION_APPROXIMATE = "approximate"
SITE_PRECISIONS = (SITE_PRECISION_PRECISE, SITE_PRECISION_APPROXIMATE)

# The coarsest position the approximate rule takes, by default.
#
# 13 bits is 2.9 km. It is what most of the Arizona backbone shares
# through the public broker, and it is the value s.azmsh.dev ran with
# after #318. Below it the broker's own coarsest settings begin.
APPROXIMATE_SITE_PRECISION_BITS = 13


def precise_minimum_bits(configured: int) -> int:
    """Return the precision the precise rule asks for, in bits.

    `configured` is `COVERAGE_MIN_PRECISION_BITS`. It may raise the
    floor, and zero still turns the test off for a deployment that reads
    its own broker. It may not lower the floor below
    `MIN_SITE_PRECISION_BITS`: a value from 1 to 15 asked for rounded
    positions on the main map, and that is what #315 stopped. Such a
    host gets 16, and the coverage job says so in its log.
    """
    if configured <= 0:
        return 0
    return max(configured, MIN_SITE_PRECISION_BITS)


def site_minimum_bits(precision: str, configured_precise: int, configured_approximate: int) -> int:
    """Return the precision one site-selection rule asks for, in bits.

    The approximate rule is never stricter than the precise one. It is
    the precise map and more, so every precise site is also on it.
    """
    precise = precise_minimum_bits(configured_precise)
    if precision == SITE_PRECISION_PRECISE:
        return precise
    if precision == SITE_PRECISION_APPROXIMATE:
        if precise == 0:
            return 0
        return min(precise, max(configured_approximate, 0))
    raise ValueError(f"not a site precision: {precision!r}")
