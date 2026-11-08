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

A node of the drawing still links to its node page (beta-sonoran#405).
`node_boxes` reads where each node is drawn, as fractions of the
picture, and the page lays an ordinary `<a href>` over each box. The SVG
itself is never put into the page.
"""

from __future__ import annotations

import re
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


# A node's <title> is its id, `!` and eight hex digits. The title is
# third-party text that ends up in an href, so nothing else is accepted.
_NODE_ID = re.compile(r"^![0-9a-f]{8}$")
_NUMBER = r"(-?[0-9.]+)"
_SCALE = re.compile(rf"scale\({_NUMBER}(?:[ ,]+{_NUMBER})?\)")
_ROTATE = re.compile(rf"rotate\({_NUMBER}\)")
_TRANSLATE = re.compile(rf"translate\({_NUMBER}[ ,]+{_NUMBER}\)")


def _graph_transform(transform: str) -> tuple[float, float, float, float] | None:
    """Return (sx, sy, tx, ty) of a Graphviz graph group, or None.

    Graphviz writes `scale(s s) rotate(0) translate(tx ty)`, so a point
    is first moved and then scaled. A real rotation is refused: links put
    in the wrong place are worse than no links.
    """
    rotate = _ROTATE.search(transform)
    if rotate and float(rotate.group(1)) % 360 != 0:
        return None
    scale = _SCALE.search(transform)
    sx = float(scale.group(1)) if scale else 1.0
    sy = float(scale.group(2)) if scale and scale.group(2) else sx
    move = _TRANSLATE.search(transform)
    tx, ty = (float(move.group(1)), float(move.group(2))) if move else (0.0, 0.0)
    return sx, sy, tx, ty


def _shape_points(shape: ET.Element) -> list[tuple[float, float]]:
    """Return the corner points of an ellipse or a polygon."""
    tag = _tag(shape)
    if tag == "ellipse":
        cx, cy = float(shape.get("cx", 0)), float(shape.get("cy", 0))
        rx, ry = float(shape.get("rx", 0)), float(shape.get("ry", 0))
        return [(cx - rx, cy - ry), (cx + rx, cy + ry)]
    if tag == "polygon":
        numbers = [float(n) for n in re.findall(r"-?[0-9.]+", shape.get("points", ""))]
        return list(zip(numbers[0::2], numbers[1::2], strict=False))
    return []


def node_boxes(svg: bytes) -> list[dict[str, object]]:
    """Return where each node of a drawing is, as fractions of the picture.

    Each item is `node_id`, `x`, `y`, `w`, `h`, from 0 to 1 of the
    viewBox. A node whose title is not a node id, or a drawing whose
    layout this cannot read, gives no box. Raises `ValueError` when the
    input is not an SVG document.
    """
    if len(svg) > MAX_BYTES:
        raise ValueError("drawing is too large")
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        raise ValueError(f"drawing is not XML: {exc}") from exc
    if _tag(root) != "svg":
        raise ValueError("drawing is not an SVG document")
    try:
        _, _, width, height = (float(n) for n in root.get("viewBox", "").split())
    except ValueError:
        return []
    graph = next(
        (g for g in root.iter() if _tag(g) == "g" and "graph" in _classes(g)),
        None,
    )
    if graph is None or width <= 0 or height <= 0:
        return []
    transform = _graph_transform(graph.get("transform", ""))
    if transform is None:
        return []
    sx, sy, tx, ty = transform
    boxes: list[dict[str, object]] = []
    for group in graph.iter():
        if _tag(group) != "g" or "node" not in _classes(group):
            continue
        title = next((t.text for t in group if _tag(t) == "title"), None)
        node_id = (title or "").strip()
        if not _NODE_ID.match(node_id):
            continue
        points = [p for shape in group.iter() for p in _shape_points(shape)]
        if not points:
            continue
        xs = [sx * (x + tx) for x, _ in points]
        ys = [sy * (y + ty) for _, y in points]
        boxes.append(
            {
                "node_id": node_id,
                "x": min(xs) / width,
                "y": min(ys) / height,
                "w": (max(xs) - min(xs)) / width,
                "h": (max(ys) - min(ys)) / height,
            }
        )
    return boxes


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
