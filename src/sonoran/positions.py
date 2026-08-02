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
