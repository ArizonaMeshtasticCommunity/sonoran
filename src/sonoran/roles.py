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

# The role a node has when it names none.
#
# `config.proto` calls CLIENT the "Default Role", so a User message
# that sets no role is reporting a client rather than saying nothing.
DEFAULT_ROLE = "CLIENT"

# The roles that may transmit on a coverage map.
#
# These are deliberately sited community assets. Somebody chose the
# place, put up a mast, and left it there.
#
# `ROUTER_CLIENT` is not here. It repeats traffic, but it is usually a
# personal node that happens to have the setting turned on, and it moves
# like one.
INFRASTRUCTURE_ROLES = frozenset({"ROUTER", "ROUTER_LATE", "REPEATER"})

# The roles that repeat other nodes' traffic without being infrastructure.
#
# A coverage map drawn from routers alone answers "where does the
# backbone reach". It is the right default and it is not the only
# question. A mesh also carries traffic on ordinary nodes, and an
# operator asking "why does my neighbourhood work when no router
# covers it" is asking about these.
#
# Membership is quoted from the firmware, never inferred. The text is
# `meshtastic/config.proto`, `Config.DeviceConfig.Role`, at the
# revision in `proto/UPSTREAM_REV.txt`:
#
# - CLIENT is "App connected or stand alone messaging device", the
#   "Default Role". The proto does not say it forwards, but it defines
#   CLIENT_MUTE as the role that does not, which leaves CLIENT as one
#   that does.
# - CLIENT_BASE "Treats packets from or to favorited nodes as
#   ROUTER_LATE, and all other packets as CLIENT", and is "Used for
#   stronger attic/roof nodes to distribute messages more widely". A
#   roof node that stays on the roof is the best of these.
# - ROUTER_CLIENT is "Combination of both ROUTER and CLIENT",
#   deprecated but still set on live nodes.
#
# What is deliberately absent, and why:
#
# - CLIENT_MUTE is "Device that does not forward packets from other
#   devices". It contributes no coverage. This is the one exclusion the
#   proto states outright.
# - CLIENT_HIDDEN "Still rebroadcasts, but with local only rebroadcast
#   mode (known meshes only)", so it repeats little, and its stated
#   purpose is "stealth" and "clandestine operation". Drawing a
#   footprint around a node whose point is not being seen is a poor
#   trade for the coverage it adds.
# - TRACKER and TAK_TRACKER are mobile by definition. A footprint
#   around where a tracker was is not coverage.
# - SENSOR, TAK and LOST_AND_FOUND reduce their own routine
#   broadcasts. The proto never says whether they forward for others,
#   and this module does not assert what the vendor did not state.
#
# A NULL role is still excluded, by `is_site_role`. See the trap above:
# NULL means a client or an unintroduced node, and a run that predicted
# from every unintroduced node would be predicting from the whole mesh.
REPEATING_CLIENT_ROLES = frozenset({"CLIENT", "CLIENT_BASE", "ROUTER_CLIENT"})

# Every role a coverage run may predict from when clients are included.
EXTENDED_ROLES = INFRASTRUCTURE_ROLES | REPEATING_CLIENT_ROLES

# The name of each site set, and the roles it predicts from.
#
# `INFRASTRUCTURE` is the default and the only set the public embed
# will ever serve. `EXTENDED` is a wider view for somebody reading the
# dashboard, and `is_diagnostic_role_set` calls it diagnostic, because
# it is: a client is usually somebody's house, and it moves.
SITE_SET_INFRASTRUCTURE = "infrastructure"
SITE_SET_EXTENDED = "extended"

# What a run predicted from when the operator named the roles itself
# and the set it named is not a subset of the infrastructure roles.
#
# This set has no fixed roles, which is why it is not in
# `SITE_SET_ROLES`: it is whatever `COVERAGE_SITE_ROLES` said, and that
# is a deployment setting rather than a rule of this module.
#
# It exists because a path that says `infrastructure` must hold the
# infrastructure map. A `COVERAGE_SITE_ROLES=ALL` run used to be
# written under that name, so the directory said "routers and
# repeaters" while holding a footprint around every client node in
# region. The manifest was honest and the path was not, and the tiles
# are what a reader fetches. See `AGENTS.md` 9.25.
SITE_SET_DIAGNOSTIC = "diagnostic"

SITE_SET_ROLES: dict[str, frozenset[str]] = {
    SITE_SET_INFRASTRUCTURE: INFRASTRUCTURE_ROLES,
    SITE_SET_EXTENDED: EXTENDED_ROLES,
}

SITE_SET_LABELS: dict[str, str] = {
    SITE_SET_INFRASTRUCTURE: "Routers and repeaters",
    SITE_SET_EXTENDED: "Also nodes that repeat",
    SITE_SET_DIAGNOSTIC: "Every role this run was given",
}

# Every name a run may write a directory of tiles under.
#
# `SITE_SET_ROLES` answers "which roles does this set predict from",
# and the diagnostic set has no answer to that. This answers "may this
# name appear in a path", which is the question the dashboard tile
# route asks, and the two are not the same question. Serving a tile is
# never a reason to widen the first dictionary.
_BASE_SITE_SET_KEYS: frozenset[str] = frozenset(SITE_SET_ROLES) | {SITE_SET_DIAGNOSTIC}

# What is added to a site set's name for its approximate map (#315).
#
# A run with `COVERAGE_INCLUDE_APPROXIMATE` also predicts each map from
# positions rounded to `APPROXIMATE_SITE_PRECISION_BITS`. That is a
# different answer, so it is a different site set with its own tiles.
#
# An underscore and not a hyphen, because the dashboard tile route
# takes `^[a-z_]{1,32}$`. The name can never be `infrastructure`, and
# the public tile route reads that name and no other, so the embed
# cannot serve an approximate map. See `AGENTS.md` 9.25 and 9.27.
APPROXIMATE_SUFFIX = "_approximate"


def approximate_site_set(site_set: str) -> str:
    """Return the name of the approximate map of one site set."""
    return f"{site_set}{APPROXIMATE_SUFFIX}"


def is_approximate_site_set(site_set: str) -> bool:
    """Return true when a site set name is an approximate map."""
    return site_set.endswith(APPROXIMATE_SUFFIX)


SITE_SET_KEYS: frozenset[str] = _BASE_SITE_SET_KEYS | {
    approximate_site_set(key) for key in _BASE_SITE_SET_KEYS
}


def site_set_label(site_set: str) -> str:
    """Return what a reader is shown for one site set."""
    if is_approximate_site_set(site_set):
        base = site_set.removesuffix(APPROXIMATE_SUFFIX)
        return f"{SITE_SET_LABELS.get(base, base)}, rounded positions included"
    return SITE_SET_LABELS.get(site_set, site_set)


def site_set_roles(site_set: str) -> frozenset[str]:
    """Return the roles one site set predicts from.

    An unknown name gives the infrastructure set. The failure is to the
    narrow answer, never the wide one: a typo must not put a mesh of
    houses on a map. `parse_site_roles` fails the same way.
    """
    if site_set not in SITE_SET_ROLES:
        logger.warning("unknown coverage site set %r, using %s", site_set, SITE_SET_INFRASTRUCTURE)
        return INFRASTRUCTURE_ROLES
    return SITE_SET_ROLES[site_set]


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


def is_diagnostic_role_set(allowed: frozenset[str] | None) -> bool:
    """Return true when a role set can include a personal node.

    A subset of the infrastructure roles is still safe to publish. It
    is non-standard, but it cannot add a handheld or an unknown node.
    `None` means every role and is always diagnostic.
    """
    return allowed is None or not allowed.issubset(INFRASTRUCTURE_ROLES)


def resolve_role(role: str | None, long_name: str | None, short_name: str | None) -> str | None:
    """Return the role of a node, reading an old NULL for what it meant.

    Since #197 the ingest writes `CLIENT` as `CLIENT`, so new rows do
    not need this. Rows written before it are still NULL for every
    client on the mesh -- 167 of them on MediumFast when the issue was
    filed -- and they cannot be backfilled by a migration, because
    nothing in the database says which NULLs were clients.

    Something does say it indirectly. `long_name` and `short_name` are
    written in one statement with `role`, in `store_nodeinfo`, and
    **nowhere else in the ingest**. So a row that carries a name is a
    row where a User message was processed, which is exactly the case
    the old code turned into NULL. A row with no name at all is a node
    that has only ever been seen relaying or being mentioned, and its
    role is genuinely unknown.

    This is an inference and it is the weaker half of the fix. It is
    kept here, beside the trap it answers, rather than in the one page
    that needs it, so a second page cannot grow a second version of the
    rule that disagrees.

    **It expires.** Every node that sends NodeInfo again gets a real
    role written, so the set this touches only shrinks. When
    `SELECT count(*) FROM node WHERE role IS NULL AND long_name IS NOT
    NULL` reaches zero, this function can go.

    One case it gets wrong, stated rather than hidden: a node running a
    role number the vendored proto did not know *also* stored NULL
    before #197, and this calls it a client. That is bounded -- the
    firmware ships few roles and this repository vendors them -- and it
    is strictly better than the grey it replaces, which called every
    client an unknown.
    """
    if role:
        return role
    if long_name or short_name:
        return DEFAULT_ROLE
    return None
