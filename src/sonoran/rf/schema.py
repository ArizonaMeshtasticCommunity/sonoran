"""The messages `rf-agent` publishes, version 1.

This is the contract between the agent on a member's machine and
`sonoran-rf-ingest`. It is written once, here, and exported as JSON
Schema to `docs/rf-message-v1.schema.json` for whoever builds an agent.
See `docs/design/rf-map.md` section 4.

Unknown fields are ignored, so an agent may send more than this and an
older sonoran still reads it. A field that is present but wrong makes
the whole message invalid: a point with a bad latitude is not a point.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import models_json_schema

STATION_ID = re.compile(r"^[a-z0-9-]{3,32}$")
# An ICAO address as readsb prints it. A leading `~` marks an address
# that is not an ICAO one, such as a TIS-B target.
ICAO = re.compile(r"^~?[0-9a-f]{6}$")

# Everything an observation may be. Phase 1 stores `adsb` and `uat`; the
# ingest drops the rest, counted, until their phase lands.
Kind = Literal["adsb", "uat", "aprs", "sonde", "ism"]
AIRCRAFT_KINDS = frozenset({"adsb", "uat"})

MAX_OBS = 100
MAX_META_BYTES = 1024


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)


class Observation(_Model):
    """One thing heard, at one moment, by one station."""

    id: Annotated[str, Field(min_length=1, max_length=64)]
    t: AwareDatetime
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    alt_m: Annotated[float | None, Field(ge=-500, le=60000)] = None
    alt_ref: Literal["baro", "geom"] | None = None
    gs_kn: Annotated[float | None, Field(ge=0, le=2000)] = None
    track_deg: Annotated[float | None, Field(ge=0, le=360)] = None
    rssi_db: Annotated[float | None, Field(ge=-200, le=50)] = None
    meta: dict[str, object] | None = None

    @field_validator("id")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("meta")
    @classmethod
    def _small_meta(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        if value is not None and len(repr(value).encode()) > MAX_META_BYTES:
            raise ValueError(f"meta is larger than {MAX_META_BYTES} bytes")
        return value


def _station_id(value: str) -> str:
    if not STATION_ID.match(value):
        raise ValueError("station must match [a-z0-9-]{3,32}")
    return value


StationId = Annotated[str, Field(pattern=STATION_ID.pattern)]


class Batch(_Model):
    """A batch of observations of one kind, from one station."""

    v: Literal[1]
    station: StationId
    kind: Kind
    sent: AwareDatetime
    obs: Annotated[list[Observation], Field(max_length=MAX_OBS)]


class Counts(_Model):
    """What the agent did since its last heartbeat."""

    heard: Annotated[int, Field(ge=0)] = 0
    sent: Annotated[int, Field(ge=0)] = 0
    dropped: Annotated[int, Field(ge=0)] = 0


class Status(_Model):
    """The heartbeat, published retained on `rf/v1/<station>/status`."""

    v: Literal[1]
    station: StationId
    sent: AwareDatetime
    lat: Annotated[float | None, Field(ge=-90, le=90)] = None
    lon: Annotated[float | None, Field(ge=-180, le=180)] = None
    precision_m: Annotated[int | None, Field(ge=0, le=100000)] = None
    kinds: list[Kind] = []
    agent_version: Annotated[str | None, Field(max_length=64)] = None
    counts: Counts = Counts()


class TopicError(ValueError):
    """The topic is not an `rf/v1/<station>/<kind>` topic."""


def parse_topic(topic: str) -> tuple[str, str]:
    """Return (station, kind or `status`) from an RF topic."""
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != "rf" or parts[1] != "v1":
        raise TopicError(topic)
    station, kind = parts[2], parts[3]
    try:
        _station_id(station)
    except ValueError as exc:
        raise TopicError(topic) from exc
    return station, kind


def json_schema() -> dict[str, object]:
    """Return the JSON Schema of both messages, for agent builders."""
    _, top = models_json_schema(
        [(Batch, "validation"), (Status, "validation")], ref_template="#/$defs/{model}"
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "rf-agent message, version 1",
        "description": (
            "Published by rf-agent. Observations go to rf/v1/<station>/<kind>, "
            "the heartbeat to rf/v1/<station>/status, retained. "
            "See docs/design/rf-map.md section 4. Generated from sonoran/rf/schema.py."
        ),
        "oneOf": [{"$ref": "#/$defs/Batch"}, {"$ref": "#/$defs/Status"}],
        "$defs": top["$defs"],
    }
