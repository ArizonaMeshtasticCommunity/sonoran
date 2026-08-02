"""Daily dashboard snapshot job."""

import asyncio
from datetime import UTC, datetime, time, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import get_settings
from sonoran.db.models import DailySnapshot, Node, Packet, PacketKey, PacketSeen, TextMessage
from sonoran.db.session import make_engine, make_session_factory
from sonoran.logging import configure_logging, get_logger

logger = get_logger(__name__)


async def prune_packet_keys(session: AsyncSession, now: datetime, retention_days: int) -> int:
    """Delete deduplication keys older than the packet retention window.

    `packet_key` is a plain table, so no TimescaleDB retention policy
    covers it. A key older than the packet window cannot match a new
    packet, because the packet itself is already gone.
    """
    cutoff = now - timedelta(days=retention_days)
    result = cast(
        "CursorResult[Any]",
        await session.execute(delete(PacketKey).where(PacketKey.first_seen_at < cutoff)),
    )
    return result.rowcount or 0


async def main() -> None:
    """Write or replace the UTC daily snapshot row."""
    settings = get_settings()
    engine = make_engine(settings.database_url_jobs)
    factory = make_session_factory(engine)
    now = datetime.now(UTC)
    try:
        async with factory() as session:
            statement = insert(DailySnapshot).values(
                day=now.date(),
                node_count=await session.scalar(select(func.count()).select_from(Node)),
                packet_count=await session.scalar(select(func.count()).select_from(Packet)),
                observation_count=await session.scalar(
                    select(func.count()).select_from(PacketSeen)
                ),
                gateway_count=await session.scalar(
                    select(func.count()).select_from(Node).where(Node.is_mqtt_gateway)
                ),
                text_count=await session.scalar(select(func.count()).select_from(TextMessage)),
                created_at=now,
            )
            statement = statement.on_conflict_do_update(
                index_elements=[DailySnapshot.day],
                set_={
                    "node_count": statement.excluded.node_count,
                    "packet_count": statement.excluded.packet_count,
                    "observation_count": statement.excluded.observation_count,
                    "gateway_count": statement.excluded.gateway_count,
                    "text_count": statement.excluded.text_count,
                    "created_at": statement.excluded.created_at,
                },
            )
            await session.execute(statement)
            removed = await prune_packet_keys(session, now, settings.retention_days_packet)
            await session.commit()
            if removed:
                logger.info("pruned %s expired packet keys", removed)
    finally:
        await engine.dispose()


def _delay_to_next_utc_day(now: datetime) -> float:
    """Return seconds until shortly after the next UTC day begins."""
    tomorrow = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)
    return max((tomorrow - now).total_seconds() + 5, 1)


async def service() -> None:
    """Write a snapshot once per UTC day."""
    while True:
        await main()
        await asyncio.sleep(_delay_to_next_utc_day(datetime.now(UTC)))


def run() -> None:
    """Console script entry point."""
    configure_logging(get_settings().log_level)
    asyncio.run(service())
