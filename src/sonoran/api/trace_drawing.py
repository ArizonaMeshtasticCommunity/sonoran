"""A mesh-graph traceroute drawing, recoloured for the dark site.

mesh-graph draws a trace with Graphviz: a white page, black edges and
black Times text. Sonoran is dark throughout, so opening a trace was a
flash of white. mesh-graph is third party code and is not changed here,
and a CSS filter over its picture inverts its colours along with the
white (see `app.css` and issue #51). So the API fetches the SVG itself,
over the compose network, and rewrites only the neutral colours:

- The page background becomes transparent, so the panel shows through.
- Edges, arrowheads, edge labels and loose text become light.
- Node shapes keep mesh-graph's own fills, because the colours mean
  something there. The one exception is plain white, the fill of an
  ordinary node, which becomes a warm off-white so a page of them is not
  a page of glare. Text on a filled node stays dark, because it sits on
  a pastel fill. Text on an unfilled node becomes light.

The page shows the result in an `<img>`, where an SVG runs no script and
follows no link, so a drawing from a third party stays inert.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from sonoran.config import Settings

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)

# The site palette, from `app.css`. An SVG in an `<img>` cannot read the
# page's custom properties, so the two values it needs are written here.
LIGHT_TEXT = "#f6ece2"
LIGHT_LINE = "#cdbcae"
# An ordinary node, in place of pure white. Dark text still reads on it.
NODE_PLAIN = "#e3d5c7"

# A drawing larger than this is refused. A trace is a handful of nodes,
# and the biggest one seen live was under 10 kB.
MAX_BYTES = 2_000_000

# Graphviz writes black in these spellings, and leaves text unfilled,
# which also draws black.
_BLACK = {None, "black", "#000000", "#000"}
_EMPTY = {"none", "transparent"}
_WHITE = {"white", "#ffffff", "#fff"}


def _tag(element: ET.Element) -> str:
    """Return a tag without its namespace."""
    return element.tag.rsplit("}", 1)[-1]


def _classes(element: ET.Element) -> set[str]:
    return set((element.get("class") or "").split())


def _lighten(element: ET.Element, attribute: str, colour: str) -> None:
    """Set a stroke or fill to the light colour when it is black or unset."""
    if element.get(attribute) in _BLACK:
        element.set(attribute, colour)


def _node_is_filled(node: ET.Element) -> bool:
    """Return true when a node draws a filled shape under its text."""
    for shape in node.iter():
        if _tag(shape) in {"ellipse", "polygon", "path", "rect"}:
            fill = shape.get("fill")
            if fill is not None and fill not in _EMPTY and fill not in _BLACK:
                return True
    return False


def recolour(svg: bytes) -> bytes:
    """Return a Graphviz SVG with its neutral colours made light.

    Raises `ValueError` when the input is not an SVG document.
    """
    if len(svg) > MAX_BYTES:
        raise ValueError("drawing is too large")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise ValueError(f"drawing is not XML: {exc}") from exc
    if _tag(root) != "svg":
        raise ValueError("drawing is not an SVG document")

    # The first polygon of the graph group is the page itself.
    for group in root.iter():
        if _tag(group) == "g" and "graph" in _classes(group):
            for child in group:
                if _tag(child) == "polygon":
                    child.set("fill", "none")
                    child.set("stroke", "none")
                    break
            break

    for group in root.iter():
        if _tag(group) != "g":
            continue
        classes = _classes(group)
        if "edge" in classes or "cluster" in classes:
            for part in group.iter():
                tag = _tag(part)
                if tag in {"path", "polygon", "ellipse"}:
                    _lighten(part, "stroke", LIGHT_LINE)
                    if tag == "polygon" and "edge" in classes:
                        _lighten(part, "fill", LIGHT_LINE)
                elif tag == "text":
                    _lighten(part, "fill", LIGHT_TEXT)
        elif "node" in classes:
            for part in group.iter():
                if _tag(part) in {"ellipse", "polygon", "path", "rect"}:
                    if (part.get("fill") or "").lower() in _WHITE:
                        part.set("fill", NODE_PLAIN)
            if not _node_is_filled(group):
                for part in group.iter():
                    if _tag(part) == "text":
                        _lighten(part, "fill", LIGHT_TEXT)

    # Loose text, such as a graph label, sits on the transparent page.
    for group in root.iter():
        if _tag(group) == "g" and "graph" in _classes(group):
            for child in group:
                if _tag(child) == "text":
                    _lighten(child, "fill", LIGHT_TEXT)

    body: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return body


async def fetch_trace_svg(settings: Settings, trace_key: int) -> bytes | None:
    """Fetch one trace drawing from mesh-graph over the internal network.

    None when mesh-graph holds no drawing for the trace. Network errors
    raise `httpx.HTTPError`, and the route turns them into a 502.
    """
    base = settings.mesh_graph_internal_url.rstrip("/")
    timeout = httpx.Timeout(settings.mesh_graph_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.get(f"{base}/graph/trace/{trace_key}", params={"format": "svg"})
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.content
