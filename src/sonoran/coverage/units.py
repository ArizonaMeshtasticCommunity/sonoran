"""The one place metres become feet.

SPLAT! reads every height as feet. It is a 1990s program and it has
never read anything else. This project speaks metres everywhere, because
everybody else does.

Passing metres straight through overstates every antenna by a factor of
3.28 and draws coverage that does not exist. The mistake is silent: the
engine takes the number, the run finishes, and the map is wrong.

See `AGENTS.md` 9.15. The planner form makes the same conversion in
`web/static/planner-params.js`.

Every height that reaches the engine passes through `metres_to_feet`.
Every name in this package that holds a height says its unit, so a bare
number cannot reach a call by accident.
"""

METRES_PER_FOOT = 0.3048


def metres_to_feet(metres: float) -> float:
    """Return a height in feet.

    Use this for every height that goes to the engine. There is no
    other conversion in this package.
    """
    return metres / METRES_PER_FOOT


def feet_to_metres(feet: float) -> float:
    """Return a height in metres.

    Use this for a height that comes back from the engine.
    """
    return feet * METRES_PER_FOOT
