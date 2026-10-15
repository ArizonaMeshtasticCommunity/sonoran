"""`sonoran-contrib`: give jobs to contributors and keep what they send (#178).

It subscribes to every contributor's `inbox` and `status`, and it is the
only login that may publish to an `outbox`. Every tick it expires old
jobs, plans the jobs due now, publishes them, and clears the outbox
messages of finished jobs. One bad message must never stop it: each is
handled in its own transaction, and a failure is logged and counted.

It runs as `azmsh_jobs` with `DATABASE_URL_JOBS`. See
`docs/design/contributors.md` section 5.
"""

from __future__ import annotations

import asyncio
import json
import ssl
from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import aiomqtt
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sonoran.config import Settings, get_settings
from sonoran.contrib import store
from sonoran.contrib.dispatch import refuse_result
from sonoran.contrib.schema import (
    TOPIC_ROOT,
    Job,
    Result,
    Status,
    TopicError,
    job_topic,
    node_id,
    parse_topic,
)
from sonoran.db.session import make_engine, make_session_factory
from sonoran.logging import configure_logging, get_logger

logger = get_logger(__name__)

# How often the running totals are logged.
REPORT_EVERY = timedelta(seconds=60)
SUBSCRIPTIONS = (f"{TOPIC_ROOT}/+/+/inbox/+", f"{TOPIC_ROOT}/+/+/status")


def _client(settings: Settings) -> aiomqtt.Client:
    return aiomqtt.Client(
        hostname=settings.contrib_mqtt_host or settings.rf_mqtt_host or settings.mqtt_host,
        port=settings.contrib_mqtt_port,
        username=settings.contrib_mqtt_username or None,
        password=settings.contrib_mqtt_password or None,
        identifier=f"sonoran-contrib-{uuid4().hex}",
        protocol=aiomqtt.ProtocolVersion.V311,
        clean_session=True,
        keepalive=settings.mqtt_keepalive,
        tls_context=ssl.create_default_context() if settings.contrib_mqtt_use_tls else None,
    )


async def handle(
    session: AsyncSession,
    topic: str,
    payload: bytes,
    received: datetime,
    retained: bool,
    totals: Counter[str],
) -> None:
    """Check and store one message from a contributor."""
    try:
        parsed = parse_topic(topic)
        if parsed.box == "status":
            status = Status.model_validate(json.loads(payload))
            if (status.location, status.source) != parsed.contributor:
                raise ValueError("the heartbeat names another contributor")
            # A retained heartbeat may be days old: it was heard when sent.
            at = min(status.sent, received) if retained else received
            await store.store_status(session, parsed.contributor, status, at)
            totals["status"] += 1
            return
        if parsed.box != "inbox":
            raise TopicError(topic)
        result = Result.model_validate(json.loads(payload))
    except (TopicError, ValueError, ValidationError) as exc:
        totals["invalid"] += 1
        logger.info("drop invalid contributor message on %s: %s", topic, str(exc)[:200])
        return
    if result.job != parsed.job:
        totals["refused"] += 1
        logger.info("refuse result on %s: the topic names another job", topic)
        return
    reason = refuse_result(await store.job_facts(session, result.job), parsed.contributor, result)
    if reason is not None:
        totals["refused"] += 1
        logger.info("refuse result on %s: %s", topic, reason)
        return
    stored = await store.store_result(session, result, received)
    totals["reading" if stored else f"result_{result.outcome}"] += 1


async def tick(
    client: aiomqtt.Client,
    sessions: async_sessionmaker[AsyncSession],
    keep: timedelta,
    totals: Counter[str],
) -> None:
    """Expire, plan, publish and clear, once."""
    now = datetime.now(UTC)
    async with sessions() as session:
        totals["expired"] += await store.expire_jobs(session, now)
        planned = await store.plan_jobs(session, now)
        await store.prune(session, now, keep)
        await session.commit()
    for new in planned:
        job = Job(
            v=1,
            job=new.job,
            kind="local_stats",
            target=node_id(new.target),
            issued=new.issued,
            expires=new.expires,
        )
        await client.publish(
            job_topic("outbox", new.contributor, new.job),
            job.model_dump_json(),
            qos=1,
            retain=True,
        )
        totals["jobs"] += 1
    async with sessions() as session:
        cleared = await store.to_clear(session)
        for job_id, who in cleared:
            await client.publish(job_topic("outbox", who, job_id), b"", qos=1, retain=True)
        await store.mark_cleared(session, [job_id for job_id, _ in cleared])
        await session.commit()


async def _ticks(
    client: aiomqtt.Client,
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    totals: Counter[str],
) -> None:
    keep = timedelta(days=settings.retention_days_metric)
    while True:
        try:
            await tick(client, sessions, keep, totals)
        except aiomqtt.MqttError:
            raise
        except Exception:
            logger.exception("contributor tick failed")
        await asyncio.sleep(settings.contrib_tick_seconds)


async def main() -> None:
    """Run `sonoran-contrib`."""
    settings = get_settings()
    engine = make_engine(settings.database_url_jobs)
    sessions = make_session_factory(engine)
    totals: Counter[str] = Counter()
    reported = datetime.now(UTC)
    delay = 1
    try:
        while True:
            try:
                async with _client(settings) as client:
                    for topic in SUBSCRIPTIONS:
                        await client.subscribe(topic, qos=1)
                    delay = 1
                    ticks = asyncio.create_task(_ticks(client, sessions, settings, totals))
                    try:
                        async for message in client.messages:
                            received = datetime.now(UTC)
                            async with sessions() as session:
                                try:
                                    await handle(
                                        session,
                                        str(message.topic),
                                        bytes(message.payload),
                                        received,
                                        bool(message.retain),
                                        totals,
                                    )
                                    await session.commit()
                                except Exception:
                                    await session.rollback()
                                    totals["failed"] += 1
                                    logger.exception("failed to store %s", message.topic)
                            if received - reported >= REPORT_EVERY:
                                logger.info("contrib, last minute: %s", dict(totals))
                                totals.clear()
                                reported = received
                    finally:
                        ticks.cancel()
            except aiomqtt.MqttError as exc:
                logger.warning("contrib broker connection failed: %s; retry in %s s", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
    finally:
        await engine.dispose()


def run() -> None:
    """Console script entry point."""
    configure_logging(get_settings().log_level)
    asyncio.run(main())
