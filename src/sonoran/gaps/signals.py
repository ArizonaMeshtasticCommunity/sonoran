"""What the packet record says about one node, and what it cannot say.

This module is the only place that decides what a gap signal means. It
is the arrangement `positions.py`, `roles.py` and `api/traces.py`
already use: one module holds one rule, so no two pages can disagree
about it. The design is `docs/design/coverage-gaps.md`.

Every function here returns one of three states, and the third one is
`unknown`. **`unknown` is not zero and it is not a pass.** A node that
reports nothing is usually a node that is switched off, not a node in
trouble, and this module refuses to tell the two apart when the data
cannot.

## The load-bearing fact

A packet of node N reaches this database by exactly one of two routes:

- **N uploaded it.** `packet_seen.gateway_node_num = from_node_num`. N
  is an MQTT gateway and uploaded its own traffic. It proves nothing at
  all about radio. See `AGENTS.md` 9.5.1.
- **Some other radio heard it and a gateway uploaded it.**
  `gateway_node_num <> from_node_num`. Whether that gateway heard N
  directly or after any number of relays, a radio received N's
  transmission.

The second route is a positive radio signal that costs nothing and
claims no link. It says *some* radio heard N. It never says which one,
and it never carries an SNR, because the reading on a relayed
observation belongs to the last hop into the gateway and not to N. See
`AGENTS.md` 9.5 and 9.20.

Read backwards it gives the negative: a node whose every upload is its
own upload was heard by no gateway, by any path. That is
`radio_isolated`.

## The observer set is MQTT gateways, and nothing else

`packet_seen` records MQTT uploads, so the only observers this database
can ever hold are gateways. Every other node on the mesh hears plenty
and reports none of it. So "nobody heard this node" always means "no
gateway heard it", and the page must say it in those words. See
`AGENTS.md` 9.5.1.

## The open hole, and why an ambiguous packet is `unknown`

A gateway can rebroadcast MQTT traffic onto the air. If a third gateway
then heard that copy and uploaded it, the second upload would be
evidence for a radio path that N never used. The firmware marks a
packet it took from MQTT and `via_mqtt` is stored, so the copy should
never be uploaded again.

**That is an assertion about firmware behaviour, and this project does
not assert what the vendor did not state.** The vendored `proto/`
directory holds only `UPSTREAM_REV.txt` and `update.sh`, so the
`via_mqtt` and `TransportMechanism` field comments cannot be quoted
from this repository yet. Design section 2.2 makes quoting them, and
measuring the hole with the query in section 11.1, a prerequisite for
trusting the exclusion.

Until both are done this module treats a `via_mqtt` packet as **no
evidence either way**. Such packets are counted as `ambiguous_packets`
and reported in the evidence object. A node whose every packet is
ambiguous reads `unknown`, never `bad`.

`via_mqtt` is also not a per observation fact.
`ingest/pipeline.py` calls `store_mesh_packet_metrics` inside
`if stored.is_new:`, so `mesh_packet_metrics` holds one row for each
unique packet carrying the view of whichever gateway uploaded it
**first**. There is no per observation column to read.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import asin, cos, radians, sin, sqrt
from typing import Any

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sonoran.api import traces
from sonoran.config import Settings
from sonoran.coverage.grid import MIN_LEVEL, to_dbm
from sonoran.db.models import (
    MeshPacketMetrics,
    NeighborMetrics,
    Packet,
    PacketSeen,
    PositionMetrics,
    Traceroute,
)
from sonoran.positions import is_precise_enough, is_usable, precision_deviation_m
from sonoran.radio.presets import ModemPreset, preset_for_channel, required_snr_db

# The three states. There is no fourth, and there is no score.
BAD = "bad"
OK = "ok"
UNKNOWN = "unknown"

# The signals this phase computes, in the order they rank a node.
#
# The order is a fixed severity order and not a weighting. There is no
# 0 to 100 number anywhere in this feature: a score would let two
# `unknown` signals and one `bad` average into amber, and amber reads as
# "a bit broken" when the truth is "we cannot tell". A row's colour
# comes from `worst_state`. See the design, section 5.2.
SIGNAL_ORDER: tuple[str, ...] = (
    "hears_but_is_not_heard",
    "radio_isolated",
    "rf_intermittent",
    "weak_best_link",
    "outside_predicted_usable",
)

# What each signal is called on the page.
SIGNAL_LABELS: dict[str, str] = {
    "hears_but_is_not_heard": "Hears the mesh, not heard back",
    "radio_isolated": "Reaches us only through MQTT",
    "rf_intermittent": "Gets out over the air only sometimes",
    "weak_best_link": "Best measured link has little margin",
    "outside_predicted_usable": "Outside the predicted usable map",
}

# What a signal's `value` is measured in (#265).
#
# StarSkream, relayed by Will: a new user seeing "Yes 0.226" gets nothing
# from it; it took a hover over the evidence to work out that 0.226 was
# 22.6%. The page printed `String(value)` because nothing told it what
# the number was, and the number is a different kind of thing on every
# signal: a share of hours, a margin in dB, a count of gateways, a
# predicted level in dBm.
#
# So the unit is decided here, beside the rule that made the number, and
# travels with it. Every `Signal` that carries a value must name one
# (`Signal.__post_init__` refuses otherwise), and the page formats by
# the unit and never by the signal's name. A value with no unit is not
# printed at all: a bare number is exactly what #265 is about.
FRACTION = "fraction"  # 0 to 1. Drawn as a percentage.
DB = "db"  # A margin in dB. Drawn signed, because below zero is a real answer.
GATEWAYS = "gateways"  # A whole count of gateways.
DBM = "dbm"  # A predicted signal level in dBm.
METRES = "m"  # A distance. Only `position_too_coarse`, which is `unknown`.
UNITS: frozenset[str] = frozenset({FRACTION, DB, GATEWAYS, DBM, METRES})

# The unit a column's heading names, per signal (#265).
#
# `Gets out over the air only sometimes (% of hours heard)`, as the
# suggestion asked. Two signals carry no number at all: their answer is
# the state and the sentence, so their heading has no unit.
SIGNAL_UNIT_LABELS: dict[str, str] = {
    "rf_intermittent": "% of hours heard",
    "weak_best_link": "dB of margin",
    "outside_predicted_usable": "predicted dBm",
}

# What each column means, for somebody who joined the mesh last week
# (#265). The key above the table and the column hints read these.
#
# Three parts each, the three a newcomer asks: what the check looks at,
# what counts as a problem, and what the node's owner can do about it.
# `{...}` fields are filled from the thresholds this run used, so the
# key cannot state a limit the assessment did not apply.
SIGNAL_KEY: dict[str, dict[str, str]] = {
    "hears_but_is_not_heard": {
        "measures": (
            "Whether the node can hear the mesh but the mesh cannot hear it. It can only be "
            "told for a node that publishes neighbor reports, which prove its receiver works."
        ),
        "problem": (
            "Yes when it published at least {min_neighbour_reports} neighbor reports and no "
            "gateway heard it over the air."
        ),
        "owner": (
            "Check the transmit side: the antenna and its cable, the region setting, and that "
            "transmit power is not zero."
        ),
    },
    "radio_isolated": {
        "measures": (
            "Whether any gateway heard the node over the radio, rather than only receiving "
            "its traffic through the node's own internet (MQTT) link."
        ),
        "problem": "Yes when no gateway heard it over the air in this window.",
        "owner": (
            "Check the antenna and the region setting. A node indoors or low down may be "
            "heard by nobody; height and a clear view help most."
        ),
    },
    "rf_intermittent": {
        "measures": (
            "Of the hours the node was awake, the share in which something on the air heard "
            "it. 100% means it was heard in every hour it was awake."
        ),
        "problem": (
            "Yes when that share is below {rf_ratio_bad_pct}. It needs at least "
            "{min_active_hours} awake hours to judge."
        ),
        "owner": (
            "A low share usually means a marginal link. A higher or clearer antenna position, "
            "or a better antenna, helps."
        ),
    },
    "weak_best_link": {
        "measures": (
            "How far the node's best measured link is above the weakest signal this preset "
            "can still decode, in dB. More is better."
        ),
        "problem": "Yes when the margin is below {margin_bad_db} dB.",
        "owner": (
            "Little margin means small changes, such as weather or a parked truck, can break "
            "the link. More height or a better antenna adds margin."
        ),
    },
    "outside_predicted_usable": {
        "measures": (
            "Whether the published coverage prediction reaches the place the node stands. "
            "This is a prediction, not a measurement."
        ),
        "problem": (
            "Yes when the predicted signal there is below what this preset needs. A node "
            "that works anyway shows where the prediction is wrong."
        ),
        "owner": (
            "Nothing, if the node works. If it does not, a better site or a relay nearby "
            "would help."
        ),
    },
}


def signal_key(thresholds: dict[str, object]) -> dict[str, dict[str, str]]:
    """Return the key for every signal, with this run's thresholds filled in.

    A threshold the run did not report is left visible as `unknown`
    rather than dropped, the rule `sentence_for` follows: an unnamed
    value must be visible, not invisible.
    """
    values: dict[str, object] = dict(thresholds)
    ratio = thresholds.get("rf_ratio_bad")
    if isinstance(ratio, int | float) and not isinstance(ratio, bool):
        values["rf_ratio_bad_pct"] = f"{ratio * 100:g}%"
    return {
        name: {part: text.format_map(_Missing(values)) for part, text in parts.items()}
        for name, parts in SIGNAL_KEY.items()
    }


# What the page says for each machine reason. The reason is the short
# name; this is the sentence. Every one of them is a measurement or an
# admission, and none of them is a judgement about a node's owner.
#
# `{gateways_active}` is filled in from the evidence. "None of the 31
# gateways active this week heard it" is a fact. "It is isolated" is an
# accusation, and the difference is the whole point.
REASON_SENTENCES: dict[str, str] = {
    "no_gateway_heard_it": (
        "None of the {gateways_active} gateways active in this window heard it over the "
        "air. Its traffic reaches us through its own internet link."
    ),
    "heard_over_the_air": "At least one gateway heard it over the air.",
    "not_an_mqtt_gateway": (
        "It is not an MQTT gateway, so its packets could only reach us because a radio heard them."
    ),
    "too_few_packets": (
        "It sent fewer than {min_packets} packets in this window. That is too few to "
        "judge, and a quiet node is usually a node that is switched off."
    ),
    "every_packet_ambiguous": (
        "Every packet that reached us came through a gateway that had taken it from "
        "MQTT, so none of it is evidence about radio either way."
    ),
    "receiver_works_transmitter_does_not": (
        "It published {neighbour_reports} neighbor reports with a measured signal, so "
        "its receiver works. None of the {gateways_active} active gateways heard it "
        "over the air. That points at the transmit side: an antenna, a cable, a region "
        "setting, or a power of zero."
    ),
    "no_neighbour_reports": (
        "It published fewer than {min_neighbour_reports} neighbor reports with a "
        "measured signal, so we cannot tell whether its receiver works. The "
        "NeighborInfo module is off on most nodes."
    ),
    "heard_both_ways": (
        "It published {neighbour_reports} neighbor reports with a measured signal, so "
        "its receiver works, and gateways heard it over the air. Both directions are "
        "accounted for."
    ),
    "receiver_works_transmitter_unmeasured": (
        "It published {neighbour_reports} neighbor reports with a measured signal, so "
        "its receiver works. Whether anything heard it over the air is not settled in "
        "this window, so the pair is not judged."
    ),
    "rf_in_few_hours": (
        "In {rf_hours} of the {active_hours} hours it was awake, something on the air "
        "heard it. In the rest, nothing did."
    ),
    "rf_in_most_hours": (
        "In {rf_hours} of the {active_hours} hours it was awake, something on the air heard it."
    ),
    "too_few_active_hours": (
        "It was awake in fewer than {min_active_hours} hours of this window, which is "
        "too few to read a ratio from."
    ),
    "one_gateway_hears_it": (
        "Only one gateway has heard this node directly. That is a statement about where "
        "our gateways are as much as about the mesh."
    ),
    "one_gateway_hears_it_close": (
        "Only one gateway has heard this node directly, and it receives it very "
        "strongly: a median of {direct_rssi_dbm} dBm over {direct_rssi_readings} "
        "packets. A signal that strong comes from a gateway close to the node. One "
        "gateway here says where our gateways are, not that this node has a problem."
    ),
    "several_gateways_hear_it": "{direct_gateways} gateways have heard this node directly.",
    "no_direct_observation": (
        "No gateway has heard it directly. A well connected node several hops deep is "
        "heard directly by nobody, which is normal."
    ),
    "thin_margin": (
        "The best measured link has {value} dB of margin above what this preset needs "
        "to demodulate."
    ),
    "adequate_margin": (
        "The best measured link has {value} dB of margin above what this preset needs "
        "to demodulate."
    ),
    "no_measured_snr": (
        "No measured signal reading exists for it. A neighbor report or a traceroute "
        "hop would give one; an ordinary packet does not."
    ),
    "outside_usable": (
        "The published coverage run does not predict usable coverage where it stands."
    ),
    "inside_usable": "The published coverage run predicts usable coverage where it stands.",
    "no_coverage_run": "No coverage run has been published for this preset yet.",
    "no_usable_position": "It has never reported a position we can place on the ground.",
    "position_too_coarse": (
        "Its position is only accurate to about {value} m. The terrain under a "
        "prediction is 90 m across, so it cannot be placed on the grid."
    ),
    "outside_run_region": "It stands outside the ground the coverage run covered.",
    "diagnostic_run": (
        "The published run is a diagnostic that predicts from nodes which move, so it "
        "cannot answer this."
    ),
}

# What this feature cannot answer at all, in the order the page shows
# them. Each one is a hole in the data and not a thing left to build.
CAVEATS: tuple[tuple[str, str], ...] = (
    (
        "observers_are_gateways_only",
        "The only observers this database holds are MQTT gateways. Every other node on "
        "the mesh hears plenty and reports none of it, so “nobody heard this node” "
        "always means “no gateway heard it”.",
    ),
    (
        "receiving_is_not_observable",
        "We cannot tell whether a node can hear the mesh. A receiver leaves no trace. "
        "The two exceptions are a node that publishes neighbor reports and a node that "
        "answered a traceroute.",
    ),
    (
        "no_relay_topology",
        "We cannot tell which node relayed a packet. The firmware truncates the relay "
        "field to one byte, and only about one observation in twenty resolves to a "
        "single node.",
    ),
    (
        "link_loss_is_not_measurable",
        "We cannot tell whether a link stopped working. A neighbor table decays slowly "
        "and can be truncated to fit a packet, so absence from one is not proof of "
        "silence.",
    ),
    (
        "one_preset_only",
        "This is one modem preset. A node on Long fast cannot hear a node on Medium "
        "fast, so there is no merged view and there never will be.",
    ),
    (
        "prediction_is_uncalibrated",
        "The predicted layer runs on nameplate radio figures. The measured calibration "
        "was rejected as too far out to apply, so no correction is in it.",
    ),
)


@dataclass(frozen=True)
class Signal:
    """One signal about one node, with the evidence it rests on.

    `value` is None unless the signal has a measured number. `reason` is
    a short machine name that `REASON_SENTENCES` turns into a sentence.
    `evidence` holds the counts the claim rests on, so a reader can
    check the claim without opening a database.

    This is the shape `/api/coverage/calibration` already uses for a
    node with thin evidence: listed, with its counts, with a null value.
    """

    state: str
    reason: str
    value: float | None = None
    evidence: dict[str, object] = field(default_factory=dict)
    unit: str | None = None

    def __post_init__(self) -> None:
        """Refuse a number that does not say what it is (#265).

        "Yes 0.226" is what a unitless value looks like on the page. A
        new signal that forgets its unit fails here, where it is made,
        rather than as a bare number in front of a reader.
        """
        if self.value is not None and self.unit not in UNITS:
            raise ValueError(f"signal {self.reason!r} has a value and no known unit: {self.unit!r}")

    def as_dict(self) -> dict[str, object]:
        """Return the signal as the API serves it."""
        return {
            "state": self.state,
            "reason": self.reason,
            "sentence": sentence_for(self.reason, self.value, self.evidence),
            "value": self.value,
            "unit": self.unit,
            "evidence": dict(self.evidence),
        }


def sentence_for(reason: str, value: float | None, evidence: dict[str, object]) -> str:
    """Return the sentence a reason stands for, filled in from the evidence.

    A reason with no sentence returns the reason itself rather than an
    empty string. An unnamed reason must be visible, not invisible.
    """
    template = REASON_SENTENCES.get(reason)
    if template is None:
        return reason
    values: dict[str, object] = {**evidence, "value": value}
    try:
        return template.format_map(_Missing(values))
    except (KeyError, IndexError, ValueError):
        return template


class _Missing(dict[str, object]):
    """A mapping that leaves an unknown placeholder visible."""

    def __missing__(self, key: str) -> str:
        return "unknown"


@dataclass(frozen=True)
class NodeEvidence:
    """Everything the database says about one node on one preset.

    Built by `read_evidence`, which does all of the SQL in a handful of
    aggregate queries. The signal functions below are pure and read only
    this, so every rule can be tested with rows built by hand.
    """

    node_num: int
    # Distinct packets, never rows. One live packet had 22 uploads from
    # 15 gateways, and about 8,200 duplicate `packet` rows survive from
    # before revision 0009. See `docs/ISSUES.md` 1.1.
    packets: int = 0
    # Packets that some radio heard: an upload by a node other than the
    # sender, whose first uploader had not taken it from MQTT.
    rf_packets: int = 0
    # Packets an MQTT rebroadcast could explain. Neither evidence nor a
    # fault. See the module docstring.
    ambiguous_packets: int = 0
    # Hours of our clock in which the node sent at least one packet.
    active_hours: int = 0
    # Of those, the hours in which at least one packet was heard on air.
    rf_hours: int = 0
    # Distinct gateways that heard the node with no hop used, which is
    # rung 3 of the evidence ladder and the only SNR in the packet
    # record that belongs to a real link.
    direct_gateways: int = 0
    best_direct_snr: float | None = None
    # The median RSSI of those direct observations, in dBm, and how many
    # carried one. A gateway that does not report RSSI stores NULL,
    # never 0, so a missing reading is never the loudest one.
    direct_rssi_dbm: float | None = None
    direct_rssi_readings: int = 0
    # Whether the node ever uploaded anything itself. Only a gateway can
    # be `radio_isolated`.
    is_mqtt_gateway: bool = False
    # Neighbour reports the node published itself, which prove its
    # receiver works.
    neighbour_reports: int = 0
    # The best SNR from a neighbour report in either direction.
    best_neighbour_snr: float | None = None
    # Rows that name the node as somebody else's neighbour. A node named
    # by one of these was heard by a real radio.
    named_as_neighbour: int = 0
    # Evidenced traceroute hops that mention the node, read through
    # `api/traces.py`, and the best measured SNR among them.
    trace_hops: int = 0
    best_trace_snr: float | None = None
    # The widest distance between two reported positions, in km.
    position_spread_km: float | None = None

    @property
    def rf_hour_ratio(self) -> float | None:
        """Return the share of awake hours in which a radio heard it."""
        if self.active_hours <= 0:
            return None
        return self.rf_hours / self.active_hours

    @property
    def best_snr_db(self) -> float | None:
        """Return the best measured SNR from any of the three sources.

        Only measured readings, in the order the design sets: a
        neighbour report, a traceroute hop, then a direct observation.
        A relayed observation is never here, because its reading belongs
        to the last hop. A self upload is never here, because it is the
        node's own voice. See `AGENTS.md` 9.5 and 9.5.1.
        """
        readings = [
            value
            for value in (self.best_neighbour_snr, self.best_trace_snr, self.best_direct_snr)
            if value is not None
        ]
        return max(readings) if readings else None


def _on_preset(column: Any, channels: Sequence[str]) -> Any:
    """Return the filter that selects the channels of one preset.

    It is a list and not one name because two spellings of a channel can
    normalise to the same preset: `preset_for_channel` strips case and
    separators, so `longfast` and `LongFast` are one radio setting
    stored two ways. Both belong in one assessment.

    An empty list selects nothing, which is the honest answer for a
    preset no traffic named. It must never fall back to selecting
    everything: that would merge every preset into one, which is the
    thing `AGENTS.md` 9.7 forbids.
    """
    return column.in_(list(channels))


async def read_preset_channels(
    session: AsyncSession, since: datetime, until: datetime
) -> dict[str, list[str]]:
    """Return the channel names that name each preset, from the traffic.

    A node belongs to a preset when it sent traffic seen on it, which is
    the rule `/api/graph/channels` and `/api/map/nodes` already use. It
    is a claim about what a node was doing rather than how it is
    configured, so a genuine dual-preset node appears under both. Live
    data had 14 of those against 709.

    A channel that is not a default preset name rides on top of a preset
    and does not name one. Weather and PKI are the examples this mesh
    has. `preset_for_channel` returns None for those and they are left
    out rather than guessed at.
    """
    names = await session.scalars(
        select(Packet.channel)
        .where(
            Packet.channel.is_not(None),
            Packet.first_seen_at >= since,
            Packet.first_seen_at < until,
        )
        .group_by(Packet.channel)
    )
    found: dict[str, list[str]] = {}
    for name in names.all():
        if name is None:
            continue
        preset = preset_for_channel(name)
        if preset is None:
            continue
        found.setdefault(preset.name, []).append(name)
    return found


def _keys_cte(channels: Sequence[str], since: datetime, until: datetime) -> Select[Any]:
    """Return one row for each distinct packet in the window.

    Grouping by (`from_node_num`, `packet_id`) first is not an
    optimisation. It is the identity of a packet: the surrogate
    `packet.id` cannot be read back, and duplicate `packet` rows survive
    from before revision 0009. See `AGENTS.md` 9.1 and `docs/ISSUES.md`
    1.1.

    The window is bounded at both ends on **our** clock. A node clock
    has been seen nearly 28 hours ahead, and some historical rows still
    carry one, so an unbounded upper end reports hours that have not
    happened. See `AGENTS.md` 9.3 and 9.4.
    """
    return (
        select(
            Packet.from_node_num.label("from_node_num"),
            Packet.packet_id.label("packet_id"),
            func.max(Packet.hop_start).label("hop_start"),
            func.min(Packet.first_seen_at).label("first_seen_at"),
        )
        .where(
            _on_preset(Packet.channel, channels),
            Packet.first_seen_at >= since,
            Packet.first_seen_at < until,
        )
        .group_by(Packet.from_node_num, Packet.packet_id)
    )


async def read_gateways(
    session: AsyncSession, channels: Sequence[str], since: datetime, until: datetime
) -> set[int]:
    """Return the gateways that uploaded anything on this preset.

    The size of this set is how strong a `radio_isolated` claim is, so
    the page prints it: "none of the 31 gateways active this week heard
    it" is a fact a reader can weigh.
    """
    rows = await session.scalars(
        select(PacketSeen.gateway_node_num)
        .where(
            _on_preset(PacketSeen.channel, channels),
            PacketSeen.seen_at >= since,
            PacketSeen.seen_at < until,
        )
        .group_by(PacketSeen.gateway_node_num)
    )
    return set(rows.all())


async def read_evidence(
    session: AsyncSession,
    settings: Settings,
    channels: Sequence[str],
    since: datetime,
    until: datetime,
) -> dict[int, NodeEvidence]:
    """Return the evidence for every node that sent traffic on this preset.

    One preset, always. A node on Long fast cannot hear a node on
    Medium fast, so a merged assessment would invite a reader to fix a
    gap between two radios that have no way to reach each other. See
    `AGENTS.md` 9.7.
    """
    keys = _keys_cte(channels, since, until).cte("gap_keys")

    # One row for each packet, with what the uploads prove about it.
    #
    # `heard_by_other` is rung 4: some radio heard the sender.
    # `direct_by_other` is rung 3: that gateway's receiver closed a link
    # from the sender, and only these carry an SNR that means anything.
    heard_by_other = PacketSeen.gateway_node_num != PacketSeen.from_node_num
    direct_by_other = and_(heard_by_other, PacketSeen.hop_limit == keys.c.hop_start)
    obs = (
        select(
            keys.c.from_node_num.label("from_node_num"),
            keys.c.packet_id.label("packet_id"),
            keys.c.first_seen_at.label("first_seen_at"),
            func.bool_or(heard_by_other).label("heard_by_other"),
            func.max(PacketSeen.rx_snr).filter(direct_by_other).label("best_direct_snr"),
        )
        .select_from(keys)
        .join(
            PacketSeen,
            and_(
                PacketSeen.from_node_num == keys.c.from_node_num,
                PacketSeen.packet_id == keys.c.packet_id,
                PacketSeen.seen_at >= since,
                PacketSeen.seen_at < until,
            ),
        )
        .group_by(keys.c.from_node_num, keys.c.packet_id, keys.c.first_seen_at)
        .cte("gap_obs")
    )

    # `via_mqtt` belongs to whichever gateway uploaded the packet first,
    # because `store_mesh_packet_metrics` runs inside `if stored.is_new:`.
    # There is no per observation column, and a query that reads one
    # would be inventing it.
    first_via_mqtt = func.coalesce(MeshPacketMetrics.via_mqtt, False)
    evidence = (
        select(
            obs.c.from_node_num.label("from_node_num"),
            obs.c.first_seen_at.label("first_seen_at"),
            obs.c.best_direct_snr.label("best_direct_snr"),
            obs.c.heard_by_other.label("heard_by_other"),
            first_via_mqtt.label("first_upload_via_mqtt"),
            and_(obs.c.heard_by_other, first_via_mqtt.is_(False)).label("rf_evidenced"),
        )
        .select_from(obs)
        .join(
            MeshPacketMetrics,
            and_(
                MeshPacketMetrics.from_node_num == obs.c.from_node_num,
                MeshPacketMetrics.packet_id == obs.c.packet_id,
                MeshPacketMetrics.time >= since,
                MeshPacketMetrics.time < until,
            ),
            isouter=True,
        )
        .cte("gap_evidence")
    )

    hour = func.date_trunc("hour", evidence.c.first_seen_at)
    rf_evidenced = evidence.c.rf_evidenced.is_(True)
    ambiguous = and_(evidence.c.heard_by_other, evidence.c.first_upload_via_mqtt.is_(True))
    summary = (
        select(
            evidence.c.from_node_num,
            func.count().label("packets"),
            func.count().filter(rf_evidenced).label("rf_packets"),
            func.count().filter(ambiguous).label("ambiguous_packets"),
            func.count(func.distinct(hour)).label("active_hours"),
            func.count(func.distinct(hour)).filter(rf_evidenced).label("rf_hours"),
            func.max(evidence.c.best_direct_snr).label("best_direct_snr"),
        )
        .group_by(evidence.c.from_node_num)
        .subquery()
    )

    counted = (await session.execute(select(summary))).all()
    wanted = {int(row.from_node_num) for row in counted}

    direct = await _read_direct_gateways(session, channels, since, until)
    gateways = await read_gateways(session, channels, since, until)
    neighbours = await _read_neighbour_evidence(session, channels, since, until)
    named_as = await _read_named_as_neighbour(session, channels, since, until)
    trace = await read_trace_evidence(session, channels, since, until)
    spread = await _read_position_spread(session, since, until, wanted)

    found: dict[int, NodeEvidence] = {}
    for row in counted:
        node_num = int(row.from_node_num)
        # The reporter direction proves this node's own receiver works,
        # so `neighbour_reports` counts only that. The reading is taken
        # from BOTH directions, because one reported link is one
        # measurement of one radio path whichever end wrote it down.
        reports, own_snr = neighbours.get(node_num, (0, None))
        named, their_snr = named_as.get(node_num, (0, None))
        neighbour_snr = _best_of(own_snr, their_snr)
        hops, trace_snr = trace.get(node_num, (0, None))
        direct_gateways, direct_rssi, rssi_readings = direct.get(node_num, (0, None, 0))
        found[node_num] = NodeEvidence(
            node_num=node_num,
            packets=_as_int(row.packets),
            rf_packets=_as_int(row.rf_packets),
            ambiguous_packets=_as_int(row.ambiguous_packets),
            active_hours=_as_int(row.active_hours),
            rf_hours=_as_int(row.rf_hours),
            direct_gateways=direct_gateways,
            direct_rssi_dbm=direct_rssi,
            direct_rssi_readings=rssi_readings,
            best_direct_snr=_as_float(row.best_direct_snr),
            is_mqtt_gateway=node_num in gateways,
            neighbour_reports=reports,
            best_neighbour_snr=neighbour_snr,
            named_as_neighbour=named,
            trace_hops=hops,
            best_trace_snr=trace_snr,
            position_spread_km=spread.get(node_num),
        )
    return found


def _as_int(value: int | None) -> int:
    """Return a count, treating a missing aggregate as zero."""
    return 0 if value is None else int(value)


def _best_of(first: float | None, second: float | None) -> float | None:
    """Return the stronger of two readings, or None when there is none.

    None is not a reading of zero. A missing measurement must never
    become the answer.
    """
    readings = [value for value in (first, second) if value is not None]
    return max(readings) if readings else None


def _as_float(value: float | None) -> float | None:
    """Return a float, or None when the database had nothing.

    None stays None. A missing reading is not a reading of zero.
    """
    return None if value is None else float(value)


async def _read_direct_gateways(
    session: AsyncSession, channels: Sequence[str], since: datetime, until: datetime
) -> dict[int, tuple[int, float | None, int]]:
    """Return how many gateways heard each node with no hop used.

    Also returns the median RSSI of those observations and how many
    carried one. `sole_observer` reads it to tell a gateway beside the
    node from a marginal link.

    Gateways, not rows. One live packet had 22 uploads from 15
    gateways, and 15 is the number that means something. See
    `AGENTS.md` 9.5.1.

    A gateway that is the node itself is excluded on every branch. Such
    a row always has the hop limits equal, so the hop rule alone calls
    it direct and then offers the node's own voice as a link to itself.
    """
    keys = _keys_cte(channels, since, until).cte("gap_direct_keys")
    statement = (
        select(
            keys.c.from_node_num,
            func.count(func.distinct(PacketSeen.gateway_node_num)).label("gateways"),
            func.percentile_cont(0.5).within_group(PacketSeen.rx_rssi).label("rssi"),
            func.count(PacketSeen.rx_rssi).label("rssi_readings"),
        )
        .select_from(keys)
        .join(
            PacketSeen,
            and_(
                PacketSeen.from_node_num == keys.c.from_node_num,
                PacketSeen.packet_id == keys.c.packet_id,
                PacketSeen.seen_at >= since,
                PacketSeen.seen_at < until,
                PacketSeen.gateway_node_num != PacketSeen.from_node_num,
                PacketSeen.hop_limit == keys.c.hop_start,
            ),
        )
        .group_by(keys.c.from_node_num)
    )
    rows = (await session.execute(statement)).all()
    return {
        row.from_node_num: (
            int(row.gateways or 0),
            _as_float(row.rssi),
            int(row.rssi_readings or 0),
        )
        for row in rows
    }


async def _read_neighbour_evidence(
    session: AsyncSession, channels: Sequence[str], since: datetime, until: datetime
) -> dict[int, tuple[int, float | None]]:
    """Return each node's own neighbour reports, and its best reported SNR.

    A node that publishes one of these proves its receiver works, which
    is one of only two ways this database can ever prove that.

    `neighbor_metrics.snr` is measured. It is the strongest evidence of
    a real radio link there is: node A's receiver closed a link from
    node B. Never mix in `NodeFit.offset_db`, which is inferred and not
    reported. See `AGENTS.md` 9.21.
    """
    statement = (
        select(
            NeighborMetrics.node_num,
            func.count().filter(NeighborMetrics.snr.is_not(None)).label("reports"),
            func.max(NeighborMetrics.snr).label("best_snr"),
        )
        .where(
            _on_preset(NeighborMetrics.channel, channels),
            NeighborMetrics.time >= since,
            NeighborMetrics.time < until,
        )
        .group_by(NeighborMetrics.node_num)
    )
    rows = (await session.execute(statement)).all()
    return {row.node_num: (int(row.reports or 0), _as_float(row.best_snr)) for row in rows}


async def _read_named_as_neighbour(
    session: AsyncSession, channels: Sequence[str], since: datetime, until: datetime
) -> dict[int, tuple[int, float | None]]:
    """Return how many reports name each node as somebody else's neighbour.

    A node named by one of these was heard by a real radio, which is
    rung 1 of the evidence ladder. It removes the node from
    `radio_isolated` on its own.

    The reading comes back as well, because a link has two ends and the
    measurement is a measurement whichever end reported it. Node A
    saying it hears B at -8 dB measures the very same radio path as B
    saying it hears A. `weak_best_link` reads both directions for that
    reason.
    """
    statement = (
        select(
            NeighborMetrics.neighbor_node_num,
            func.count().label("rows"),
            func.max(NeighborMetrics.snr).label("best_snr"),
        )
        .where(
            _on_preset(NeighborMetrics.channel, channels),
            NeighborMetrics.time >= since,
            NeighborMetrics.time < until,
        )
        .group_by(NeighborMetrics.neighbor_node_num)
    )
    rows = (await session.execute(statement)).all()
    return {row.neighbor_node_num: (int(row.rows or 0), _as_float(row.best_snr)) for row in rows}


async def read_trace_evidence(
    session: AsyncSession, channels: Sequence[str], since: datetime, until: datetime
) -> dict[int, tuple[int, float | None]]:
    """Return evidenced traceroute hops for each node, and its best hop SNR.

    Read through `api/traces.py` and never re-implemented. Three rules
    apply and each one drew a false link when it was missed: a reply's
    endpoints are the wrong way round, a hop past the end of the reading
    list did not happen, and an unanswered request evidences nothing at
    all. Half of all rows in live data are that last case. See
    `AGENTS.md` 9.6 and 9.18.

    Rows are selected by the window and the preset, never by recency. A
    row limit that decides what evidence exists is the trap in
    `AGENTS.md` 9.19.
    """
    rows = await session.scalars(
        select(Traceroute).where(
            _on_preset(Traceroute.channel, channels),
            Traceroute.seen_at >= since,
            Traceroute.seen_at < until,
        )
    )
    found: dict[int, tuple[int, float | None]] = {}

    def record(node_num: int, snr: float | None) -> None:
        count, best = found.get(node_num, (0, None))
        if snr is not None:
            best = snr if best is None else max(best, snr)
        found[node_num] = (count + 1, best)

    for trace in rows.all():
        for path, readings in (
            (traces.forward_path(trace), trace.snr_towards or []),
            (traces.return_path(trace), trace.snr_back or []),
        ):
            if len(path) < 2:
                continue
            hops, _ = traces.evidenced_hops(path, list(readings))
            for source, target, snr in hops:
                record(source, snr)
                record(target, snr)
    return found


async def _read_position_spread(
    session: AsyncSession, since: datetime, until: datetime, wanted: set[int]
) -> dict[int, float]:
    """Return how far each node's reported positions spread, in km.

    A node whose positions spread is mobile. A mobile node is still
    listed, because a handheld that cannot get out is a real problem for
    its owner. It is the area half of this feature that must leave it
    out, because a footprint drawn to serve a node that moves serves
    nobody tomorrow.

    The spread is measured from the median position to the furthest
    reported one, which is the cheap form and enough to tell a handheld
    from a mast.
    """
    if not wanted:
        return {}
    statement = (
        select(
            PositionMetrics.node_num,
            PositionMetrics.latitude,
            PositionMetrics.longitude,
        )
        .where(
            PositionMetrics.node_num.in_(wanted),
            PositionMetrics.time >= since,
            PositionMetrics.time < until,
            PositionMetrics.latitude.is_not(None),
            PositionMetrics.longitude.is_not(None),
        )
        .order_by(PositionMetrics.node_num)
    )
    seen: dict[int, list[tuple[float, float]]] = {}
    for row in (await session.execute(statement)).all():
        if row.latitude is None or row.longitude is None:
            continue
        seen.setdefault(row.node_num, []).append((float(row.latitude), float(row.longitude)))

    spread: dict[int, float] = {}
    for node_num, points in seen.items():
        if len(points) < 2:
            continue
        latitudes = sorted(point[0] for point in points)
        longitudes = sorted(point[1] for point in points)
        middle = (latitudes[len(latitudes) // 2], longitudes[len(longitudes) // 2])
        spread[node_num] = max(_distance_km(middle, point) for point in points)
    return spread


def _distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
    """Return the great circle distance between two positions, in km."""
    earth_radius_km = 6371.0088
    lat1, lon1 = radians(first[0]), radians(first[1])
    lat2, lon2 = radians(second[0]), radians(second[1])
    half = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * earth_radius_km * asin(min(1.0, sqrt(half)))


# --------------------------------------------------------------- 4.1


def radio_isolated(evidence: NodeEvidence, settings: Settings, gateways_active: int) -> Signal:
    """Present through MQTT, not heard on the air.

    `bad` means: the node is an MQTT gateway, it sent enough packets to
    judge, and no gateway on this mesh heard any of them over the air,
    by any path, directly or after any number of relays. No neighbour
    report names it and no traceroute hop evidences it either.

    **A node that is not a gateway can never be `bad` here**, and
    returns `ok` with the reason `not_an_mqtt_gateway`. Its packets
    could only have reached us because a radio heard them. That is the
    load-bearing fact read backwards, and it removes most of the mesh
    from this signal at no cost.

    The claim scales with how many gateways the mesh has, so
    `gateways_active` travels with it. The page then says "none of the
    31 gateways active this week heard it", which is a fact, rather than
    "it is isolated", which is a judgement.
    """
    counts: dict[str, object] = {
        "packets": evidence.packets,
        "rf_packets": evidence.rf_packets,
        "ambiguous_packets": evidence.ambiguous_packets,
        "direct_gateways": evidence.direct_gateways,
        "named_as_neighbour": evidence.named_as_neighbour,
        "trace_hops": evidence.trace_hops,
        "gateways_active": gateways_active,
        "min_packets": settings.gaps_min_packets,
    }

    if evidence.rf_packets > 0:
        return Signal(OK, "heard_over_the_air", evidence=counts)
    if evidence.named_as_neighbour > 0 or evidence.trace_hops > 0:
        # A real radio closed a link from it, which is stronger evidence
        # than an upload. The signal is about the air, not about MQTT.
        return Signal(OK, "heard_over_the_air", evidence=counts)
    if not evidence.is_mqtt_gateway:
        return Signal(OK, "not_an_mqtt_gateway", evidence=counts)
    if evidence.packets < settings.gaps_min_packets:
        return Signal(UNKNOWN, "too_few_packets", evidence=counts)
    if evidence.ambiguous_packets >= evidence.packets:
        # Every packet could be an MQTT rebroadcast that a second
        # gateway heard on the air. Neither evidence nor a fault.
        return Signal(UNKNOWN, "every_packet_ambiguous", evidence=counts)
    return Signal(BAD, "no_gateway_heard_it", evidence=counts)


# --------------------------------------------------------------- 4.2


def hears_but_is_not_heard(
    evidence: NodeEvidence, settings: Settings, gateways_active: int, isolated: Signal
) -> Signal:
    """The one honest asymmetry this database can prove.

    `bad` means the node satisfies `radio_isolated` **and** it published
    enough neighbour reports with a measured signal to prove its own
    receiver works. Its receiver demonstrably works and its
    transmissions demonstrably reach no gateway. That points at the
    transmit side: a bad antenna, a bad cable, a wrong region setting,
    or a transmit power of zero.

    It is the strongest single finding this feature can produce, and it
    is the only case in which this project will ever say a node cannot
    be heard.

    **The absence of neighbour reports stays `unknown`, never `ok`.**
    That absence is almost always the NeighborInfo module being
    switched off, which says nothing at all about the radio.

    `ok` is for the opposite case, and it is not the same claim. When a
    node published enough measured reports to prove its receiver works
    **and** `radio_isolated` says something heard it over the air, both
    directions are accounted for by measurement. That is precisely what
    the node page promises with "Green when the nodes it hears also
    hear it", so refusing to say it left that promise unkeepable.

    This used to return one reason for every outcome that was not the
    fault, so a node with 379 neighbour reports was told it had
    published "fewer than 2". A reason now belongs to one state only:
    a sentence can no longer describe a state the node is not in.
    """
    counts: dict[str, object] = {
        "neighbour_reports": evidence.neighbour_reports,
        "gateways_active": gateways_active,
        "min_neighbour_reports": settings.gaps_min_neighbour_reports,
        "radio_isolated_state": isolated.state,
    }
    proven_receiver = evidence.neighbour_reports >= settings.gaps_min_neighbour_reports
    if not proven_receiver:
        return Signal(UNKNOWN, "no_neighbour_reports", evidence=counts)
    if isolated.state == BAD:
        return Signal(BAD, "receiver_works_transmitter_does_not", evidence=counts)
    if isolated.state == OK:
        return Signal(OK, "heard_both_ways", evidence=counts)
    # The receiver is proven and the other half is not settled. Saying
    # `ok` here would claim a measurement nobody made.
    return Signal(UNKNOWN, "receiver_works_transmitter_unmeasured", evidence=counts)


# --------------------------------------------------------------- 4.3


def rf_intermittent(evidence: NodeEvidence, settings: Settings) -> Signal:
    """Sometimes gets out over the air, sometimes not.

    Link stability is not measurable from this database, so this
    measures something that is: of the hours in which the node was
    awake, in how many did anything on the air hear it?

    Read it as "in half the hours it was awake, nothing on the air heard
    it". That is an unstable connection to the mesh stated in terms of
    evidence, rather than in terms of a link nobody measured.

    The ratio is over **hours and not packets**, because one chatty hour
    would otherwise decide the answer. It is a ratio within the node and
    never a rate across nodes, because two nodes with different
    broadcast intervals are not comparable on an hour count.
    """
    ratio = evidence.rf_hour_ratio
    counts: dict[str, object] = {
        "active_hours": evidence.active_hours,
        "rf_hours": evidence.rf_hours,
        "packets": evidence.packets,
        "ambiguous_packets": evidence.ambiguous_packets,
        "min_active_hours": settings.gaps_min_active_hours,
    }
    if ratio is None or evidence.active_hours < settings.gaps_min_active_hours:
        return Signal(UNKNOWN, "too_few_active_hours", evidence=counts)
    # Not rounded here (#265). Rounding to three places turned a share
    # just short of every hour into 1.0, and the page would then print
    # "100%" -- a perfect score nobody measured. The page rounds for
    # display and says ">99.9%" for that case.
    value = ratio
    if ratio < settings.gaps_rf_ratio_bad:
        return Signal(BAD, "rf_in_few_hours", value=value, evidence=counts, unit=FRACTION)
    return Signal(OK, "rf_in_most_hours", value=value, evidence=counts, unit=FRACTION)


# --------------------------------------------------------------- 4.4






# --------------------------------------------------------------- 4.5


def weak_best_link(evidence: NodeEvidence, settings: Settings, preset: ModemPreset) -> Signal:
    """The best measured link has little margin.

    The margin is the SNR above what the preset needs to demodulate:

        required_snr_db(preset) = preset.sensitivity_dbm - noise_floor_dbm(preset)
        snr_margin_db           = snr - required_snr_db(preset)

    For Long fast the required SNR is near -25 dB, which is why a
    reported SNR of -20 dB is a working link with 5 dB to spare and not
    a broken one. A raw SNR cannot be read without the preset beside it.

    The **best** link is the right statistic. A node with one strong
    link and twenty weak ones is fine.

    `unknown` when there is no measured reading at all, which will be
    the common state: an ordinary packet carries no reading that belongs
    to the sender's link.
    """
    required = required_snr_db(preset)
    snr = evidence.best_snr_db
    counts: dict[str, object] = {
        "best_snr_db": None if snr is None else round(snr, 2),
        "required_snr_db": round(required, 2),
        "neighbour_reports": evidence.neighbour_reports,
        "trace_hops": evidence.trace_hops,
        "direct_gateways": evidence.direct_gateways,
        "margin_bad_db": settings.gaps_margin_bad_db,
        "sources": [
            name
            for name, value in (
                ("neighbour_report", evidence.best_neighbour_snr),
                ("traceroute_hop", evidence.best_trace_snr),
                ("direct_observation", evidence.best_direct_snr),
            )
            if value is not None
        ],
    }
    if snr is None:
        return Signal(UNKNOWN, "no_measured_snr", evidence=counts)
    margin = round(snr - required, 2)
    if margin < settings.gaps_margin_bad_db:
        return Signal(BAD, "thin_margin", value=margin, evidence=counts, unit=DB)
    return Signal(OK, "adequate_margin", value=margin, evidence=counts, unit=DB)


# --------------------------------------------------------------- 4.6


@dataclass(frozen=True)
class CoverageLevels:
    """The level the published coverage run predicted at each node.

    Read from `coverage-at-nodes.json`, which the coverage job samples
    out of the region grids while they are still in memory. A finished
    run keeps no level grid: only colour ramped PNG tiles survive, and a
    tile entirely below the threshold is never written at all, so the
    exact dBm at a point cannot be recovered from disk afterwards.
    """

    stamp: str | None = None
    site_set: str = "infrastructure"
    is_diagnostic: bool = False
    available: bool = False
    threshold_level: int = 0
    # Node number as a string, because JSON keys are strings, to the
    # sampled level of each layer.
    levels: dict[str, dict[str, int]] = field(default_factory=dict)

    def level_of(self, node_num: int, layer: str = "usable") -> int | None:
        """Return the sampled level, or None when the node is absent.

        **Absent is not zero.** A node outside the region grid is absent
        from the artefact, and that means unknown. A stored zero means
        the run reached that cell and found nothing there, which is
        `grid.NO_COVERAGE` and a real answer.
        """
        holder = self.levels.get(str(node_num))
        if holder is None:
            return None
        value = holder.get(layer)
        return None if value is None else int(value)


def outside_predicted_usable(
    node_num: int,
    coverage: CoverageLevels,
    position_confidence: str,
    deviation_m: float | None,
) -> Signal:
    """The prediction does not reach it.

    This is the one signal in phase 1 that reads a prediction rather
    than a measurement, and the page must never draw the two in the
    same colour.

    `unknown` when there is no published run for the preset, when the
    node has no usable position, when the position is known to be
    coarse, or when the published run is a diagnostic. A
    `precision_deviation_m` of 2.9 km cannot be placed on a 90 m grid,
    and a diagnostic run predicts from client nodes that move. See
    `AGENTS.md` 9.25 and 9.27.
    """
    counts: dict[str, object] = {
        "stamp": coverage.stamp,
        "site_set": coverage.site_set,
        "threshold_level": coverage.threshold_level,
        "position_confidence": position_confidence,
    }
    if not coverage.available:
        return Signal(UNKNOWN, "no_coverage_run", evidence=counts)
    if coverage.is_diagnostic:
        return Signal(UNKNOWN, "diagnostic_run", evidence=counts)
    if position_confidence == "none":
        return Signal(UNKNOWN, "no_usable_position", evidence=counts)
    if position_confidence == "coarse":
        return Signal(
            UNKNOWN,
            "position_too_coarse",
            value=None if deviation_m is None else round(deviation_m, 1),
            evidence={**counts, "deviation_m": deviation_m},
            unit=METRES,
        )
    level = coverage.level_of(node_num)
    if level is None:
        return Signal(UNKNOWN, "outside_run_region", evidence=counts)
    counts["level"] = level
    # The value is the predicted level in dBm, not the engine's byte
    # (#265). The byte carries a 200 dB offset (`coverage/grid.py`), so
    # it printed as "62" for -138 dBm. A byte of zero means the run
    # reached the cell and predicted nothing there, which has no dBm at
    # all: that is `None`, never -200 dBm, and the sentence says it.
    predicted = to_dbm(level) if level >= MIN_LEVEL else None
    unit = None if predicted is None else DBM
    if level < coverage.threshold_level:
        return Signal(BAD, "outside_usable", value=predicted, evidence=counts, unit=unit)
    return Signal(OK, "inside_usable", value=predicted, evidence=counts, unit=unit)


# --------------------------------------------------------------- 4.8


def is_mobile(evidence: NodeEvidence, settings: Settings) -> bool:
    """Return true when the node's reported positions spread too far.

    Mobile is a modifier and not a fault. A handheld that cannot get out
    is a real problem for its owner, so a mobile node stays in the per
    node list. It is the area half that must leave it out.
    """
    spread = evidence.position_spread_km
    return spread is not None and spread > settings.gaps_mobile_spread_km


# --------------------------------------------------------------- 5.2


def worst_state(signals: dict[str, Signal]) -> str:
    """Return the worst state among a node's signals.

    A row's colour comes from this and never from a number. A node with
    no `bad` signal and at least one `unknown` is **not** healthy: it is
    unmeasured, and the page says so.
    """
    states = {signal.state for signal in signals.values()}
    if BAD in states:
        return BAD
    if UNKNOWN in states:
        return UNKNOWN
    return OK


def rank_key(row: dict[str, object]) -> tuple[object, ...]:
    """Return the sort key of one assessed node, worst first.

    Three terms, in this order: how many signals are `bad`, then a fixed
    severity order between the signals, then how many packets the node
    sent, so a node we know a lot about sorts above one we barely know.

    None of the three is a score. See the design, section 5.2.
    """
    signals = row.get("signals")
    bad_names: set[str] = set()
    if isinstance(signals, dict):
        bad_names = {
            name
            for name, signal in signals.items()
            if isinstance(signal, dict) and signal.get("state") == BAD
        }
    severity = next(
        (index for index, name in enumerate(SIGNAL_ORDER) if name in bad_names),
        len(SIGNAL_ORDER),
    )
    return (
        -_count_of(row.get("bad_count")),
        severity,
        -_count_of(row.get("packets")),
        str(row.get("node_id") or ""),
    )


def _count_of(value: object) -> int:
    """Return a count read out of a plain dict, or zero."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def position_confidence(
    latitude: float | None,
    longitude: float | None,
    precision_bits: int | None,
    minimum_bits: int,
) -> tuple[str, float | None]:
    """Return how well a node's position is known, and by how much.

    `exact`, `coarse` or `none`. A missing precision counts as exact,
    which is the decision `positions.is_precise_enough` exists to make:
    a node that sent no precision field at all is the ordinary case for
    a node heard directly over the radio, and it is full precision.
    """
    if not is_usable(latitude, longitude):
        return "none", None
    deviation = precision_deviation_m(precision_bits)
    if not is_precise_enough(precision_bits, minimum_bits):
        return "coarse", deviation
    return "exact", deviation


def window_bounds(settings: Settings, hours: int | None = None) -> tuple[datetime, datetime]:
    """Return the window to measure over, bounded at both ends.

    The upper bound is our clock now. It is not optional: a node clock
    has been seen nearly 28 hours ahead, some historical rows still
    carry one, and an unbounded window reports hours that have not
    happened yet. See `AGENTS.md` 9.4 and `docs/ISSUES.md` 1.5.
    """
    span = max(1, hours if hours is not None else settings.gaps_window_hours)
    until = datetime.now(UTC)
    return until - timedelta(hours=span), until


def assess(
    evidence: NodeEvidence,
    settings: Settings,
    preset: ModemPreset,
    gateways_active: int,
    coverage: CoverageLevels,
    confidence: str,
    deviation_m: float | None,
) -> dict[str, Signal]:
    """Return every phase 1 signal for one node on one preset.

    The order of the returned mapping is `SIGNAL_ORDER`, which is the
    severity order the page and the ranking both use.
    """
    isolated = radio_isolated(evidence, settings, gateways_active)
    return {
        "hears_but_is_not_heard": hears_but_is_not_heard(
            evidence, settings, gateways_active, isolated
        ),
        "radio_isolated": isolated,
        "rf_intermittent": rf_intermittent(evidence, settings),
        "weak_best_link": weak_best_link(evidence, settings, preset),
        "outside_predicted_usable": outside_predicted_usable(
            evidence.node_num, coverage, confidence, deviation_m
        ),
    }


def reached_but_unpredicted(signals: dict[str, Signal], evidence: NodeEvidence) -> bool:
    """Return true when a node the air reached sits outside the prediction.

    **This is a finding about the map, not about the node.** A node that
    something on the air heard, standing where the model predicts no
    usable coverage, is coverage the model missed.
    `tools/validate_coverage.py` measures the same thing from outside
    and puts it near 11 percent. It tells a reader where the prediction
    is pessimistic.
    """
    outside = signals.get("outside_predicted_usable")
    return bool(evidence.rf_packets > 0 and outside is not None and outside.state == BAD)


__all__ = [
    "BAD",
    "CAVEATS",
    "OK",
    "SIGNAL_LABELS",
    "SIGNAL_ORDER",
    "UNKNOWN",
    "CoverageLevels",
    "NodeEvidence",
    "Signal",
    "assess",
    "hears_but_is_not_heard",
    "is_mobile",
    "outside_predicted_usable",
    "position_confidence",
    "radio_isolated",
    "rank_key",
    "reached_but_unpredicted",
    "read_evidence",
    "read_gateways",
    "read_preset_channels",
    "read_trace_evidence",
    "rf_intermittent",
    "sentence_for",
    "weak_best_link",
    "window_bounds",
    "worst_state",
]
