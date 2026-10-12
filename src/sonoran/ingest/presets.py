"""The modem preset of each observation and packet, decided at ingest (#313).

A topic channel is not a modem preset. `azmsh`, `Weather` and `PKI`
ride on top of whatever preset the gateway is set to, and this mesh
runs `azmsh` on both MediumFast and LongFast. So the channel name in
the topic cannot say which preset carried a packet. The gateway can.
Firmware names an unnamed primary channel after its preset, so a
gateway that uploads on `.../e/LongFast/!gw` is set to LongFast.

This module holds that knowledge in memory. It touches no database.
`ingest/preset_writes.py` stores what it decides.

The interface is three calls, in this order for each MQTT message:

1. `observe(gateway, topic_channel, at)` before the packet is stored.
   It returns the preset of this observation, for
   `packet_seen.modem_preset`, and the preset to store as the
   gateway's `node.uplink_preset`, when the topic named one.
2. `vote(from_node, packet_id, preset, at, is_new)` after the packet
   is stored. It returns a `PacketPreset` when the majority of the
   packet's observations changed, else None.
3. `seed(gateway, preset, at)` once at start, from `node.uplink_preset`,
   so that a restart does not forget every gateway.

The rules:

- **One observation.** A preset-named topic is its own preset.
  Otherwise the preset is the gateway's current preset. Otherwise it
  is unknown (None).
- **One gateway.** The current preset is the preset of its newest
  preset-named upload, so a reconfigured gateway switches at once. It
  is ambiguous, and has no current preset, while it has uploaded two
  different presets within `conflict_window`. That is a flapping or
  misconfigured node, not a reconfiguration.
- **One packet.** The packet takes the majority of its observations.
  An unknown observation does not vote. A tie keeps the value that is
  already stored.

The tally of each packet lives for `tally_ttl` and holds at most
`tally_size` packets. Repeats from other gateways arrive within
seconds, so that is enough. A packet whose tally is gone, after a
restart for example, starts a new tally at its next observation.
"""

from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sonoran.radio.presets import preset_for_channel

#: How long the votes of one packet are kept.
DEFAULT_TALLY_TTL = timedelta(minutes=10)

#: How many packets the tally holds. This mesh carries about 7 packets a
#: second at its busiest, so ten minutes is about 4,200 packets.
DEFAULT_TALLY_SIZE = 50_000


@dataclass(frozen=True)
class Observation:
    """What one MQTT upload says about modem presets."""

    #: The preset of this observation, or None when unknown.
    preset: str | None
    #: The preset the topic itself named, to store as the gateway's
    #: `uplink_preset`. None for a topic channel.
    uplink: str | None


@dataclass(frozen=True)
class PacketPreset:
    """A new majority preset for one packet."""

    preset: str
    #: The packet's `first_seen_at` when `exact`. Otherwise the time of
    #: the observation that started the tally, which is an upper bound.
    first_seen_at: datetime
    #: True when this process stored the packet and knows its time.
    exact: bool
    #: True when the INSERT of the packet already wrote this preset.
    inserted: bool


@dataclass
class _Tally:
    first_seen_at: datetime
    exact: bool
    counts: Counter[str] = field(default_factory=Counter)
    majority: str | None = None


class PresetTracker:
    """The memory that ingest keeps about gateways and recent packets."""

    def __init__(
        self,
        conflict_window: timedelta,
        tally_ttl: timedelta = DEFAULT_TALLY_TTL,
        tally_size: int = DEFAULT_TALLY_SIZE,
    ) -> None:
        self._window = conflict_window
        self._ttl = tally_ttl
        self._size = tally_size
        # gateway -> preset name -> newest upload on a topic of that name
        self._gateways: dict[int, dict[str, datetime]] = {}
        self._tallies: OrderedDict[tuple[int, int], _Tally] = OrderedDict()

    def seed(self, gateway: int, preset: str | None, at: datetime | None) -> None:
        """Remember a gateway's stored preset. A newer live upload wins."""
        known = preset_for_channel(preset)
        if known is None or at is None:
            return
        self._remember(gateway, known.name, at)

    def observe(self, gateway: int, channel: str | None, at: datetime) -> Observation:
        """Return the preset of one upload, and learn from its topic."""
        named = preset_for_channel(channel)
        if named is not None:
            self._remember(gateway, named.name, at)
            return Observation(preset=named.name, uplink=named.name)
        return Observation(preset=self._current(gateway, at), uplink=None)

    def vote(
        self,
        from_node: int,
        packet_id: int,
        preset: str | None,
        at: datetime,
        is_new: bool,
    ) -> PacketPreset | None:
        """Count one observation, and return the new majority if it changed."""
        tally = self._tally(from_node, packet_id, at, is_new)
        if preset is None:
            return None
        tally.counts[preset] += 1
        before = tally.majority
        if before is not None and tally.counts[preset] <= tally.counts[before]:
            return None
        tally.majority = preset
        return PacketPreset(
            preset=preset,
            first_seen_at=tally.first_seen_at,
            exact=tally.exact,
            inserted=is_new,
        )

    @property
    def tally_ttl(self) -> timedelta:
        """Return how long the votes of one packet are kept."""
        return self._ttl

    def tally_count(self) -> int:
        """Return how many packets the tally holds now."""
        return len(self._tallies)

    def _remember(self, gateway: int, preset: str, at: datetime) -> None:
        heard = self._gateways.setdefault(gateway, {})
        if preset not in heard or heard[preset] < at:
            heard[preset] = at
        # Keep the newest preset, and any other still inside the window.
        newest = max(heard.values())
        for name in [name for name, when in heard.items() if when < newest - self._window]:
            del heard[name]

    def _current(self, gateway: int, at: datetime) -> str | None:
        heard = self._gateways.get(gateway)
        if not heard:
            return None
        newest = max(heard, key=lambda name: heard[name])
        floor = at - self._window
        if any(when >= floor for name, when in heard.items() if name != newest):
            return None
        return newest

    def _tally(self, from_node: int, packet_id: int, at: datetime, is_new: bool) -> _Tally:
        self._expire(at)
        key = (from_node, packet_id)
        tally = self._tallies.get(key)
        if is_new or tally is None:
            tally = _Tally(first_seen_at=at, exact=is_new)
            self._tallies.pop(key, None)
            self._tallies[key] = tally
            while len(self._tallies) > self._size:
                self._tallies.popitem(last=False)
        return tally

    def _expire(self, at: datetime) -> None:
        floor = at - self._ttl
        while self._tallies:
            oldest = next(iter(self._tallies.values()))
            if oldest.first_seen_at >= floor:
                return
            self._tallies.popitem(last=False)
