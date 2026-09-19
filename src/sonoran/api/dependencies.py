"""Shared API dependencies."""

from collections.abc import AsyncIterator

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Yield a session from the API SELECT-only connection factory."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session


def parse_node_id(value: str) -> int:
    """Parse a documented node ID form to its integer value."""
    try:
        if value.startswith("!"):
            return int(value[1:], 16)
        text = value
        if text.startswith("0x"):
            return int(text, 16)
        if text.isdecimal():
            return int(text)
        return int(text, 16)
    except ValueError as exc:
        raise ValueError("invalid node ID") from exc


def require_node_num(value: str) -> int:
    """Parse a node ID, or answer 422 rather than raising into the handler.

    `parse_node_id` raises ValueError, which reaches a client as a 500
    unless somebody catches it. Three route modules each kept a private
    copy of this wrapper and four filter helpers called the bare parser,
    so whether a malformed node ID was a bad request or a server fault
    depended on which endpoint you asked.
    """
    try:
        return parse_node_id(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# The escape character for a LIKE pattern built from user input.
#
# `%` and `_` are wildcards. A search for `a_b` matched `axb`, which is
# wrong but harmless; a search for `%` matched every row in the table,
# which on a text hypertable this size is a full scan somebody can ask
# for from a public endpoint. Pass this as `escape=` wherever a pattern
# from `contains` is used.
LIKE_ESCAPE = "\\"


def contains(value: str) -> str:
    """Return a LIKE pattern matching `value` anywhere, wildcards literal."""
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"
