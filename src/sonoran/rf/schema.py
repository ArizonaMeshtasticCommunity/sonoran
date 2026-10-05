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
from typing import Annotated, Literal, NamedTuple

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic.json_schema import models_json_schema

STATION_ID = re.compile(r"^[a-z0-9-]{3,32}$")
# One Pi or decoder at a location (#305). A location is what the map
# shows as one station. Each source has its own broker login and its
# own heartbeat on `rf/v1/<station>/status/<source>`.
SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,15}$")
# The `rf_source` key of an agent that sends no source. It is not a
# valid source id, so no agent can send it.
NO_SOURCE = "-"
# An ICAO address as readsb prints it. A leading `~` marks an address
# that is not an ICAO one, such as a TIS-B target.
ICAO = re.compile(r"^~?[0-9a-f]{6}$")

# An APRS station: a callsign and optional SSID. Up to nine characters,
# not AX.25's six, because a third-party packet carries an internet
# source name such as a CWOP station's.
APRS_STATION = re.compile(r"^[a-z0-9]{1,9}(?:-[a-z0-9]{1,2})?$")
# An APRS object or item, named by the station that sends it: `;` and
# the name. `;` never appears in a callsign, so an object cannot take a
# station's id. No `/` or `#`: the id is a URL path segment.
APRS_OBJECT = re.compile(r"^;[a-z0-9._+-][a-z0-9._+-]{0,8}$")
# Path words that name no station: the generic digipeating aliases and
# the internet markers. One of these as `via` credits nobody, even
# though it is shaped like a callsign.
APRS_ALIAS = re.compile(
    r"^(?:wide[1-7]?|trace[1-7]?|relay|echo|gate|tcpip|tcpxx|nogate|rfonly|q[a-z]{2})(?:-[0-9]{1,2})?$"
)
# A sender may blur its position (APRS position ambiguity). Past this,
# a position does not place a cell in the heard layer, which is about
# 2 km on a side.
HEARD_PRECISION_M = 1000.0

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
    # A station, or an object or item that a station reports (design 5.1).
    "aprs": re.compile(rf"^(?:{APRS_STATION.pattern[1:-1]}|{APRS_OBJECT.pattern[1:-1]})$"),
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
# The raw frame or line an observation was decoded from. An APRS frame
# in TNC2 form is at most about 330 characters; the rest is headroom.
MAX_RAW_CHARS = 1024
META_KEY = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,31}$")
# A Meshtastic node ID, as the firmware prints it.
MESH_NODE = re.compile(r"^![0-9a-f]{8}$")
# 902 to 928 MHz in 50 kHz bins is 520. This leaves room for finer bins
# or a wider band without letting one message grow without bound.
MAX_BINS = 4096
# A name a station gives one of its sweep ranges, or a member gives a
# mod: short, lower case, and safe in a URL path.
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,15}$")
# The sweeps one heartbeat may report (#324).
MAX_SWEEPS = 8
MAX_COMMAND_CHARS = 512
# A point's id inside a member's mod. Sonoran stores it under the
# station and the mod, so no mod can take another's id or a built-in one.
CUSTOM_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,31}$")
MAX_CUSTOM_POINTS = 100

# Characters that change how text looks without being seen: zero-width
# characters, direction overrides and isolates, the soft hyphen, and the
# control characters. A name that holds them can pretend to be another
# name, so they are removed from text a station sends before it is
# stored (#324, section 8).
INVISIBLE = re.compile(
    "[\x00-\x08\x0b-\x1f\x7f-\x9f\u00ad\u061c\u115f\u1160\u180e"
    "\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\ufeff\ufff9-\ufffb]"
)


def plain_text(value: str) -> str:
    """Return `value` without the characters `INVISIBLE` names."""
    return INVISIBLE.sub("", value)


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
    # APRS only: the station the receiver actually decoded, when that is
    # not the thing named by `id`. The last digipeater that repeated a
    # packet, the gateway that put a third-party packet on the air, or
    # the station that sent an object. The receiver did hear this
    # station, so it counts in the heard layer (design 5.1).
    via: Annotated[str | None, Field(max_length=16)] = None
    # How far the sender blurred its own position, in metres. Missing
    # means not blurred.
    precision_m: Annotated[float | None, Field(ge=0, le=500_000)] = None
    # What the decoder gave the agent, before decoding, for the RF tab's
    # table: an APRS frame in TNC2 form, an ADS-B frame as hex, a sonde
    # or rtl_433 JSON line. Missing when the source has none (readsb's
    # aircraft.json). Longer than the limit is sent as missing, never cut.
    raw: Annotated[str | None, Field(max_length=MAX_RAW_CHARS)] = None
    meta: dict[str, object] | None = None

    @field_validator("id")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("raw", mode="before")
    @classmethod
    def _whole_raw_or_none(cls, value: object) -> object:
        """Drop an over-long `raw`, never the observation.

        Raising here would refuse the whole batch -- up to a hundred good
        points -- for one frame, the trap `_small_meta` documents. And a
        cut frame would read as the frame that was sent, so it is not
        shortened either: it is simply not stored.
        """
        if isinstance(value, str) and len(value) > MAX_RAW_CHARS:
            return None
        return value

    @field_validator("via")
    @classmethod
    def _lower_via(cls, value: str | None) -> str | None:
        return None if value is None else value.strip().lower() or None

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
        return small_meta(value)


def small_meta(value: dict[str, object] | None, *, plain: bool = False) -> dict[str, object] | None:
    """Keep the parts of a `meta` map that are safe; see `Observation._small_meta`.

    With `plain`, text values also lose the characters `INVISIBLE` names.
    A member's mod sends text we did not write, so its values are made
    plain before they are stored (#324, section 8).
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
            kept[key] = plain_text(item) if plain else item
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
# Optional in every message. An agent that does not send it is the
# location's only source, as before #305.
SourceId = Annotated[str | None, Field(pattern=SOURCE_ID.pattern)]


class Batch(_Model):
    """A batch of observations of one kind, from one station."""

    v: Literal[1]
    station: StationId
    source: SourceId = None
    kind: Kind
    sent: AwareDatetime
    obs: Annotated[list[Observation], Field(max_length=MAX_OBS)]


class Counts(_Model):
    """What the agent did since its last heartbeat."""

    heard: Annotated[int, Field(ge=0)] = 0
    sent: Annotated[int, Field(ge=0)] = 0
    dropped: Annotated[int, Field(ge=0)] = 0


Hz = Annotated[int, Field(ge=0, le=6_000_000_000)]


class Sweep(_Model):
    """What one sweeper of a station runs, as the station reports it (#324).

    This is a claim, shown as "reported by the station". Nothing is ever
    run from it, and it never changes how a station's data is trusted.
    `command` is the exact command line the sweeper runs, for a reader
    who wants to repeat it. `dwell_s` is set when one dongle takes turns
    between ranges: it sweeps this range `dwell_s` seconds at a time.
    """

    tool: Annotated[str, Field(pattern=r"^[a-z0-9_.-]{1,32}$")]
    tool_version: Annotated[str | None, Field(max_length=64)] = None
    name: Annotated[str | None, Field(pattern=NAME.pattern)] = None
    f_start_hz: Hz
    f_end_hz: Hz
    bin_hz: Annotated[int, Field(ge=1, le=10_000_000)]
    gain_db: Annotated[float, Field(ge=-10, le=100)]
    interval_s: Annotated[int | None, Field(ge=1, le=3600)] = None
    ppm: Annotated[int | None, Field(ge=-1000, le=1000)] = None
    dwell_s: Annotated[int | None, Field(ge=1, le=86400)] = None
    command: Annotated[str | None, Field(max_length=MAX_COMMAND_CHARS)] = None

    @field_validator("tool_version", "command")
    @classmethod
    def _plain(cls, value: str | None) -> str | None:
        return None if value is None else plain_text(value)

    @model_validator(mode="after")
    def _a_range(self) -> Sweep:
        if self.f_end_hz <= self.f_start_hz:
            raise ValueError("f_end_hz must be above f_start_hz")
        return self


def _usable_sweeps(value: object) -> object:
    """Keep the sweeps that pass the contract, drop the rest.

    A heartbeat is how the map knows a station is alive. One bad sweep
    report must not drop it, so a bad entry is left out instead, as a
    bad `meta` key is (`Observation._small_meta`).
    """
    if not isinstance(value, list):
        return []
    kept: list[Sweep] = []
    for item in value[:MAX_SWEEPS]:
        try:
            kept.append(Sweep.model_validate(item))
        except ValidationError:
            continue
    return kept


class Status(_Model):
    """The heartbeat, published retained.

    An agent with a `source` publishes it on
    `rf/v1/<station>/status/<source>`, so the sources of one location do
    not overwrite each other's heartbeat. An agent without one publishes
    it on `rf/v1/<station>/status`.
    """

    v: Literal[1]
    station: StationId
    source: SourceId = None
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
    # What each sweeper of this source runs (#324). Missing is not
    # "sweeps nothing": an older agent does not report it.
    sweeps: Annotated[list[Sweep], Field(max_length=MAX_SWEEPS)] = []

    @field_validator("sweeps", mode="before")
    @classmethod
    def _keep_usable_sweeps(cls, value: object) -> object:
        return _usable_sweeps(value)


# A level in tenths of a dB relative to the dongle's full scale. None is
# a bin no sweep reached in that minute.
Level = Annotated[int, Field(ge=-2000, le=1000)] | None
Busy = Annotated[int, Field(ge=0, le=100)] | None


class Spectrum(_Model):
    """One minute of one swept range from one station, on `rf/v1/<station>/spectrum`.

    A station may sweep any range it chooses, and more than one: with
    two dongles, or one that takes turns (#324). Each range sends its
    own minutes. A range is known by its source, `f_start_hz`, `bin_hz`
    and number of bins; `name` is an optional label the station gives it.

    Bin `i` covers `f_start_hz + i * bin_hz` to the next bin. Per bin: the
    median, the 95th percentile and the peak level over the minute's
    sweeps, and `busy`, the share of sweeps in percent in which the bin
    stood more than 6 dB above its own median. The four arrays have one
    entry per bin. Levels compare one station with itself over time,
    never two stations (design 3.5).
    """

    v: Literal[1]
    station: StationId
    source: SourceId = None
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
    name: Annotated[str | None, Field(pattern=NAME.pattern)] = None

    @model_validator(mode="after")
    def _one_entry_per_bin(self) -> Spectrum:
        if not len(self.p50) == len(self.p95) == len(self.peak) == len(self.busy):
            raise ValueError("p50, p95, peak and busy must have one entry per bin")
        return self


class CustomPoint(_Model):
    """One thing a member's mod heard (#324, section 6).

    A position is optional. With `heard_here`, the point is drawn at the
    station's own rounded position, and any position it sends is not
    used. With neither, it is listed in the table and never drawn.
    """

    id: Annotated[str, Field(min_length=1, max_length=32)]
    t: AwareDatetime
    lat: Annotated[float | None, Field(ge=-90, le=90)] = None
    lon: Annotated[float | None, Field(ge=-180, le=180)] = None
    heard_here: bool = False
    meta: dict[str, object] | None = None

    @field_validator("id")
    @classmethod
    def _lower(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("meta")
    @classmethod
    def _small_plain_meta(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        """Filtered as an observation's is, and made plain: see `small_meta`."""
        return small_meta(value, plain=True)

    @model_validator(mode="after")
    def _both_or_neither(self) -> CustomPoint:
        if (self.lat is None) != (self.lon is None):
            raise ValueError("lat and lon are sent together or not at all")
        return self


class Custom(_Model):
    """A batch from a member's own mod, on `rf/v1/<station>/custom` (#324).

    `mod` names the program within the station. Sonoran stores each point
    under the station and the mod, so a mod can never post as another
    station, another mod, or a built-in kind. It gets no more trust than
    a built-in decoder, and is shown as unverified.
    """

    v: Literal[1]
    station: StationId
    source: SourceId = None
    kind: Literal["custom"]
    mod: Annotated[str, Field(pattern=NAME.pattern)]
    sent: AwareDatetime
    points: Annotated[list[CustomPoint], Field(max_length=MAX_CUSTOM_POINTS)]


MAX_DISPLAY_NAME = 64
MAX_REGISTRY_SOURCES = 32


class Registry(_Model):
    """A location's entry in the registry, on `rf/v1/<station>/registry`.

    The registrar publishes it, retained, when a location or its tokens
    change (#305). The broker lets nobody else publish to this topic, so
    a station cannot claim a name or an owner. `sources` are the
    sources that hold a login now. An empty retained message removes
    the entry.
    """

    v: Literal[1]
    station: StationId
    sent: AwareDatetime
    display_name: Annotated[str, Field(min_length=1, max_length=MAX_DISPLAY_NAME)]
    # The owner's name as the community knows it. Never an account id.
    owner: Annotated[str | None, Field(max_length=MAX_DISPLAY_NAME)] = None
    sources: Annotated[
        list[Annotated[str, Field(pattern=SOURCE_ID.pattern)]],
        Field(max_length=MAX_REGISTRY_SOURCES),
    ] = []


class TopicError(ValueError):
    """The topic is not an RF topic."""


class Topic(NamedTuple):
    """An RF topic, split.

    `kind` is an observation kind, `spectrum`, `custom`, `status` or
    `registry`.
    `source` is set only for a heartbeat on `status/<source>`.
    """

    station: str
    kind: str
    source: str | None = None


def parse_topic(topic: str) -> Topic:
    """Split an RF topic.

    The topics are `rf/v1/<station>/<kind>` and, for a source's own
    heartbeat, `rf/v1/<station>/status/<source>`.
    """
    parts = topic.split("/")
    if len(parts) not in (4, 5) or parts[0] != "rf" or parts[1] != "v1":
        raise TopicError(topic)
    station, kind = parts[2], parts[3]
    source = parts[4] if len(parts) == 5 else None
    if source is not None and (kind != "status" or not SOURCE_ID.match(source)):
        raise TopicError(topic)
    try:
        _station_id(station)
    except ValueError as exc:
        raise TopicError(topic) from exc
    return Topic(station, kind, source)


def json_schema() -> dict[str, object]:
    """Return the JSON Schema of every message, for agent builders.

    JSON Schema cannot say that a spectrum's four arrays are the same
    length. `Spectrum` checks it; an agent must too.
    """
    _, top = models_json_schema(
        [
            (Batch, "validation"),
            (Status, "validation"),
            (Spectrum, "validation"),
            (Custom, "validation"),
            (Registry, "validation"),
        ],
        ref_template="#/$defs/{model}",
    )
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "rf-agent message, version 1",
        "description": (
            "Published by rf-agent. Observations go to rf/v1/<station>/<kind>, "
            "the heartbeat to rf/v1/<station>/status/<source> (or "
            "rf/v1/<station>/status without a source), retained, and a minute of "
            "a swept range to rf/v1/<station>/spectrum, and a member's mod's points "
            "to rf/v1/<station>/custom. The registrar alone "
            "publishes the Registry to rf/v1/<station>/registry, retained. "
            "See docs/design/rf-map.md section 4. Generated from sonoran/rf/schema.py."
        ),
        # A message with `obs` is a batch, one of kind `spectrum` is a
        # spectrum, one of kind `custom` is a mod's batch, one with
        # `display_name` is a registry entry, and
        # anything else is a heartbeat. Not `oneOf`: a
        # heartbeat ignores unknown fields, so every batch would also pass
        # as one, and `anyOf` would let a batch with bad observations
        # through as a "heartbeat". sonoran itself decides by the topic;
        # this is the same split for a file on its own.
        "if": {"required": ["obs"]},
        "then": {"$ref": "#/$defs/Batch"},
        "else": {
            "if": {"required": ["kind"], "properties": {"kind": {"const": "spectrum"}}},
            "then": {"$ref": "#/$defs/Spectrum"},
            "else": {
                "if": {"required": ["kind"], "properties": {"kind": {"const": "custom"}}},
                "then": {"$ref": "#/$defs/Custom"},
                "else": {
                    "if": {"required": ["display_name"]},
                    "then": {"$ref": "#/$defs/Registry"},
                    "else": {"$ref": "#/$defs/Status"},
                },
            },
        },
        "$defs": top["$defs"],
    }
