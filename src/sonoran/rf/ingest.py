"""`sonoran-rf-ingest`: store what `rf-agent` stations publish.

It subscribes to `rf/v1/#`, validates each message against
`sonoran/rf/schema.py`, and writes it with `sonoran/rf/store.py`. One
bad message, or one bad station, must never stop it: every message is
handled in its own transaction, and a failure is logged and counted.

It runs as `azmsh_ingest` with `DATABASE_URL`. See the design, 5.1.
"""

from __future__ import annotations

import asyncio
import json
import ssl
from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import aiomqtt
from pydantic import ValidationError

from sonoran.config import Settings, get_settings
from sonoran.db.session import make_engine, make_session_factory
from sonoran.logging import configure_logging, get_logger
from sonoran.rf.schema import Batch, Status, TopicError, parse_topic
from sonoran.rf.store import Rules, store_batch, store_status

logger = get_logger(__name__)

# How often the running totals are logged.
REPORT_EVERY = timedelta(seconds=60)


def rules_from(settings: Settings) -> Rules:
    """Return the writer's rules from the settings."""
    return Rules(
        bucket=timedelta(seconds=settings.rf_bucket_seconds),
        future_slack=timedelta(seconds=settings.rf_future_slack_seconds),
        past_slack=timedelta(seconds=settings.rf_past_slack_seconds),
        hidden=frozenset(item.lower() for item in settings.rf_hidden_ids),
    )


def _client(settings: Settings) -> aiomqtt.Client:
    return aiomqtt.Client(
        hostname=settings.rf_mqtt_host or settings.mqtt_host,
        port=settings.rf_mqtt_port,
        username=settings.rf_mqtt_username or None,
        password=settings.rf_mqtt_password or None,
        identifier=f"sonoran-rf-{uuid4().hex}",
        protocol=aiomqtt.ProtocolVersion.V311,
        clean_session=True,
        keepalive=settings.mqtt_keepalive,
        tls_context=ssl.create_default_context() if settings.rf_mqtt_use_tls else None,
    )


async def _messages(settings: Settings) -> AsyncIterator[tuple[str, bytes]]:
    """Yield (topic, payload), reconnecting after a broker error."""
    delay = 1
    while True:
        try:
            async with _client(settings) as client:
                for topic in settings.rf_topics:
                    await client.subscribe(topic)
                delay = 1
                async for message in client.messages:
                    yield str(message.topic), bytes(message.payload)
        except aiomqtt.MqttError as exc:
            logger.warning("RF broker connection failed: %s; retry in %s seconds", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


def decode(topic: str, payload: bytes) -> Batch | Status:
    """Parse and validate one message.

    Raises `TopicError` or `ValueError` for a message that is not one. A
    message must name the station its topic names: the broker already
    lets a station publish only to its own topic, and this checks it
    again rather than trust one control.
    """
    station, kind = parse_topic(topic)
    data = json.loads(payload)
    message: Batch | Status = (
        Status.model_validate(data) if kind == "status" else Batch.model_validate(data)
    )
    if message.station != station:
        raise ValueError(f"message names station {message.station!r} on {station!r}'s topic")
    if isinstance(message, Batch) and message.kind != kind:
        raise ValueError(f"message of kind {message.kind!r} on the {kind!r} topic")
    return message


async def main() -> None:
    """Run the RF ingest loop."""
    settings = get_settings()
    rules = rules_from(settings)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    totals: Counter[str] = Counter()
    reported = datetime.now(UTC)
    try:
        async for topic, payload in _messages(settings):
            received = datetime.now(UTC)
            try:
                message = decode(topic, payload)
            except (TopicError, ValueError, ValidationError) as exc:
                totals["invalid"] += 1
                logger.info("drop invalid RF message on %s: %s", topic, str(exc)[:200])
                continue
            async with session_factory() as session:
                try:
                    if isinstance(message, Status):
                        await store_status(session, message, received)
                        totals["status"] += 1
                    else:
                        tally = await store_batch(session, message, received, rules)
                        totals["stored"] += tally.stored
                        totals["retimed"] += tally.retimed
                        totals["hidden"] += tally.hidden
                        totals["rejected"] += tally.rejected
                        totals["kind_not_stored"] += tally.kind_not_stored
                    await session.commit()
                except Exception:
                    await session.rollback()
                    totals["failed"] += 1
                    logger.exception("failed to store RF message on %s", topic)
            if received - reported >= REPORT_EVERY:
                logger.info("rf ingest, last minute: %s", dict(totals))
                totals.clear()
                reported = received
    finally:
        await engine.dispose()


def run() -> None:
    """Console script entry point."""
    configure_logging(get_settings().log_level)
    asyncio.run(main())
