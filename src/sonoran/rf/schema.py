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

# Everything an observation may be.
Kind = Literal["adsb", "uat", "aprs", "sonde", "ism"]
KINDS: tuple[str, ...] = ("adsb", "uat", "aprs", "sonde", "ism")
AIRCRAFT_KINDS = frozenset({"adsb", "uat"})
# What the ingest stores. The RF page reads this through
# `/api/rf/kinds`, so it never shows a source as working before it does.
STORED_KINDS = frozenset(KINDS)

# What an `id` may be, one rule for each kind (design 4.2). Ids arrive
# lower-cased. One loose rule for every kind would store a bad id; this
# way a bad id is still refused and counted.
THING_ID: dict[str, re.Pattern[str]] = {
    "adsb": ICAO,
    "uat": ICAO,
    # A callsign with its SSID, which is how APRS names a station.
    "aprs": re.compile(r"^[a-z0-9]{1,6}(-[a-z0-9]{1,2})?$"),
    # A radiosonde serial as the decoder prints it.
    "sonde": re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$"),
    # An rtl_433 model and device id, joined.
    "ism": re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$"),
}

MAX_OBS = 100
# A flat map of short scalars is all any station needs to describe a
# contact, and all the RF page can display.
MAX_META_KEYS = 16
# Long enough for any APRS comment whole. The AX.25 information field
# is at most 256 octets, so no comment in it is longer. A value over
# the limit is dropped, not cut, so a lower limit loses the longest
# comments entirely. Never cut what somebody sent (design 4.2).
MAX_META_VALUE_CHARS = 256
# Room for one comment at the limit beside a full set of readings.
MAX_META_BYTES = 4096
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
    # APRS only: true when the receiver heard the sender itself, with no
    # digipeater in between (no used hop, `*`, in the path). A relayed
    # packet still carries the sender's own position, but its signal is
    # the last digipeater's, and it says nothing about how far the
    # receiver hears. Missing is not true. See design 5.1 and
    # AGENTS.md 9.5, the same trap on Meshtastic.
    direct: bool | None = None
    meta: dict[str, object] | None = None

    @field_validator("id")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("meta")
    @classmethod
    def _small_meta(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        """Keep the parts of `meta` that are safe, drop the rest.

        `meta` arrives from an MQTT station. It used to be checked for
        one thing: that `repr()` of it fits in a kilobyte. Inside that
        kilobyte it could hold any keys, nested objects and arrays, and
        values of any type -- and the RF page renders every key it
        finds, because the non-aircraft tooltip is a generic viewer for
        sources whose fields we do not know in advance.

        It is rendered safely today (`rf.js` builds DOM with
        `el({ text })`), so this was never a live vulnerability. It is
        attacker-shaped JSON on a public API, and it becomes one the
        moment somebody renders it as a string -- which is how #81
        happened.

        **This FILTERS rather than rejects, and that is the whole
        point.** Observations arrive in batches of up to 100. An earlier
        version of this raised on a bad field, and measured:

            100 good observations                -> accepted, 100 stored
            1 nested-meta + 99 good observations -> WHOLE BATCH REJECTED

        A station whose firmware puts one nested object in `meta` would
        have lost every observation in every batch, silently, for as
        long as it ran -- and its operator would see "my station stopped
        reporting" with nothing to explain it. That is a far worse
        outcome than the shape it was defending against.

        `meta` is decoration. The position, altitude and signal are the
        measurement. Dropping an unusable key costs nothing; dropping
        the batch costs a hundred real aircraft positions.

        What survives is a small flat map of short scalars, which is the
        same guarantee the raising version gave, without the collateral.
        """
        if value is None:
            return None
        kept: dict[str, object] = {}
        for key, item in value.items():
            if len(kept) >= MAX_META_KEYS:
                break
            if not META_KEY.match(key):
                continue
            if isinstance(item, bool) or item is None or isinstance(item, int | float):
                kept[key] = item
            elif isinstance(item, str) and len(item) <= MAX_META_VALUE_CHARS:
                kept[key] = item
            # Anything else -- a dict, a list, an over-long string -- is
            # dropped. No recursion reaches a renderer.
        if len(repr(kept).encode()) > MAX_META_BYTES:
            # Bounded key count and value length make this close to
            # unreachable, but the byte cap is the one promise the old
            # code made and it is kept rather than assumed.
            return {}
        return kept


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
