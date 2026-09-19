"""Terminal clutter loss, from ITU-R P.2108-1 section 3.1.

A propagation model works over the ground. It does not know that one
end of the link is a handheld standing among two-storey buildings, or
that the other is a node on a shed roof under trees. The loss that
costs is a property of the last few metres at each end, and this module
is the only place that decides it.

## Why not the clutter the engine already takes

`splat_create` takes a clutter height, and SPLAT uses it by raising the
ground. Measured on flat ground at 906 MHz, over a 20 km radius:

    clutter      tx 3 m     tx 9 m    tx 30 m
      0 m       -118.6 dB  -107.9 dB  -95.2 dB
      2 m       -118.4     -108.1     -95.2
      5 m       -158.8     -109.0     -95.2
      9 m       -185.1     -108.6     -95.2
     15 m       -189.6     -172.5     -95.2

That is a cliff, not a curve. While the antenna clears the clutter it
costs nothing at all; once it does not, the terminal is buried and the
field falls by forty to seventy dB. Neither answer describes a radio.
The receiver height changes it by 0.00 dB at any height, so the end the
whole map is drawn for was never charged anything.

So the engine is given no clutter, and the loss is applied here as a
number of dB at each end. See `docs/COVERAGE.md` 7.

## The model

P.2108-1 section 3.1, the height gain terminal correction. It is valid
from 0.03 to 3 GHz, and the Meshtastic US band at 906.875 MHz sits
inside that. It applies to both ends of a path, by the same equations.

A terminal at or above the representative clutter height takes no loss.
Below it, the recommendation gives two forms, and which one to use
depends on what the clutter is:

- Equation (2a), diffraction over an obstacle, for buildings and trees.
- Equation (2b), a height gain against the ground, for open country.
"""

import math

import numpy as np
import numpy.typing as npt

from sonoran.landcover.classes import CLASSES

# The width of a street, in metres.
#
# P.2108 Table 2 says to use 27 unless there is local information, and
# there is none here: the land cover product names a class for each
# hundred metres of ground and says nothing about streets.
STREET_WIDTH_M = 27.0

# The lowest terminal height the model is evaluated at, in metres.
#
# Equation (2b) is a ratio of the terminal height to the clutter
# height, so it runs away as the height goes to zero. Ten centimetres
# is below any radio somebody carries and keeps the answer finite.
MINIMUM_TERMINAL_M = 0.1

# The band edges the model is defined over, in MHz.
FREQUENCY_MIN_MHZ = 30.0
FREQUENCY_MAX_MHZ = 3000.0


def knife_edge_db(nu: float) -> float:
    """Return the knife edge diffraction loss for a Fresnel parameter.

    This is J(v), the approximation P.2108-1 equation (1) gives and that
    ITU-R P.526 uses for a single rounded or sharp obstacle. It is the
    same function whether the obstacle is a row of buildings at one end
    of a path or a ridge in the middle of it, so it is written once
    here.

    `nu` is the usual Fresnel-Kirchhoff parameter:

        nu = h * sqrt(2 * (d1 + d2) / (lambda * d1 * d2))

    where `h` is how far the obstacle stands above the straight line
    between the two antennas. A negative `h`, which is a clear path,
    gives a negative `nu` and no loss.

    The recommendation notes that J(-0.78) is about zero and sets the
    function to zero below that, which is the lower limit the
    approximation holds to.
    """
    if nu <= -0.78:
        return 0.0
    shifted = nu - 0.1
    return 6.9 + 20.0 * math.log10(math.sqrt(shifted * shifted + 1.0) + shifted)


def _j(nu: float) -> float:
    """Return the knife edge approximation. The name P.2108 uses."""
    return knife_edge_db(nu)


def terminal_loss_db(
    clutter_height_m: float,
    terminal_height_m: float,
    frequency_mhz: float,
    diffracting: bool,
) -> float:
    """Return the clutter loss at one end of a path, in dB.

    `clutter_height_m` is the representative height of what stands on
    the ground around the terminal. `diffracting` picks the form: true
    for buildings and trees, where the signal bends over an obstacle,
    false for open country, where the ground itself is the obstacle.

    The answer is never negative. A terminal at or above the clutter
    takes nothing, which is the recommendation's own boundary and also
    the sense of it: an antenna above the roofs sees over them.
    """
    if clutter_height_m <= 0.0 or terminal_height_m >= clutter_height_m:
        return 0.0
    # A terminal on the ground is as deep in the clutter as it gets,
    # not out of it. Equation (2b) divides by the height, so it needs a
    # floor rather than a special case: returning zero here made the
    # loss jump from 34 dB at five centimetres to nothing at zero.
    terminal_height_m = max(terminal_height_m, MINIMUM_TERMINAL_M)

    ghz = max(FREQUENCY_MIN_MHZ, min(frequency_mhz, FREQUENCY_MAX_MHZ)) / 1000.0
    difference = clutter_height_m - terminal_height_m

    if not diffracting:
        # (2b) and (2f). The height gain near the ground in open places.
        k_h2 = 21.8 + 6.2 * math.log10(ghz)
        return max(0.0, -k_h2 * math.log10(terminal_height_m / clutter_height_m))

    # (2a), (2c), (2e) and (2g). Diffraction over the clutter.
    theta_clut = math.degrees(math.atan(difference / STREET_WIDTH_M))
    k_nu = 0.342 * math.sqrt(ghz)
    nu = k_nu * math.sqrt(difference * theta_clut)
    return max(0.0, _j(nu) - 6.03)


def loss_by_class(terminal_height_m: float, frequency_mhz: float) -> npt.NDArray[np.uint8]:
    """Return the terminal loss of every land cover code, in whole dB.

    A land cover page holds one byte for each cell, so the answer is a
    lookup table of 256 entries and the whole raster is one index into
    it. An unknown code is charged nothing, which is what a deployment
    with no land cover data already predicts.

    Whole dB is enough. The levels the map is drawn from are whole dB
    themselves, and the model behind this is a median over a clutter
    category, not a measurement of one street.
    """
    table = np.zeros(256, dtype=np.uint8)
    for code, cover in CLASSES.items():
        loss = terminal_loss_db(
            cover.clutter_height_m, terminal_height_m, frequency_mhz, cover.diffracting
        )
        table[code] = min(255, round(loss))
    return table
