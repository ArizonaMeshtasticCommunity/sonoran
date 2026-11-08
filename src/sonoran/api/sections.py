"""The parts of the site an operator can hide (`HIDDEN_SECTIONS`).

Logan asked for this on 2026-10-21, for the test roll-out to main: a
deployment must be able to keep an unfinished part of the site out of
view without a code change.

A hidden section is hidden in two places:

- **On the page.** `index.html` gets the list in its config, and
  `web/static/sections.js` takes the section out of the menu, the phone
  bar and the links that lead there. Its address shows "This part of
  Sonoran isn't available yet".
- **On the server.** Its API routes answer 404, so the feature is not
  only out of sight. `gate` does this for every route, from one table.

THE RULE FOR A ROUTE. A route closes only when **every** section that
uses it is hidden. `/api/map/nodes` draws the live map, the coverage
map and the planner, so hiding the map alone leaves it open. A route
that a page which can never be hidden needs (the dashboard, a node
page, a packet page) is `SHARED` and never closes.

`tests/unit/test_hidden_sections.py` fails when a registered route is in
neither table, so a new route is a decision and not an accident.
"""

from dataclasses import dataclass

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class Section:
    """One part of the site that can be hidden."""

    #: The words the menu uses for it.
    label: str
    #: The page it is a part of, or None for a page of its own.
    parent: str | None = None


# The ids are the page names in the address (`#rf`) and in the menu
# (`data-nav="rf"`), so an operator reads them off the address bar.
SECTIONS: dict[str, Section] = {
    "map": Section("Map"),
    "nodes": Section("Nodes"),
    "chat": Section("Chat"),
    "traceroutes": Section("Traceroutes"),
    "graph": Section("Graph"),
    "coverage": Section("Coverage"),
    "planner": Section("Planner"),
    "gaps": Section("Gaps"),
    "config": Section("Config check"),
    "meshnet": Section("Weekly check-in"),
    "firehose": Section("Firehose"),
    "rf": Section("RF"),
    "stats": Section("Statistics"),
    "leaderboards": Section("Leaderboards", parent="stats"),
}

# Pages that cannot be hidden, and why. An id here is refused like an
# unknown one, with this reason in the log line.
NOT_HIDDEN: dict[str, str] = {
    "dashboard": "it is the home page, and the 'not available' page links to it",
    "settings": "it holds the reader's own choices",
}


def resolve(ids: list[str]) -> tuple[frozenset[str], list[str]]:
    """Return the sections to hide, and the ids that are not sections.

    Case and space are ignored. A page takes its parts with it: hiding
    `stats` hides `leaderboards` too.
    """
    wanted: set[str] = set()
    unknown: list[str] = []
    for raw in ids:
        name = raw.strip().lower()
        if not name:
            continue
        if name in SECTIONS:
            wanted.add(name)
        elif name not in unknown:
            unknown.append(name)
    for name, section in SECTIONS.items():
        if section.parent in wanted:
            wanted.add(name)
    return frozenset(wanted), unknown


def describe_unknown(unknown: list[str]) -> str:
    """Say why each refused id was refused, for the start-up log."""
    return ", ".join(
        f"{name!r} ({NOT_HIDDEN[name]})" if name in NOT_HIDDEN else repr(name) for name in unknown
    )


_PLANNER = frozenset({"planner"})
_RF = frozenset({"rf"})
_GAPS = frozenset({"gaps"})
_COVERAGE = frozenset({"coverage"})
_CHAT = frozenset({"chat"})
_MAP = frozenset({"map"})
_STATS = frozenset({"stats"})

# Each route template, and the sections whose pages call it.
#
# Found by reading which page of `web/static/` asks for each path. A
# route that no page asks for (for example `/api/map/track/...`) goes
# with the part of the API it is named for.
ROUTES: dict[str, frozenset[str]] = {
    # Chat. The dashboard's "Latest messages" card is a part of chat and
    # is hidden with it, so the dashboard is not a user here.
    "/api/chat": _CHAT,
    "/api/chat/channels": _CHAT,
    "/api/chat/conversation/{from_node}/{packet_id}": _CHAT,
    "/api/chat/overview": _CHAT,
    # The weekly check-in reads the tagged messages, not the chat page.
    "/api/chat/tagged": frozenset({"meshnet"}),
    # The planner: terrain, climate, the radio catalogue, address search.
    "/api/climate/classes": _PLANNER,
    "/api/climate/page/{tile}": _PLANNER,
    "/api/terrain/page/{tile}": _PLANNER,
    "/api/terrain/region": _PLANNER,
    "/api/radio/adapters": _PLANNER,
    "/api/radio/antennas": _PLANNER,
    "/api/radio/boards": _PLANNER,
    "/api/radio/cables": _PLANNER,
    "/api/geocode": _PLANNER,
    # Coverage, and the embed, which is the coverage map on another site.
    "/api/coverage": _COVERAGE,
    "/api/coverage/calibration": _COVERAGE,
    "/api/coverage/tiles/{stamp}/{preset}/{site_set}/{layer}/{zoom}/{x}/{y}.png": _COVERAGE,
    "/api/coverage/tiles/{stamp}/{preset}/{site_set}/{layer}/margin/{zoom}/{x}/{y}.png": _COVERAGE,
    # The heard positions layer (#344) is drawn on the coverage page only.
    "/api/map/heatmap/{model}/{z}/{x}/{y}.png": _COVERAGE,
    "/embed/coverage": _COVERAGE,
    "/api/embed/coverage": _COVERAGE,
    "/api/embed/nodes": _COVERAGE,
    "/api/embed/tiles/{stamp}/{preset}/{layer}/{zoom}/{x}/{y}.png": _COVERAGE,
    # Gaps. The node page's health panel reads `/api/nodes/{id}/gaps`,
    # which is SHARED: a node page is reached from everywhere.
    "/api/gaps": _GAPS,
    "/api/gaps/areas": _GAPS,
    "/api/gaps/candidates": _GAPS,
    "/api/gaps/nodes": _GAPS,
    # The graph. Its preset list also fills the live map's.
    "/api/graph": frozenset({"graph"}),
    "/api/graph/channels": frozenset({"graph", "map"}),
    # The live map. Its node list also draws coverage and the planner.
    "/api/map/nodes": frozenset({"map", "coverage", "planner"}),
    "/api/map/edges": _MAP,
    "/api/map/traceroute-paths": _MAP,
    "/api/map/track/{node_id}": _MAP,
    "/api/map/traffic": _MAP,
    # The nodes list. The rest of `/api/nodes` is the node page: SHARED.
    "/api/nodes/export": frozenset({"nodes"}),
    "/api/nodes/facets": frozenset({"nodes"}),
    # The firehose list. One packet's page is SHARED.
    "/api/packets": frozenset({"firehose"}),
    # RF.
    "/api/rf/channels": _RF,
    "/api/rf/custom": _RF,
    "/api/rf/heard/{station}": _RF,
    "/api/rf/kinds": _RF,
    "/api/rf/latest": _RF,
    "/api/rf/noise-floor": _RF,
    "/api/rf/spectrum/{station}": _RF,
    "/api/rf/spectrum/{station}/ranges": _RF,
    "/api/rf/stations": _RF,
    "/api/rf/sweeps": _RF,
    "/api/rf/track/{kind}/{thing_id}": _RF,
    # Statistics. The summary, the busiest nodes and the packet types
    # are on the dashboard as well: SHARED.
    "/api/stats/activity": _STATS,
    "/api/stats/broadcast": _STATS,
    "/api/stats/daily": _STATS,
    "/api/stats/hardware": _STATS,
    "/api/stats/reliability/{node_id}": _STATS,
    "/api/stats/leaderboards": frozenset({"leaderboards"}),
    # The traceroutes list. One traceroute's page is SHARED.
    "/api/traceroutes": frozenset({"traceroutes"}),
}

# Routes that never close: the page, its worker and manifest, the
# health check, and what the dashboard and the detail pages (a node, a
# packet, a link, a traceroute) need. Those pages cannot be hidden.
SHARED: frozenset[str] = frozenset(
    {
        "/",
        "/sw.js",
        "/static",
        "/static/manifest.webmanifest",
        "/health",
        "/api/version",
        "/api/nodes",
        "/api/nodes/{node_id}",
        "/api/nodes/{node_id}/config",
        "/api/nodes/{node_id}/detail",
        "/api/nodes/{node_id}/gaps",
        "/api/nodes/{node_id}/graph",
        "/api/nodes/{node_id}/heard-by",
        "/api/nodes/{node_id}/history",
        "/api/nodes/{node_id}/neighbors",
        "/api/nodes/{node_id}/packets",
        "/api/nodes/{node_id}/radio",
        "/api/nodes/{node_id}/routes",
        "/api/nodes/{node_id}/signal",
        "/api/nodes/{node_id}/telemetry",
        "/api/packets/{from_node}/{packet_id}",
        "/api/graph/link",
        "/api/stats",
        "/api/stats/portnums",
        "/api/stats/snapshots/daily",
        "/api/stats/top",
        "/api/traceroutes/by-packet/{from_node}/{packet_id}",
        "/api/traceroutes/{trace_id}",
        "/api/traceroutes/{trace_id}/drawing.svg",
        "/api/traceroutes/{trace_id}/drawing-nodes",
    }
)


def is_closed(path: str, hidden: frozenset[str]) -> bool:
    """True when every section that uses this route template is hidden."""
    users = ROUTES.get(path)
    return users is not None and users <= hidden


async def gate(request: Request) -> None:
    """Answer 404 for a route of a hidden section.

    An app-wide dependency, so it runs after routing and reads the
    route's template (`/api/rf/track/{kind}/{thing_id}`), not the path
    the caller sent. A path cannot be spelled past it.
    """
    hidden: frozenset[str] = getattr(request.app.state, "hidden_sections", frozenset())
    if not hidden:
        return
    route = request.scope.get("route")
    path = getattr(route, "path", "")
    if is_closed(path, hidden):
        raise HTTPException(status_code=404, detail="Not Found")
