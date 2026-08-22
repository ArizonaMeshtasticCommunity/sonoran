"""What counts as a piece of mesh infrastructure.

A coverage map answers "where does the mesh reach". Only a node that
stays where it is can answer it. A router on a hill is there tomorrow. A
handheld that crossed town once is not, and drawing a permanent
footprint around it promises reach that nobody can use.

This module holds the one test for that, so the coverage job and the
public embed agree on it. It touches nothing but the log.

## The trap

Meshtastic numbers its device roles from zero, and `CLIENT` is zero.
`ingest/handlers/nodeinfo.py` reads an enum with

    if not value:
        return None

so a plain client arrives as NULL, and is then stored exactly like a
node that has never introduced itself at all. The database cannot tell
the two apart.

A NULL role is therefore not "unknown, so include it". It is "a client,
or a node we know nothing about", and neither may hold coverage open.
`docs/COVERAGE.md` 11 and `AGENTS.md` 9.22 say the same.
"""

from sonoran.logging import get_logger

logger = get_logger(__name__)

# The roles that may transmit on a coverage map.
#
# These are deliberately sited community assets. Somebody chose the
# place, put up a mast, and left it there.
#
# `ROUTER_CLIENT` is not here. It repeats traffic, but it is usually a
# personal node that happens to have the setting turned on, and it moves
# like one.
INFRASTRUCTURE_ROLES = frozenset({"ROUTER", "ROUTER_LATE", "REPEATER"})

# What a node with no role is counted as in a report.
#
# The manifest counts the nodes a run left out, by role. A NULL role
# needs a name to be counted under, and the name must not look like a
# role that exists.
NO_ROLE = "NULL"


def is_infrastructure(role: str | None) -> bool:
    """Return true when a node may be a coverage transmitter.

    A missing role is false. See the trap in the module docstring: NULL
    means a client or an unintroduced node, and never "unknown".
    """
    return (role or "").upper() in INFRASTRUCTURE_ROLES


def role_name(role: str | None) -> str:
    """Return the name to count a node under in a report."""
    return (role or "").upper() or NO_ROLE


# Every role the firmware defines, for checking a setting against.
#
# Not a rule about what may transmit — `INFRASTRUCTURE_ROLES` is that.
# This exists so a typo in `COVERAGE_SITE_ROLES` is caught and said out
# loud. `ROUTR` parses to a set that matches nothing, the run finds no
# site, and the log line blames the mesh for having no routers on it.
# The operator then goes looking at the mesh.
#
# A name that is not here is still used. Firmware adds roles, and a
# deployment must not be stopped by a version of this list that is a
# release behind. It is warned about, and nothing more.
KNOWN_ROLES = frozenset(
    {
        "CLIENT",
        "CLIENT_MUTE",
        "ROUTER",
        "ROUTER_CLIENT",
        "REPEATER",
        "TRACKER",
        "SENSOR",
        "TAK",
        "CLIENT_HIDDEN",
        "LOST_AND_FOUND",
        "TAK_TRACKER",
        "ROUTER_LATE",
        "CLIENT_BASE",
    }
)

# What an operator writes to ask for every role at once.
#
# Logan asked for this on the pull request: the infrastructure filter is
# right for the map somebody publishes, and an "all nodes" run is still
# the way to answer "why is this ridge empty?".
EVERY_ROLE = "ALL"


def parse_site_roles(text: str) -> frozenset[str] | None:
    """Return the roles a coverage run may predict from.

    None means every role, which is the diagnostic answer. A run in that
    state is not a coverage map and must say so on the page: see
    `Manifest.is_diagnostic`.

    An empty or unreadable setting gives the infrastructure set. A
    deployment must not lose its filter to a typo, so the failure is to
    the safe answer rather than to the wide one.
    """
    wanted = {part.strip().upper() for part in text.split(",") if part.strip()}
    if not wanted:
        return INFRASTRUCTURE_ROLES
    if EVERY_ROLE in wanted:
        return None
    unknown = sorted(wanted - KNOWN_ROLES)
    if unknown:
        # Said here, once, at the point the setting is read. A name
        # that is not a role matches nothing, and the run then reports
        # that the mesh has no routers on it, which sends the reader to
        # the wrong place entirely.
        logger.warning(
            "COVERAGE_SITE_ROLES names %s, which %s not a Meshtastic role. "
            "No node will match. The roles are: %s, or %s for every one.",
            ", ".join(unknown),
            "is" if len(unknown) == 1 else "are",
            ", ".join(sorted(KNOWN_ROLES)),
            EVERY_ROLE,
        )
    return frozenset(wanted)


def is_site_role(role: str | None, allowed: frozenset[str] | None) -> bool:
    """Return true when a node may be a coverage transmitter.

    `allowed` of None accepts everything, including a NULL role. That is
    the diagnostic run and nothing else may use it. The public embed
    asks `is_public_node`, which is fixed to the infrastructure set and
    takes no setting, so a diagnostic run cannot put a stranger's house
    on a public map.
    """
    if allowed is None:
        return True
    return (role or "").upper() in allowed
