"""Recover packets that were stored as unreadable but can be read now (#252).

From 2026-09-23 22:43 UTC, every packet from a node that signs its traffic
was decrypted correctly and then filed as ``no_key``. The vendored schema
did not know ``Data`` field 10 (``xeddsa_signature``), so the known fields
no longer re-serialised to the input and ``_valid_data`` refused them. The
schema is fixed; this puts the packets already refused back where they
belong.

Nothing was lost. Ingest keeps an unreadable packet as traffic, with its
original ``raw_bytes``, precisely so that "a schema bump plus a backfill
recovers them" -- the remedy the stricter check's own commit named. This is
that backfill.

**It reuses the live path, it does not re-implement it.** A recovered
packet is decrypted by ``decrypt_packet`` with the same ``_valid_data``
validator, decoded by ``decode_payload``, and stored by ``store_payload``
with the same ``HandlerContext`` the live pipeline builds. So recovered
telemetry lands exactly as live telemetry would have, and a later change to
any of those functions applies here too.

**It recovers only what now validates.** A ``no_key`` row that still fails
is genuinely on a channel this instance holds no key for, and it stays
``no_key``. The report says how many of each.

**Dry run by default.** It reports what it would recover, by port, and
writes nothing unless ``--apply`` is given.

**One savepoint per packet.** A packet whose payload a handler rejects is
rolled back on its own and counted, rather than losing the batch.

Not recovered: ``mesh_packet_metrics``. The live path computes it from the
MQTT message, including its size on the wire, which was not stored. The
per-packet radio figures for the recovered window stay missing; the
telemetry, positions, NodeInfo and messages -- what a reader sees -- come
back.

**Run it as the migration role, not as ingest.** The ingest image has the
keys and the code, but ``azmsh_ingest`` is write-only by design: it holds
INSERT and UPDATE on ``packet`` and no SELECT, so this job's reads, and the
``WHERE`` of its update, are refused. Widening that role for a one-off
would weaken it for good. Instead run a throwaway container from the
ingest image with ``DATABASE_URL`` pointed at the role migrations use,
the same host and database, with the ``postgresql+asyncpg`` scheme::

    docker compose run --rm --no-deps -T -e DATABASE_URL=<migration role URL> \
        ingest python -m sonoran.ingest.recover --since 2026-09-23T22:00:00Z
    ... --apply

Take a dump first. On production, 2026-09-27, it recovered 1,832 packets
and left 1,214 ``no_key``, the rate the fixed ingest rejects live; a second
run recovered nothing.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import get_settings
from sonoran.crypto.decrypt import DecryptionError, decode_key, decrypt_packet
from sonoran.db.models import Packet
from sonoran.db.session import make_engine, make_session_factory
from sonoran.decode.payload_state import PayloadState
from sonoran.decode.payloads import decode_payload, parse_data
from sonoran.decode.stored import stored_payload
from sonoran.ingest.handlers import HandlerContext, store_payload
from sonoran.ingest.pipeline import _valid_data
from sonoran.logging import configure_logging, get_logger
from sonoran.meshtastic import mesh_pb2

logger = get_logger(__name__)

#: How many rows are read per query. Bounded so a long window cannot pull
#: the whole backlog into memory at once.
BATCH = 500


async def recover(
    session: AsyncSession,
    keys: list[bytes],
    since: datetime,
    *,
    apply: bool,
    store_text_messages: bool,
    mesh_future_slack_seconds: int = 300,
) -> Counter[str]:
    """Try every ``no_key`` packet since ``since``; return what happened.

    The counter's keys are ``recovered:<portnum>``, ``still_no_key``,
    ``not_encrypted``, ``unparseable`` and ``handler_failed``. With
    ``apply`` false nothing is written, and ``recovered:*`` counts what
    would have been.
    """
    counts: Counter[str] = Counter()
    last_id = 0
    while True:
        rows = (
            (
                await session.execute(
                    select(Packet)
                    .where(
                        Packet.payload_state == PayloadState.NO_KEY.value,
                        Packet.first_seen_at >= since,
                        Packet.id > last_id,
                    )
                    .order_by(Packet.id)
                    .limit(BATCH)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return counts
        for row in rows:
            last_id = row.id
            await _recover_one(
                session,
                row,
                keys,
                counts,
                apply=apply,
                store_text_messages=store_text_messages,
                mesh_future_slack_seconds=mesh_future_slack_seconds,
            )


async def _recover_one(
    session: AsyncSession,
    row: Packet,
    keys: list[bytes],
    counts: Counter[str],
    *,
    apply: bool,
    store_text_messages: bool,
    mesh_future_slack_seconds: int,
) -> None:
    if not row.raw_bytes:
        counts["unparseable"] += 1
        return
    packet = mesh_pb2.MeshPacket()  # type: ignore[attr-defined]
    try:
        packet.ParseFromString(row.raw_bytes)
    except Exception:  # a stored row we cannot parse is counted, not fatal
        counts["unparseable"] += 1
        return
    if not packet.encrypted:
        counts["not_encrypted"] += 1
        return
    try:
        plaintext, _ = decrypt_packet(
            packet.encrypted, packet.id, row.from_node_num, keys, validator=_valid_data
        )
    except DecryptionError:
        counts["still_no_key"] += 1
        return

    data = parse_data(plaintext)
    decoded = decode_payload(data.portnum, data.payload)
    counts[f"recovered:{decoded.portnum}"] += 1
    if not apply:
        return

    try:
        async with session.begin_nested():
            await session.execute(
                update(Packet)
                .where(Packet.id == row.id, Packet.first_seen_at == row.first_seen_at)
                .values(
                    portnum=decoded.portnum,
                    payload_state=PayloadState.READABLE.value,
                    payload_json=stored_payload(decoded),
                )
            )
            await store_payload(
                session,
                decoded,
                HandlerContext(
                    packet_pk=row.id,
                    packet_id=row.packet_id,
                    request_id=data.request_id or None,
                    from_node_num=row.from_node_num,
                    to_node_num=row.to_node_num,
                    channel=row.channel,
                    reply_id=data.reply_id or None,
                    emoji=bool(data.emoji),
                    store_text_messages=store_text_messages,
                    seen_at=row.first_seen_at,
                    mesh_future_slack_seconds=mesh_future_slack_seconds,
                ),
            )
    except Exception:  # one packet's failure must not lose the batch
        logger.exception("could not store recovered packet %s", row.id)
        counts[f"recovered:{decoded.portnum}"] -= 1
        counts["handler_failed"] += 1


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--since",
        required=True,
        type=datetime.fromisoformat,
        help="only packets first seen at or after this ISO 8601 time, with its zone",
    )
    parser.add_argument("--apply", action="store_true", help="write; without it, only report")
    args = parser.parse_args(argv)
    if args.since.tzinfo is None:
        parser.error("--since needs a time zone, for example 2026-09-23T22:00:00Z")

    settings = get_settings()
    keys = [decode_key(key) for key in settings.channel_keys]
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    try:
        async with session_factory() as session:
            counts = await recover(
                session,
                keys,
                args.since,
                apply=args.apply,
                store_text_messages=settings.store_text_messages,
                mesh_future_slack_seconds=settings.mesh_future_slack_seconds,
            )
            if args.apply:
                await session.commit()
            else:
                await session.rollback()
    finally:
        await engine.dispose()

    verb = "recovered" if args.apply else "would recover"
    recovered = sum(v for k, v in counts.items() if k.startswith("recovered:"))
    print(f"{verb} {recovered} packet(s) since {args.since.isoformat()}")
    for key in sorted(counts):
        print(f"  {key:22} {counts[key]}")
    return 0


if __name__ == "__main__":
    configure_logging(get_settings().log_level)
    raise SystemExit(asyncio.run(main()))
