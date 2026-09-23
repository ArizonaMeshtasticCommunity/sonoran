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

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.json_schema import models_json_schema

STATION_ID = re.compile(r"^[a-z0-9-]{3,32}$")
# An ICAO address as readsb prints it. A leading `~` marks an address
# that is not an ICAO one, such as a TIS-B target.
ICAO = re.compile(r"^~?[0-9a-f]{6}$")

# Everything an observation may be. Phase 1 stores `adsb` and `uat`; the
# ingest drops the rest, counted, until their phase lands.
Kind = Literal["adsb", "uat", "aprs", "sonde", "ism"]
KINDS: tuple[str, ...] = ("adsb", "uat", "aprs", "sonde", "ism")
AIRCRAFT_KINDS = frozenset({"adsb", "uat"})
# What the ingest stores today. The RF page reads this through
# `/api/rf/kinds`, so it never shows a source as working before it does.
STORED_KINDS = AIRCRAFT_KINDS

MAX_OBS = 100
MAX_META_BYTES = 1024
# A flat map of short scalars is all any station needs to describe a
# contact, and all the RF page can display.
MAX_META_KEYS = 16
MAX_META_VALUE_CHARS = 120
META_KEY = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,31}$")
# A Meshtastic node ID, as the firmware prints it.
MESH_NODE = re.compile(r"^![0-9a-f]{8}$")
# 902 to 928 MHz in 50 kHz bins is 520. This leaves room for finer bins
# or a wider band without letting one message grow without bound.
MAX_BINS = 4096


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
        """Bound the shape of station-supplied `meta`, not just its size.

        `meta` arrives from an MQTT station and was previously checked
        for one thing: that `repr()` of it fits in a kilobyte. Inside
        that kilobyte it could hold any keys, nested objects and arrays,
        and values of any type -- and the RF page renders every key it
        finds, because the non-aircraft tooltip is a generic viewer for
        sources whose fields we do not know in advance.

        It is rendered safely today: `rf.js` builds DOM with
        `el({ text })`. This is not a live vulnerability. It is
        attacker-shaped JSON sitting on a public API, and it becomes one
        the moment anybody renders it as a string -- which is exactly
        how #81 happened, where a node's name reached an innerHTML sink.

        A key allowlist would close it hardest, and it is what #148
        suggested. It would also delete the generic viewer, which is a
        real feature for `aprs`, `sonde` and `ism`. So instead the
        SHAPE is bounded, which removes the category without removing
        the function:

        * scalars only -- no nested dict or list, so nothing recursive
          reaches a renderer
        * a bounded number of keys, each a plain identifier-ish name
        * bounded string lengths on both keys and values

        What survives is a small flat map of short scalars. There is
        nothing left to smuggle through it.
        """
        if value is None:
            return None
        if len(repr(value).encode()) > MAX_META_BYTES:
            raise ValueError(f"meta is larger than {MAX_META_BYTES} bytes")
        if len(value) > MAX_META_KEYS:
            raise ValueError(f"meta has more than {MAX_META_KEYS} keys")
        for key, item in value.items():
            if not META_KEY.match(key):
                raise ValueError(f"meta key {key!r} is not a plain name")
            if isinstance(item, bool) or item is None or isinstance(item, int | float):
                continue
            if isinstance(item, str):
                if len(item) > MAX_META_VALUE_CHARS:
                    raise ValueError(
                        f"meta value for {key!r} is longer than {MAX_META_VALUE_CHARS}"
                    )
                continue
            raise ValueError(
                f"meta value for {key!r} is a {type(item).__name__}; "
                f"only strings, numbers, booleans and null are allowed"
            )
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
    # The Meshtastic node on the same site, if any (design 3.5), so the
    # minutes it was transmitting are not read as interference.
    mesh_node: Annotated[str | None, Field(pattern=MESH_NODE.pattern)] = None


# A level in tenths of a dB relative to the dongle's full scale. None is
# a bin no sweep reached in that minute.
Level = Annotated[int, Field(ge=-2000, le=1000)] | None
Busy = Annotated[int, Field(ge=0, le=100)] | None


class Spectrum(_Model):
    """One minute of the 900 MHz band from one station, on `rf/v1/<station>/spectrum`.

    Bin `i` covers `f_start_hz + i * bin_hz` to the next bin. Per bin: the
    median, the 95th percentile and the peak level over the minute's
    sweeps, and `busy`, the share of sweeps in percent in which the bin
    stood more than 6 dB above its own median. The four arrays have one
    entry per bin. Levels compare one station with itself over time,
    never two stations (design 3.5).
    """

    v: Literal[1]
    station: StationId
    kind: Literal["spectrum"]
    # The start of the minute summarised.
    t: AwareDatetime
    f_start_hz: Annotated[int, Field(ge=0, le=6_000_000_000)]
    bin_hz: Annotated[int, Field(ge=1, le=10_000_000)]
    sweeps: Annotated[int, Field(ge=1, le=100_000)]
    # The fixed gain the dongle ran at. Never automatic (design 3.5).
    gain_db: Annotated[float, Field(ge=-10, le=100)]
    p50: Annotated[list[Level], Field(min_length=1, max_length=MAX_BINS)]
    p95: Annotated[list[Level], Field(min_length=1, max_length=MAX_BINS)]
    peak: Annotated[list[Level], Field(min_length=1, max_length=MAX_BINS)]
    busy: Annotated[list[Busy], Field(min_length=1, max_length=MAX_BINS)]

    @model_validator(mode="after")
    def _one_entry_per_bin(self) -> Spectrum:
        if not len(self.p50) == len(self.p95) == len(self.peak) == len(self.busy):
            raise ValueError("p50, p95, peak and busy must have one entry per bin")
        return self


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
    """Return the JSON Schema of every message, for agent builders.

    JSON Schema cannot say that a spectrum's four arrays are the same
    length. `Spectrum` checks it; an agent must too.
    """
    _, top = models_json_schema(
        [(Batch, "validation"), (Status, "validation"), (Spectrum, "validation")],
        ref_template="#/$defs/{model}",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "rf-agent message, version 1",
        "description": (
            "Published by rf-agent. Observations go to rf/v1/<station>/<kind>, "
            "the heartbeat to rf/v1/<station>/status, retained, and a minute of "
            "the 900 MHz band to rf/v1/<station>/spectrum. "
            "See docs/design/rf-map.md section 4. Generated from sonoran/rf/schema.py."
        ),
        # A message with `obs` is a batch, one of kind `spectrum` is a
        # spectrum, and anything else is a heartbeat. Not `oneOf`: a
        # heartbeat ignores unknown fields, so every batch would also pass
        # as one, and `anyOf` would let a batch with bad observations
        # through as a "heartbeat". sonoran itself decides by the topic;
        # this is the same split for a file on its own.
        "if": {"required": ["obs"]},
        "then": {"$ref": "#/$defs/Batch"},
        "else": {
            "if": {"required": ["kind"], "properties": {"kind": {"const": "spectrum"}}},
            "then": {"$ref": "#/$defs/Spectrum"},
            "else": {"$ref": "#/$defs/Status"},
        },
        "$defs": top["$defs"],
    }
