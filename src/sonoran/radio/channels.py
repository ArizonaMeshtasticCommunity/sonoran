"""Where each Meshtastic preset sits in the 900 MHz band.

The RF page marks our own channels on a station's waterfall (design
7.4 in `docs/design/rf-map.md`). The frequencies are computed the way
the firmware computes them, never typed in by hand:

    num_channels = floor((freq_end - freq_start) / (spacing + bandwidth))
    slot         = djb2(channel name) % num_channels
    centre       = freq_start + bandwidth / 2 + slot * bandwidth

`RadioInterface::applyModemConfig` in the firmware does this. A channel
that sets `channel_num` uses that slot instead, and a node that renames
its primary channel moves; this module answers for the default names,
which are the preset names.

Only the US region is described. It is the only region this mesh runs.
"""

from dataclasses import dataclass

from sonoran.radio.presets import PRESETS, ModemPreset

# The US 902 to 928 MHz region, with no guard spacing between slots.
US_START_HZ = 902_000_000
US_END_HZ = 928_000_000
US_SPACING_HZ = 0


@dataclass(frozen=True)
class Channel:
    """One preset's channel in the band."""

    name: str
    label: str
    bandwidth_hz: int
    slot: int
    slots: int
    centre_hz: int

    @property
    def low_hz(self) -> int:
        return self.centre_hz - self.bandwidth_hz // 2

    @property
    def high_hz(self) -> int:
        return self.centre_hz + self.bandwidth_hz // 2


def djb2(text: str) -> int:
    """Return the firmware's channel name hash, as a 32 bit unsigned int."""
    value = 5381
    for byte in text.encode("utf-8"):
        value = ((value << 5) + value + byte) & 0xFFFFFFFF
    return value


def channel_for(preset: ModemPreset, name: str | None = None) -> Channel:
    """Return where one preset's default channel sits in the US band."""
    channel_name = name or preset.name
    slots = (US_END_HZ - US_START_HZ) // (US_SPACING_HZ + preset.bandwidth_hz)
    slot = djb2(channel_name) % slots
    centre = US_START_HZ + preset.bandwidth_hz // 2 + slot * preset.bandwidth_hz
    return Channel(
        name=channel_name,
        label=preset.label,
        bandwidth_hz=preset.bandwidth_hz,
        slot=slot,
        slots=slots,
        centre_hz=centre,
    )


def all_channels() -> list[Channel]:
    """Return every preset's default channel, lowest frequency first."""
    return sorted((channel_for(preset) for preset in PRESETS), key=lambda item: item.centre_hz)
