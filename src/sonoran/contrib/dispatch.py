"""Skeleton for the red step (#178)."""

from dataclasses import dataclass
from datetime import timedelta
from typing import NamedTuple

JOB_WAIT = timedelta(0)
TARGET_ROLES: frozenset[str] = frozenset()


class Contributor(NamedTuple):
    location: str
    source: str


@dataclass(frozen=True)
class Candidate:
    contributor: Contributor
    hops: int | None
    last_heard: object


@dataclass(frozen=True)
class JobFacts:
    job: str
    contributor: Contributor
    kind: str
    target: int
    has_result: bool


def interval_for_role(role):  # type: ignore[no-untyped-def]
    raise NotImplementedError


def is_due(last_reading, round_started, now, interval):  # type: ignore[no-untyped-def]
    raise NotImplementedError


def choose(candidates, now, interval, failed, busy):  # type: ignore[no-untyped-def]
    raise NotImplementedError


def refuse_result(facts, contributor, result):  # type: ignore[no-untyped-def]
    raise NotImplementedError
