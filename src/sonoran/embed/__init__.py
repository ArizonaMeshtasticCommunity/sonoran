"""What a public viewer of the coverage map may see.

The dashboard shows the mesh to the people who run it. An embed on
somebody else's website shows it to everybody, and those are not the
same audience.

This package is the only place that decides the difference. It is the
same arrangement as `sonoran/positions.py`, which holds the one test
for a usable position, and `sonoran/api/traces.py`, which holds the one
reading of a traceroute row. One module, one rule, so two pages cannot
disagree about what is public.

The embed is off until somebody turns it on. See `EMBED_ENABLED`.
"""

from sonoran.embed.sanitise import (
    PUBLIC_ROLES,
    PublicNode,
    coarse,
    frame_ancestors,
    is_public_node,
    public_nodes,
)

__all__ = [
    "PUBLIC_ROLES",
    "PublicNode",
    "coarse",
    "frame_ancestors",
    "is_public_node",
    "public_nodes",
]
