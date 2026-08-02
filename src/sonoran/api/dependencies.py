"""Shared API dependencies."""

from collections.abc import AsyncIterator

from fastapi import Request
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
