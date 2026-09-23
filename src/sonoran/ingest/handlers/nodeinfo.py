"""NodeInfo packet storage."""

from typing import Any

from google.protobuf.message import Message
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import Node
from sonoran.ingest.handlers.context import HandlerContext


def _enum_name(message: Message, field_name: str) -> str | None:
    """Return an enum field name when it has a nonzero value.

    A value the compiled proto does not know is treated as unknown, not
    as an error. Newer firmware reports newer hardware models and roles
    than the vendored descriptors carry, and one of those must drop a
    single field, never the whole nodeinfo packet.

    Zero is None here, which is right for `hw_model` -- `UNSET` really
    does mean the node reported no hardware. It is **wrong for `role`**,
    where zero is `CLIENT`, so roles go through `_role_name` instead.
    See #197 and AGENTS.md 9.22.
    """
    field = message.DESCRIPTOR.fields_by_name[field_name]
    value = getattr(message, field_name)
    if not value:
        return None
    entry = field.enum_type.values_by_number.get(value)
    return entry.name if entry is not None else None


def _role_name(message: Message) -> str:
    """Return the role this User message reports. Never None (#197).

    `CLIENT` is zero, and proto3 gives a scalar no presence, so a User
    message that sets no role is byte-identical to one that sets
    `CLIENT`. That is not a loss, because they mean the same thing:
    `config.proto` calls `CLIENT` the "Default Role", so a node that
    named no role is a client. **Receiving the message is the evidence**
    -- whatever it says about the role, we heard the node introduce
    itself, so the answer is never "unknown".

    This used to run through `_enum_name`, where zero is falsy and came
    back NULL. A client and a node that had never said a word were then
    stored identically, and the live map drew 167 of the commonest kind
    of node on the mesh in the grey it uses for "no role reported".

    A role number this vendored proto does not know keeps its digits
    rather than becoming NULL. Firmware ships roles faster than this
    repository vendors them -- role 12 is already in the wild -- and
    turning one into NULL would feed it straight back into the bug this
    function exists to fix.
    """
    field = message.DESCRIPTOR.fields_by_name["role"]
    value = message.role
    entry = field.enum_type.values_by_number.get(value)
    return entry.name if entry is not None else f"ROLE_{value}"


async def store_nodeinfo(session: AsyncSession, message: Message, context: HandlerContext) -> None:
    """Insert or update the latest node identity fields."""
    user: Any = message
    values = {
        "node_num": context.from_node_num,
        "node_id": user.id or f"!{context.from_node_num:08x}",
        "long_name": user.long_name or None,
        "short_name": user.short_name or None,
        "hw_model": _enum_name(message, "hw_model"),
        # Never NULL: a node that introduced itself has a role, and
        # zero is CLIENT rather than silence (#197).
        "role": _role_name(message),
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
