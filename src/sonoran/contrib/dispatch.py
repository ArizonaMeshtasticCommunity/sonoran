"""Which node to ask, and which contributor asks it (#178, #181).

Pure rules, no database and no broker, so each one has its own test.
See `docs/design/contributors.md` section 5.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sonoran.contrib.schema import Contributor, Result, node_num

__all__ = [
    "JOB_WAIT",
    "TARGET_ROLES",
    "Candidate",
    "Contributor",
    "JobFacts",
    "choose",
    "interval_for_role",
    "is_due",
    "next_job",
    "refuse_result",
]

# The roles #178 names as the infrastructure to read.
TARGET_ROLES = frozenset({"ROUTER", "ROUTER_LATE", "CLIENT_BASE"})

# The firmware's default telemetry interval, for the role of the node
# that sends it: `default_telemetry_broadcast_interval_secs` is
# `IF_ROUTER(ONE_DAY / 2, 60 * 60)`, and IF_ROUTER means ROUTER or
# ROUTER_LATE (`src/mesh/Default.h` lines 18 and 47, meshtastic/firmware
# v2.7.26.54e0d8d). We ask a node no more often than it would send its
# own telemetry.
ROUTER_ROLES = frozenset({"ROUTER", "ROUTER_LATE"})
ROUTER_INTERVAL = timedelta(seconds=24 * 60 * 60 // 2)
OTHER_INTERVAL = timedelta(seconds=60 * 60)

# How long a job stays open: the Meshtastic Python library's own wait
# for an answer, `MeshInterface(timeout=300)`
# (`meshtastic/mesh_interface.py` line 93, meshtastic/python 2.7.11).
JOB_WAIT = timedelta(seconds=300)


@dataclass(frozen=True)
class Candidate:
    """A contributor whose node lists the target in its node list."""

    contributor: Contributor
    hops: int | None
    last_heard: datetime


@dataclass(frozen=True)
class JobFacts:
    """What Sonoran wrote down about one job, to check a result against."""

    job: str
    contributor: Contributor
    kind: str
    target: int
    has_result: bool


def interval_for_role(role: str | None) -> timedelta:
    """How often to read a node of this role."""
    return ROUTER_INTERVAL if role in ROUTER_ROLES else OTHER_INTERVAL


def is_due(
    last_reading: datetime | None,
    round_started: datetime | None,
    now: datetime,
    interval: timedelta,
) -> bool:
    """True when a target needs a new round.

    It does not, while its last reading is younger than its interval, or
    while its last round started within its interval. A round that ended
    with every candidate failed is not tried again at once.
    """
    for then in (last_reading, round_started):
        if then is not None and now - then < interval:
            return False
    return True


def choose(
    candidates: Iterable[Candidate],
    now: datetime,
    interval: timedelta,
    failed: set[Contributor],
    busy: set[Contributor],
) -> Contributor | None:
    """The contributor to ask, or None.

    Only a contributor that heard the target within its interval, that
    has not failed in this round, and has no open job. The fewest hops
    first (#181), unknown hops last, then the most recently heard.
    """
    usable = [
        item
        for item in candidates
        if now - item.last_heard <= interval
        and item.contributor not in failed
        and item.contributor not in busy
    ]
    if not usable:
        return None
    best = min(
        usable,
        key=lambda item: (
            item.hops is None,
            item.hops if item.hops is not None else 0,
            now - item.last_heard,
            item.contributor,
        ),
    )
    return best.contributor


def next_job(
    last_reading: datetime | None,
    round_started: datetime | None,
    round_jobs: list[tuple[Contributor, str | None]],
    candidates: list[Candidate],
    now: datetime,
    interval: timedelta,
    busy: set[Contributor],
) -> tuple[Contributor, datetime] | None:
    """The next job for one target: who asks, and in which round.

    `round_jobs` are the jobs of the target's latest round, which
    started at `round_started`, with their outcomes (None while open).

    - A round with an open job, or with a reading, waits.
    - Within its interval, a round moves to the next candidate that has
      not failed in it (#181). With none left, the round is over.
    - After its interval, a due target starts a new round, and old
      failures are forgotten.
    """
    if round_started is not None and now - round_started < interval:
        if any(outcome is None or outcome == "ok" for _, outcome in round_jobs):
            return None
        failed = {who for who, _ in round_jobs}
        chosen = choose(candidates, now, interval, failed=failed, busy=busy)
        return None if chosen is None else (chosen, round_started)
    if not is_due(last_reading, None, now, interval):
        return None
    chosen = choose(candidates, now, interval, failed=set(), busy=busy)
    return None if chosen is None else (chosen, now)


def refuse_result(
    facts: JobFacts | None,
    contributor: Contributor,
    result: Result,
) -> str | None:
    """Why a result is refused, or None when it is accepted.

    `contributor` is the one the result's topic names. The broker lets a
    login publish only to its own inbox. This checks it again, and checks
    the body against the job Sonoran wrote, so a contributor cannot write
    a reading for a node it was not asked about.
    """
    if facts is None:
        return "no such job"
    if result.job != facts.job:
        return "the body names another job"
    if facts.contributor != contributor:
        return "the job was given to another contributor"
    if Contributor(result.location, result.source) != contributor:
        return "the body names another contributor"
    if result.kind != facts.kind:
        return "another kind of job"
    if node_num(result.target) != facts.target:
        return "another target"
    if facts.has_result:
        return "the job already has a result"
    return None
