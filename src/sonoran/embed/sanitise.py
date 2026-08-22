"""The one rule for what leaves the server to a public page.

Three things are taken off a node before it goes out:

- Every node that is not infrastructure. A router or a repeater is a
  thing somebody chose to put on a hill and told the mesh about. A
  client node is usually a person, often at home, and it never appears
  here, whatever else it does.
- The exact position. What is left is snapped to a grid, so the marker
  says which hill and not which building.
- Every name but the short one, the hardware, the topic, and the time
  the node was last heard. A public map needs to show that a site
  exists, not to describe it.

`/api/map/nodes` is untouched by all of this. It serves the dashboard,
which is a different audience.
"""

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from urllib.parse import urlsplit

from sonoran.roles import INFRASTRUCTURE_ROLES

# The roles a public map may show.
#
# These are deliberately sited community assets. The mesh depends on
# them and their operators put them where everybody could see them.
#
# It is the same table the coverage job predicts from, held in one
# place. The two rules are still different, and the difference is the
# gateway below: "what a stranger may see" is not "what may transmit".
PUBLIC_ROLES = INFRASTRUCTURE_ROLES

# What a host may look like in a framing origin.
#
# `urlsplit` is not a validator. It keeps a space or a semicolon inside
# the network location, and the answer here is put straight into a
# `Content-Security-Policy` header, where `frame-ancestors` is the last
# directive. A semicolon therefore starts a new one:
#
#     EMBED_FRAME_ANCESTORS='https://azmsh.net;script-src *'
#
# would have replaced the script policy of the embed with a wildcard.
# A wildcard host is refused for the same reason: `https://*` lets any
# site frame the page.
HOST = re.compile(r"[A-Za-z0-9.\-]+(:\d{1,5})?")


@dataclass(frozen=True)
class PublicNode:
    """One node, as a public page may see it."""

    short_name: str
    latitude: float
    longitude: float
    role: str
    is_gateway: bool


def is_public_node(role: str | None, is_mqtt_gateway: bool) -> bool:
    """Return true when a node may appear on a public map.

    The role decides, and only the role. Being an MQTT gateway is not
    enough and used to be.

    The reason it used to be is that running a gateway reads like a
    deliberate act of infrastructure. It is not one.
    `ingest/handlers/presence.py` sets the flag for **any** node that
    publishes a packet, and never clears it, so a person who turns the
    MQTT uplink on in the radio on their kitchen table is marked a
    gateway for ever. The rule put that kitchen on a public map, at a
    kilometre, with no way to come off it.

    A gateway that really is infrastructure has a role that says so and
    still appears. `is_gateway` stays on the answer, because the map
    draws a ring around one, but it no longer decides who is on it.
    """
    del is_mqtt_gateway  # Named to say it is deliberately not used.
    return (role or "").upper() in PUBLIC_ROLES


def coarse(value: float, step_degrees: float) -> float:
    """Return a coordinate snapped to a grid.

    Snapping and not rounding at the last decimal, because a rounded
    coordinate is still a coordinate. A step of 0.01 degrees is about a
    kilometre, which names a hill and not a building.

    A step of zero returns the value unchanged, which is what a
    deployment that wants exact positions asks for.
    """
    if step_degrees <= 0.0:
        return value
    return round(math.floor(value / step_degrees) * step_degrees + step_degrees / 2.0, 6)


def public_nodes(
    rows: Iterable[tuple[str | None, str | None, float | None, float | None, str | None, bool]],
    step_degrees: float,
) -> list[PublicNode]:
    """Return the nodes a public page may see.

    Each row is short name, long name, latitude, longitude, role, and
    whether the node is an MQTT gateway. The long name is taken as an
    argument and never returned: naming it here makes it obvious at the
    call site that it was dropped on purpose.
    """
    out: list[PublicNode] = []
    for short_name, _long_name, latitude, longitude, role, is_gateway in rows:
        if latitude is None or longitude is None:
            continue
        if not is_public_node(role, is_gateway):
            continue
        out.append(
            PublicNode(
                short_name=(short_name or "").strip()[:8],
                latitude=coarse(latitude, step_degrees),
                longitude=coarse(longitude, step_degrees),
                role=(role or "").upper(),
                is_gateway=bool(is_gateway),
            )
        )
    return out


def frame_ancestors(origins: Sequence[str]) -> str:
    """Return the `frame-ancestors` value for the embed.

    Every origin is put through the same check the rest of the security
    headers use, so a value that is not an origin cannot widen the
    policy. An empty or unusable list gives `'none'`, which is what the
    dashboard has. It never gives `*`.
    """
    safe: list[str] = []
    for origin in origins:
        parts = urlsplit(origin.strip())
        if parts.scheme in {"http", "https"} and HOST.fullmatch(parts.netloc):
            value = f"{parts.scheme}://{parts.netloc}"
            if value not in safe:
                safe.append(value)
    return " ".join(safe) if safe else "'none'"
