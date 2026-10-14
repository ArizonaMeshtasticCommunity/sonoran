"""Skeleton for the red step (#178)."""

from typing import NamedTuple

from pydantic import BaseModel

TOPIC_ROOT = ""
MAX_HEARD = 0


class TopicError(ValueError):
    pass


class Job(BaseModel):
    pass


class Result(BaseModel):
    pass


class Status(BaseModel):
    pass


class Topic(NamedTuple):
    contributor: object
    box: str
    job: str | None


def job_topic(box: str, contributor: object, job: str) -> str:
    raise NotImplementedError


def parse_topic(topic: str) -> Topic:
    raise NotImplementedError


def node_num(node_id: str) -> int:
    raise NotImplementedError


def json_schema() -> dict[str, object]:
    raise NotImplementedError
