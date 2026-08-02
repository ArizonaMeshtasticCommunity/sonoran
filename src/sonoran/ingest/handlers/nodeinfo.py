"""NodeInfo packet storage."""

from typing import Any

from google.protobuf.message import Message
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import Node
from sonoran.ingest.handlers.context import HandlerContext


def _enum_name(message: Message, field_name: str) -> str | None:
    """Return an enum field name when it has a nonzero value."""
    field = message.DESCRIPTOR.fields_by_name[field_name]
    value = getattr(message, field_name)
    if not value:
        return None
    return field.enum_type.values_by_number[value].name


async def store_nodeinfo(session: AsyncSession, message: Message, context: HandlerContext) -> None:
    """Insert or update the latest node identity fields."""
    user: Any = message
    values = {
        "node_num": context.from_node_num,
        "node_id": user.id or f"!{context.from_node_num:08x}",
        "long_name": user.long_name or None,
        "short_name": user.short_name or None,
        "hw_model": _enum_name(message, "hw_model"),
        "role": _enum_name(message, "role"),
        "is_licensed": user.is_licensed,
        "public_key": bytes(user.public_key) or None,
        "first_seen": context.seen_at,
        "updated_at": context.seen_at,
    }
    statement = insert(Node).values(**values)
    statement = statement.on_conflict_do_update(
        index_elements=[Node.node_num],
        set_={key: value for key, value in values.items() if key not in {"node_num", "first_seen"}},
    )
    await session.execute(statement)
