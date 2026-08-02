"""Node display names.

Most tables store a node number only. The user interface must show a
readable name. This module resolves many node numbers in one query.

The rules for a display name are:

1. Use the long name when the node reports one.
2. If there is no long name, use the short name.
3. If there is no name at all, use the node ID.
"""

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import Node

BROADCAST_NODE_NUM = 0xFFFFFFFF
BROADCAST_ID = "^all"
BROADCAST_NAME = "Everyone"


def format_node_id(value: int | None) -> str:
    """Return the documented ID form of a node number."""
    if value is None or value == BROADCAST_NODE_NUM:
        return BROADCAST_ID
    return f"!{value:08x}"


def display_name(
    value: int | None, long_name: str | None = None, short_name: str | None = None
) -> str:
    """Return the best readable name for one node."""
    if value is None or value == BROADCAST_NODE_NUM:
        return BROADCAST_NAME
    for name in (long_name, short_name):
        if name and name.strip():
            return name.strip()
    return format_node_id(value)


async def resolve_names(
    session: AsyncSession, node_nums: Iterable[int | None]
) -> dict[int, dict[str, str | None]]:
    """Return name records for the given node numbers.

    The result maps a node number to its ID, long name, short name, and
    display name. Unknown nodes are included with the ID as the name.
    """
    wanted = {num for num in node_nums if num is not None and num != BROADCAST_NODE_NUM}
    if not wanted:
        return {}
    rows = await session.execute(
        select(Node.node_num, Node.long_name, Node.short_name).where(Node.node_num.in_(wanted))
    )
    known = {num: (long_name, short_name) for num, long_name, short_name in rows.all()}
    return {
        num: {
            "node_id": format_node_id(num),
            "long_name": known.get(num, (None, None))[0],
            "short_name": known.get(num, (None, None))[1],
            "display_name": display_name(num, *known.get(num, (None, None))),
        }
        for num in wanted
    }


def name_of(names: dict[int, dict[str, str | None]], value: int | None) -> str:
    """Return the display name for one node from a resolved name map."""
    if value is None or value == BROADCAST_NODE_NUM:
        return BROADCAST_NAME
    record = names.get(value)
    if record is None:
        return format_node_id(value)
    return record["display_name"] or format_node_id(value)
