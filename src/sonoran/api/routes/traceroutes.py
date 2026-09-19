"""Read-only traceroute endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api.dependencies import get_session, require_node_num
from sonoran.api.names import format_node_id, name_of, resolve_names
from sonoran.api.traces import (
    Hop,
    evidenced_hops,
    forward_path,
    is_reply,
    return_path,
    trace_endpoints,
)
from sonoran.db.models import Traceroute


def _node_nums(trace: Traceroute) -> list[int]:
    """Return every node number that one traceroute mentions."""
    hops = [hop for hop in (trace.route or []) if isinstance(hop, int)]
    return [trace.from_node_num, trace.to_node_num, *hops]


router = APIRouter(prefix="/api/traceroutes", tags=["traceroutes"])


def _trace_key(trace: Traceroute) -> int | None:
    """Return the identity mesh-graph uses for one trace.

    Its ingest reads `decoded.get("requestId", packet.id)`, so a reply is
    keyed on the request it answers and everything else on its own
    packet ID.
    """
    return trace.request_id or trace.packet_id


def _named(hops: list[Hop], names: dict[int, dict[str, str | None]]) -> list[dict[str, object]]:
    """Return one chain of hops in the public form, with names filled in."""
    return [
        {
            "position": index + 1,
            "from_node": format_node_id(source),
            "from_name": name_of(names, source),
            "to_node": format_node_id(target),
            "to_name": name_of(names, target),
            "snr": snr,
        }
        for index, (source, target, snr) in enumerate(hops)
    ]


def _return_path(
    trace: Traceroute, names: dict[int, dict[str, str | None]]
) -> tuple[list[dict[str, object]], bool]:
    """Return the path the reply took, and whether it arrived.

    `snr_back` holds one reading per hop the reply has already made. It
    is one short of the full path, because the last hop to the node that
    asked had not happened when the broker saw the packet. Delivery is
    therefore not confirmed.
    """
    path = return_path(trace)
    if not path:
        return [], False
    hops, delivered = evidenced_hops(path, list(trace.snr_back or []))
    return _named(hops, names), delivered


def _hops(trace: Traceroute, names: dict[int, dict[str, str | None]]) -> list[dict[str, object]]:
    """Return the path of one traceroute as a chain of measured links.

    The chain always runs in the request direction, from the node that
    asked to the node that answered, whichever way the packet travelled.
    """
    hops, _ = evidenced_hops(forward_path(trace), list(trace.snr_towards or []))
    return _named(hops, names)


def _item(
    trace: Traceroute,
    graph_base_url: str,
    names: dict[int, dict[str, str | None]] | None = None,
) -> dict[str, object]:
    """Map a traceroute row to the public response."""
    names = names or {}
    return_hops, return_delivered = _return_path(trace, names)
    return {
        "id": trace.id,
        "packet_id": trace.packet_id,
        "channel": trace.channel,
        "hops": _hops(trace, names),
        "is_reply": is_reply(trace),
        # Endpoints in request order, so a reply reads the same way a
        # request does. The packet fields are kept below.
        "from_node": format_node_id(trace_endpoints(trace)[0]),
        "from_name": name_of(names, trace_endpoints(trace)[0]),
        "to_node": format_node_id(trace_endpoints(trace)[1]),
        "to_name": name_of(names, trace_endpoints(trace)[1]),
        "packet_from_node": format_node_id(trace.from_node_num),
        "packet_to_node": format_node_id(trace.to_node_num),
        "return_hops": return_hops,
        # A reply is caught while it travels, so the last hop back to
        # the node that asked is usually still to come.
        "return_delivered": return_delivered,
        "reply_reached": None if not return_hops else return_hops[-1]["to_name"],
        "route_names": [name_of(names, hop) for hop in (trace.route or []) if isinstance(hop, int)],
        "route": trace.route,
        "route_back": trace.route_back,
        "snr_towards": trace.snr_towards,
        "snr_back": trace.snr_back,
        "seen_at": trace.seen_at,
        "request_id": trace.request_id,
        # mesh-graph keys a trace on the request ID when the reply carries
        # one, and on the packet ID otherwise. Match that exactly.
        "graph_url": (
            None
            if _trace_key(trace) is None
            else f"{graph_base_url.rstrip('/')}/graph/trace/{_trace_key(trace)}?clickable=true"
        ),
        "node_graph_url": (
            f"{graph_base_url.rstrip('/')}/graph/node/!{trace.from_node_num:08x}?clickable=true"
        ),
    }


@router.get("")
async def list_traceroutes(
    request: Request,
    from_node: str | None = Query(default=None, alias="from"),
    to_node: str | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    """Return recent traceroutes newest first."""
    statement = select(Traceroute).order_by(Traceroute.seen_at.desc()).limit(limit)
    if from_node:
        statement = statement.where(Traceroute.from_node_num == require_node_num(from_node))
    if to_node:
        statement = statement.where(Traceroute.to_node_num == require_node_num(to_node))
    base_url = request.app.state.settings.mesh_graph_base_url
    rows = (await session.scalars(statement)).all()
    names = await resolve_names(session, [num for row in rows for num in _node_nums(row)])
    return [_item(row, base_url, names) for row in rows]


@router.get("/by-packet/{from_node}/{packet_id}")
async def traceroute_by_packet(
    from_node: str,
    packet_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return the traceroute that one packet carried.

    A packet page uses this to show the path without knowing the row ID
    of the traceroute.
    """
    try:
        from_num = require_node_num(from_node)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    trace = await session.scalar(
        select(Traceroute)
        .where(Traceroute.from_node_num == from_num, Traceroute.packet_id == packet_id)
        .order_by(Traceroute.seen_at.desc())
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="traceroute not found")
    names = await resolve_names(session, _node_nums(trace))
    return _item(trace, request.app.state.settings.mesh_graph_base_url, names)


@router.get("/{trace_id}")
async def get_traceroute(
    trace_id: int,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict[str, object]:
    """Return one traceroute."""
    trace = await session.scalar(
        select(Traceroute).where(Traceroute.id == trace_id).order_by(Traceroute.seen_at.desc())
    )
    if trace is None:
        raise HTTPException(status_code=404, detail="traceroute not found")
    names = await resolve_names(session, _node_nums(trace))
    return _item(trace, request.app.state.settings.mesh_graph_base_url, names)
