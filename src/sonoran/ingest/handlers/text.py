"""Text message packet storage."""

from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.db.models import TextMessage
from sonoran.decode.payloads import TextPayload
from sonoran.ingest.handlers.context import HandlerContext


async def store_text(session: AsyncSession, payload: TextPayload, context: HandlerContext) -> None:
    """Store a text body when the privacy switch permits it."""
    if not context.store_text_messages:
        return
    session.add(
        TextMessage(
            packet_pk=context.packet_pk,
            packet_id=context.packet_id,
            from_node_num=context.from_node_num,
            to_node_num=context.to_node_num or 0,
            channel=context.channel,
            body=payload.body,
            reply_id=context.reply_id,
            emoji=context.emoji,
            seen_at=context.seen_at,
        )
    )
