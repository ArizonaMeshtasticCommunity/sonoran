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
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.config import Settings, get_settings
from sonoran.db.session import make_engine, make_session_factory
from sonoran.logging import configure_logging, get_logger
from sonoran.rf.guard import Guard, Limits, parse_refused
from sonoran.rf.schema import (
    Batch,
    Custom,
    Registry,
    Spectrum,
    Status,
    TopicError,
    parse_topic,
)
from sonoran.rf.store import (
    Rules,
    range_key,
    spectrum_minute,
    store_batch,
    store_custom,
    store_registry,
    store_spectrum,
    store_status,
)

logger = get_logger(__name__)

# How often the running totals are logged.
REPORT_EVERY = timedelta(seconds=60)
# An invalid message is logged once per station in this time; the rest
# are counted. One broken agent must not fill the log (#324).
INVALID_LOG_EVERY = timedelta(hours=1)


def rules_from(settings: Settings) -> Rules:
    """Return the writer's rules from the settings."""
    return Rules(
        bucket=timedelta(seconds=settings.rf_bucket_seconds),
        future_slack=timedelta(seconds=settings.rf_future_slack_seconds),
        past_slack=timedelta(seconds=settings.rf_past_slack_seconds),
        hidden=frozenset(item.lower() for item in settings.rf_hidden_ids),
        ism_allow=frozenset(item.strip().lower() for item in settings.rf_ism_allow),
    )


def limits_from(settings: Settings) -> Limits:
    """Return the per-station limits from the settings."""
    return Limits(
        messages_per_minute=settings.rf_quota_messages_per_minute,
        messages_burst=settings.rf_quota_messages_burst,
        points_per_minute=settings.rf_quota_points_per_minute,
        points_burst=settings.rf_quota_points_burst,
        spectrum_max_ranges=settings.rf_spectrum_max_ranges,
        spectrum_max_bins=settings.rf_spectrum_max_bins,
        refused=tuple(parse_refused(spec) for spec in settings.rf_spectrum_refused_ranges),
        custom_per_minute=settings.rf_custom_points_per_minute,
        custom_burst=settings.rf_custom_points_burst,
        custom_max_ids=settings.rf_custom_max_ids,
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


async def _messages(settings: Settings) -> AsyncIterator[tuple[str, bytes, bool]]:
    """Yield (topic, payload, retained), reconnecting after a broker error.

    `retained` is true for a message the broker replays on subscribe,
    such as a station's last heartbeat, possibly long after it was sent.
    """
    delay = 1
    while True:
        try:
            async with _client(settings) as client:
                for topic in settings.rf_topics:
                    await client.subscribe(topic)
                delay = 1
                async for message in client.messages:
                    yield str(message.topic), bytes(message.payload), bool(message.retain)
        except aiomqtt.MqttError as exc:
            logger.warning("RF broker connection failed: %s; retry in %s seconds", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


def heard_at(status: Status, received: datetime, retained: bool) -> datetime:
    """When a heartbeat says its station was last heard.

    A live heartbeat is heard when it arrives. A retained one is the
    broker replaying the last heartbeat, perhaps of a station revoked or
    dead for days: it was heard when it was sent, never later than now.
    Taking the arrival time would show a dead station as online after
    every ingest restart.
    """
    return min(status.sent, received) if retained else received


class Removed:
    """An empty retained registry message: the location left the registry."""

    def __init__(self, station: str) -> None:
        self.station = station


Message = Batch | Status | Spectrum | Custom | Registry | Removed


def decode(topic: str, payload: bytes) -> Message:
    """Parse and validate one message.

    Raises `TopicError` or `ValueError` for a message that is not one. A
    message must name the station its topic names: the broker already
    lets a station publish only to its own topic, and this checks it
    again rather than trust one control. A heartbeat must name the
    source its topic names, for the same reason (#305).
    """
    station, kind, source = parse_topic(topic)
    if kind == "registry" and not payload:
        return Removed(station)
    data = json.loads(payload)
    message: Batch | Status | Spectrum | Custom | Registry
    if kind == "status":
        message = Status.model_validate(data)
        if message.source != source:
            raise ValueError(f"heartbeat names source {message.source!r} on the {source!r} topic")
    elif kind == "spectrum":
        message = Spectrum.model_validate(data)
    elif kind == "custom":
        message = Custom.model_validate(data)
    elif kind == "registry":
        message = Registry.model_validate(data)
    else:
        message = Batch.model_validate(data)
    if message.station != station:
        raise ValueError(f"message names station {message.station!r} on {station!r}'s topic")
    if isinstance(message, Batch) and message.kind != kind:
        raise ValueError(f"message of kind {message.kind!r} on the {kind!r} topic")
    return message


class InvalidLog:
    """Log an invalid message once per station an hour; count the rest."""

    def __init__(self, every: timedelta = INVALID_LOG_EVERY) -> None:
        self.every = every
        self._last: dict[str, datetime] = {}
        self._skipped: Counter[str] = Counter()

    def note(self, topic: str, error: str, now: datetime) -> bool:
        """Record one invalid message. True when it was logged."""
        parts = topic.split("/")
        who = parts[2] if len(parts) > 2 else topic
        last = self._last.get(who)
        if last is not None and now - last < self.every:
            self._skipped[who] += 1
            return False
        skipped = self._skipped.pop(who, 0)
        more = f" ({skipped} more since the last line)" if skipped else ""
        logger.info("drop invalid RF message on %s: %s%s", topic, error[:200], more)
        self._last[who] = now
        return True


async def handle(
    session: AsyncSession,
    message: Message,
    received: datetime,
    retained: bool,
    rules: Rules,
    guard: Guard,
    totals: Counter[str],
) -> None:
    """Store one decoded message, counting what happened in `totals`."""
    if isinstance(message, Removed):
        await store_registry(session, message.station, None, received)
        totals["registry"] += 1
    elif isinstance(message, Registry):
        await store_registry(session, message.station, message, received)
        totals["registry"] += 1
    elif not retained and not guard.allow_message(message.station, received):
        # The registry comes from the registrar alone, and a retained
        # message is the broker replaying one on connect: neither is a
        # station sending more than its share.
        totals["over_quota"] += 1
    elif isinstance(message, Status):
        await store_status(session, message, heard_at(message, received, retained), guard)
        totals["status"] += 1
    elif isinstance(message, Spectrum):
        refused = guard.allow_spectrum(
            message.station,
            range_key(message),
            message.f_start_hz,
            len(message.p95),
            message.bin_hz,
            spectrum_minute(message, received, rules),
            received,
        )
        if refused is not None:
            totals["spectrum_refused"] += 1
            return
        new = await store_spectrum(session, message, received, rules)
        totals["spectrum" if new else "spectrum_repeat"] += 1
    elif isinstance(message, Custom):
        tally = await store_custom(session, message, received, rules, guard)
        totals["custom"] += tally.stored
        totals["custom_rejected"] += tally.rejected
        totals["over_quota"] += tally.over_quota
    else:
        tally = await store_batch(session, message, received, rules, guard)
        totals["stored"] += tally.stored
        totals["retimed"] += tally.retimed
        totals["hidden"] += tally.hidden
        totals["not_allowed"] += tally.not_allowed
        totals["relayed"] += tally.relayed
        totals["rejected"] += tally.rejected
        totals["kind_not_stored"] += tally.kind_not_stored
        totals["doubtful"] += tally.doubtful
        totals["withheld"] += tally.withheld
        totals["over_quota"] += tally.over_quota


async def main() -> None:
    """Run the RF ingest loop."""
    settings = get_settings()
    rules = rules_from(settings)
    guard = Guard(limits_from(settings))
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    totals: Counter[str] = Counter()
    invalid = InvalidLog()
    reported = datetime.now(UTC)
    trust_every = timedelta(seconds=settings.rf_trust_refresh_seconds)
    trust_read: datetime | None = None
    try:
        async for topic, payload, retained in _messages(settings):
            received = datetime.now(UTC)
            if trust_read is None or received - trust_read >= trust_every:
                trust_read = received
                try:
                    async with session_factory() as session:
                        await guard.refresh(session)
                except Exception:
                    # The last levels read stay in force.
                    logger.exception("could not read the RF trust levels")
            try:
                message = decode(topic, payload)
            except (TopicError, ValueError, ValidationError) as exc:
                totals["invalid"] += 1
                invalid.note(topic, str(exc), received)
                continue
            async with session_factory() as session:
                try:
                    await handle(session, message, received, retained, rules, guard, totals)
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
