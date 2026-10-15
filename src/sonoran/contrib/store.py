"""The database side of `sonoran-contrib` (#178).

Every function takes a session and leaves the commit to the caller, so
one message or one tick is one transaction. See
`docs/design/contributors.md` section 5.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.contrib.dispatch import (
    JOB_WAIT,
    TARGET_ROLES,
    Candidate,
    JobFacts,
    interval_for_role,
    next_job,
)
from sonoran.contrib.schema import Contributor as Who
from sonoran.contrib.schema import LocalStats, Result, Status, node_num
from sonoran.db.models import (
    ContribHeard,
    ContribJob,
    ContribSource,
    LocalStatsMetrics,
    Node,
)

# The one job kind so far.
KIND = "local_stats"
# A job's outcome when no result came before it expired.
EXPIRED = "expired"
# The outcomes a contributor sends. A job with one of these has a result.
RESULT_OUTCOMES = frozenset({"ok", "no_reply", "refused", "error"})


@dataclass(frozen=True)
class NewJob:
    """A job to publish."""

    job: str
    contributor: Who
    target: int
    issued: datetime
    expires: datetime


async def store_status(session: AsyncSession, who: Who, status: Status, received: datetime) -> None:
    """Keep a contributor's last heartbeat and replace its heard list."""
    values = {
        "sent": status.sent,
        "received_at": received,
        "version": status.version,
        "mesh_node": node_num(status.mesh_node) if status.mesh_node else None,
        "kinds": list(dict.fromkeys(status.kinds)),
    }
    await session.execute(
        pg_insert(ContribSource)
        .values(location=who.location, source=who.source, **values)
        .on_conflict_do_update(index_elements=["location", "source"], set_=values)
    )
    await session.execute(
        delete(ContribHeard).where(
            ContribHeard.location == who.location, ContribHeard.source == who.source
        )
    )
    # One row per node: the most recently heard entry wins.
    latest: dict[int, tuple[int | None, datetime]] = {}
    for item in status.heard:
        num = node_num(item.node)
        # A node list entry from the future is the contributor's clock.
        heard = min(item.last_heard, received)
        if num not in latest or heard > latest[num][1]:
            latest[num] = (item.hops, heard)
    if latest:
        await session.execute(
            insert(ContribHeard),
            [
                {
                    "location": who.location,
                    "source": who.source,
                    "node_num": num,
                    "hops": hops,
                    "last_heard": heard,
                }
                for num, (hops, heard) in latest.items()
            ],
        )


async def job_facts(session: AsyncSession, job: str) -> JobFacts | None:
    """What Sonoran wrote about one job, or None."""
    row = await session.get(ContribJob, job)
    if row is None:
        return None
    return JobFacts(
        job=row.job,
        contributor=Who(row.location, row.source),
        kind=row.kind,
        target=row.target,
        has_result=row.outcome in RESULT_OUTCOMES,
    )


async def store_result(session: AsyncSession, result: Result, received: datetime) -> bool:
    """Record an accepted result. True when it stored a reading.

    Check it with `dispatch.refuse_result` first. A late result for an
    expired job is still a real reading.
    """
    job = await session.get(ContribJob, result.job)
    if job is None:
        raise ValueError(f"no job {result.job}")
    job.outcome = result.outcome
    job.finished = received
    job.detail = result.detail
    if result.outcome != "ok" or result.local_stats is None or result.received is None:
        return False
    # The time is the contributor's. It cannot be before the job was
    # issued, or after Sonoran got the result.
    at = min(max(result.received, job.issued), received)
    stats: LocalStats = result.local_stats
    await session.execute(
        insert(LocalStatsMetrics).values(
            time=at,
            job=job.job,
            node_num=job.target,
            location=job.location,
            source=job.source,
            hops=result.hops,
            rx_snr=result.rx_snr,
            rx_rssi=result.rx_rssi,
            **stats.model_dump(),
        )
    )
    return True


async def expire_jobs(session: AsyncSession, now: datetime) -> int:
    """Close every open job past its `expires`. Returns how many."""
    rows = await session.execute(
        update(ContribJob)
        .where(ContribJob.outcome.is_(None), ContribJob.expires < now)
        .values(outcome=EXPIRED, finished=now)
        .returning(ContribJob.job)
    )
    return len(rows.all())


async def to_clear(session: AsyncSession) -> list[tuple[str, Who]]:
    """Finished jobs whose outbox message is still there."""
    rows = await session.execute(
        select(ContribJob.job, ContribJob.location, ContribJob.source).where(
            ContribJob.outcome.is_not(None), ContribJob.cleared.is_(False)
        )
    )
    return [(job, Who(location, source)) for job, location, source in rows.all()]


async def mark_cleared(session: AsyncSession, jobs: list[str]) -> None:
    """Note that these jobs' outbox messages are cleared."""
    if jobs:
        await session.execute(
            update(ContribJob).where(ContribJob.job.in_(jobs)).values(cleared=True)
        )


async def plan_jobs(session: AsyncSession, now: datetime) -> list[NewJob]:
    """Write the jobs due now, and return them to publish.

    A target is a node of a role in `TARGET_ROLES` that at least one
    contributor taking `local_stats` jobs hears.
    """
    heard = await session.execute(
        select(
            ContribHeard.node_num,
            ContribHeard.location,
            ContribHeard.source,
            ContribHeard.hops,
            ContribHeard.last_heard,
            Node.role,
        )
        .join(
            ContribSource,
            (ContribSource.location == ContribHeard.location)
            & (ContribSource.source == ContribHeard.source),
        )
        .join(Node, Node.node_num == ContribHeard.node_num)
        .where(Node.role.in_(TARGET_ROLES), ContribSource.kinds.contains([KIND]))
    )
    candidates: dict[int, list[Candidate]] = defaultdict(list)
    roles: dict[int, str | None] = {}
    for num, location, source, hops, last_heard, role in heard.all():
        candidates[num].append(Candidate(Who(location, source), hops, last_heard))
        roles[num] = role
    if not candidates:
        return []
    targets = list(candidates)

    readings = await session.execute(
        select(LocalStatsMetrics.node_num, func.max(LocalStatsMetrics.time))
        .where(LocalStatsMetrics.node_num.in_(targets))
        .group_by(LocalStatsMetrics.node_num)
    )
    last_reading: dict[int, datetime] = {num: at for num, at in readings.all()}

    latest_round = (
        select(ContribJob.target, func.max(ContribJob.round_started).label("started"))
        .where(ContribJob.target.in_(targets))
        .group_by(ContribJob.target)
        .subquery()
    )
    round_rows = await session.execute(
        select(
            ContribJob.target,
            ContribJob.round_started,
            ContribJob.location,
            ContribJob.source,
            ContribJob.outcome,
        ).join(
            latest_round,
            (latest_round.c.target == ContribJob.target)
            & (latest_round.c.started == ContribJob.round_started),
        )
    )
    rounds: dict[int, tuple[datetime, list[tuple[Who, str | None]]]] = {}
    for target, started, location, source, outcome in round_rows.all():
        rounds.setdefault(target, (started, []))[1].append((Who(location, source), outcome))

    open_rows = await session.execute(
        select(ContribJob.location, ContribJob.source).where(ContribJob.outcome.is_(None))
    )
    busy = {Who(location, source) for location, source in open_rows.all()}

    planned: list[NewJob] = []
    # The longest-waiting target first, so one busy contributor does not
    # starve the same target every tick.
    for target in sorted(
        targets, key=lambda num: last_reading.get(num) or datetime.min.replace(tzinfo=now.tzinfo)
    ):
        started, jobs = rounds.get(target, (None, []))
        choice = next_job(
            last_reading.get(target),
            started,
            jobs,
            candidates[target],
            now,
            interval_for_role(roles[target]),
            busy,
        )
        if choice is None:
            continue
        who, round_started = choice
        busy.add(who)
        planned.append(NewJob(uuid4().hex, who, target, now, now + JOB_WAIT))
        session.add(
            ContribJob(
                job=planned[-1].job,
                location=who.location,
                source=who.source,
                kind=KIND,
                target=target,
                round_started=round_started,
                issued=now,
                expires=now + JOB_WAIT,
                cleared=False,
            )
        )
    await session.flush()
    return planned


async def prune(session: AsyncSession, now: datetime, keep: timedelta) -> None:
    """Delete finished, cleared jobs older than `keep`."""
    await session.execute(
        delete(ContribJob).where(ContribJob.cleared.is_(True), ContribJob.issued < now - keep)
    )
