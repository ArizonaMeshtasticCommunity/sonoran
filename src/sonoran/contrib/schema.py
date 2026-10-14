"""The messages between Sonoran and `sonoran-contributor`, version 1 (#178).

This is the contract. It is written once, here, and exported as JSON
Schema to `docs/contributor-message-v1.schema.json` for the contributor
repository. See `docs/design/contributors.md` sections 3 and 4.

Unknown fields are ignored, so a newer contributor may send more than
this and an older Sonoran still reads it. A field that is present but
wrong makes the whole message invalid.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal, NamedTuple

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from pydantic.json_schema import models_json_schema

from sonoran.rf.schema import SOURCE_ID, STATION_ID

# Everything a contributor sends or receives is under this root, apart
# from the Meshtastic `msh/` tree and the RF `rf/v1/` tree.
TOPIC_ROOT = "sonoran/v1/contributors"
# A job id: a UUID as 32 lower-case hex characters.
JOB_ID = re.compile(r"^[0-9a-f]{32}$")
# A node as Meshtastic prints it.
NODE_ID = re.compile(r"^![0-9a-f]{8}$")
# The largest node list a radio keeps: MAX_NUM_NODES on an ESP32-S3
# with 16 MB flash, `src/mesh/mesh-pb-constants.h` in meshtastic/firmware
# (default branch, read 2026-10-14). A contributor sends at most this
# many heard nodes, the most recently heard first.
MAX_HEARD = 250
# A short text a contributor may add to an `error` result.
MAX_DETAIL = 200

# The job kinds. A contributor does only the kinds it lists in its
# heartbeat and in its own allow list.
JobKind = Literal["local_stats"]
Outcome = Literal["ok", "no_reply", "refused", "error"]
Box = Literal["outbox", "inbox", "status"]

LocationId = Annotated[str, Field(pattern=STATION_ID.pattern)]
SourceId = Annotated[str, Field(pattern=SOURCE_ID.pattern)]
JobId = Annotated[str, Field(pattern=JOB_ID.pattern)]
NodeId = Annotated[str, Field(pattern=NODE_ID.pattern)]
# Unsigned 32-bit counters, as `uint32` in the protobuf.
U32 = Annotated[int, Field(ge=0, le=0xFFFFFFFF)]
# Hops: the header holds 3 bits, so 7 at most (HOP_MAX in
# `src/mesh/MeshTypes.h` line 38, meshtastic/firmware v2.7.26.54e0d8d).
Hops = Annotated[int, Field(ge=0, le=7)]
# A share in percent. The firmware sends a float.
Percent = Annotated[float, Field(ge=0, le=100)]


class Contributor(NamedTuple):
    """One contributor: a location and one of its sources (#305)."""

    location: str
    source: str


def node_num(node_id: str) -> int:
    """Return the node number of `!1234abcd`."""
    if not NODE_ID.match(node_id):
        raise ValueError(f"not a node id: {node_id!r}")
    return int(node_id[1:], 16)


def node_id(num: int) -> str:
    """Return the `!1234abcd` form of a node number."""
    return f"!{num & 0xFFFFFFFF:08x}"


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class LocalStats(_Model):
    """`LocalStats` from `meshtastic/telemetry.proto`, by its field names.

    Every field is optional: an older firmware sends fewer.
    `noise_floor` (field 15, int32) is the radio's average noise floor
    in dBm, as the node measured it. It is not the theoretical floor in
    `sonoran/radio/presets.py`.
    """

    uptime_seconds: U32 | None = None
    channel_utilization: Percent | None = None
    air_util_tx: Percent | None = None
    num_packets_tx: U32 | None = None
    num_packets_rx: U32 | None = None
    num_packets_rx_bad: U32 | None = None
    num_online_nodes: U32 | None = None
    num_total_nodes: U32 | None = None
    num_rx_dupe: U32 | None = None
    num_tx_relay: U32 | None = None
    num_tx_relay_canceled: U32 | None = None
    heap_total_bytes: U32 | None = None
    heap_free_bytes: U32 | None = None
    num_tx_dropped: U32 | None = None
    noise_floor: Annotated[int, Field(ge=-(2**31), le=2**31 - 1)] | None = None


class Job(_Model):
    """A job, published by Sonoran, retained, on `.../outbox/<job>`.

    The contributor ignores a job whose `expires` has passed.
    """

    v: Literal[1]
    job: JobId
    kind: JobKind
    target: NodeId
    issued: AwareDatetime
    expires: AwareDatetime


class Result(_Model):
    """The result of one job, from the contributor, on `.../inbox/<job>`."""

    v: Literal[1]
    job: JobId
    location: LocationId
    source: SourceId
    kind: JobKind
    target: NodeId
    outcome: Outcome
    sent: AwareDatetime
    # When the answer reached the contributor's node. Set with `ok`.
    received: AwareDatetime | None = None
    local_stats: LocalStats | None = None
    # About the answer as the contributor's node received it.
    hops: Hops | None = None
    rx_snr: float | None = None
    rx_rssi: int | None = None
    detail: Annotated[str, Field(max_length=MAX_DETAIL)] | None = None

    @model_validator(mode="after")
    def _ok_has_a_reading(self) -> Result:
        if self.outcome == "ok" and (self.local_stats is None or self.received is None):
            raise ValueError("an ok result carries local_stats and received")
        return self


class Heard(_Model):
    """One node in the contributor's node list."""

    node: NodeId
    # Hops away, as the node list holds it. None when it does not know.
    hops: Hops | None = None
    last_heard: AwareDatetime


class Status(_Model):
    """The heartbeat, published retained on `.../status`."""

    v: Literal[1]
    location: LocationId
    source: SourceId
    sent: AwareDatetime
    version: Annotated[str, Field(max_length=64)] | None = None
    # The contributor's own node, when it is connected to it.
    mesh_node: NodeId | None = None
    kinds: list[JobKind] = []
    heard: Annotated[list[Heard], Field(max_length=MAX_HEARD)] = []


class TopicError(ValueError):
    """The topic is not a contributor topic."""


class Topic(NamedTuple):
    """A contributor topic, split. `job` is None for `status`."""

    contributor: Contributor
    box: Box
    job: str | None


def job_topic(box: Literal["outbox", "inbox"], contributor: Contributor, job: str) -> str:
    """Return the outbox or inbox topic of one job."""
    return f"{TOPIC_ROOT}/{contributor.location}/{contributor.source}/{box}/{job}"


def status_topic(contributor: Contributor) -> str:
    """Return a contributor's heartbeat topic."""
    return f"{TOPIC_ROOT}/{contributor.location}/{contributor.source}/status"


def parse_topic(topic: str) -> Topic:
    """Split a contributor topic, or raise `TopicError`.

    The topics are `<root>/<location>/<source>/status` and
    `<root>/<location>/<source>/(outbox|inbox)/<job>`.
    """
    root = TOPIC_ROOT.split("/")
    parts = topic.split("/")
    rest = parts[len(root) :]
    if parts[: len(root)] != root or len(rest) not in (3, 4):
        raise TopicError(topic)
    location, source, box = rest[0], rest[1], rest[2]
    if not STATION_ID.match(location) or not SOURCE_ID.match(source):
        raise TopicError(topic)
    contributor = Contributor(location, source)
    if box == "status" and len(rest) == 3:
        return Topic(contributor, "status", None)
    if box in ("outbox", "inbox") and len(rest) == 4 and JOB_ID.match(rest[3]):
        return Topic(contributor, box, rest[3])  # type: ignore[arg-type]
    raise TopicError(topic)


def json_schema() -> dict[str, object]:
    """Return the JSON Schema of every message, for the contributor."""
    _, top = models_json_schema(
        [(Job, "validation"), (Result, "validation"), (Status, "validation")],
        ref_template="#/$defs/{model}",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "sonoran-contributor message, version 1",
        "description": (
            f"Topics under {TOPIC_ROOT}/<location>/<source>/. Sonoran publishes a Job, "
            "retained, to outbox/<job>, and clears it with an empty retained message. "
            "The contributor publishes a Result to inbox/<job> and its Status, "
            "retained, to status. See docs/design/contributors.md. "
            "Generated from sonoran/contrib/schema.py."
        ),
        # Sonoran decides by the topic. This is the same split for a
        # file on its own: a job has `expires`, a result has `outcome`.
        "if": {"required": ["expires"]},
        "then": {"$ref": "#/$defs/Job"},
        "else": {
            "if": {"required": ["outcome"]},
            "then": {"$ref": "#/$defs/Result"},
            "else": {"$ref": "#/$defs/Status"},
        },
        "$defs": top["$defs"],
    }
