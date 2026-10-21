"""Firmware 2.8.1: the protobufs, and the presets firmware has (#362).

The sensitivities are 22 dBm minus the Meshtastic docs' link budgets;
`radio/presets.py` names the source beside the table.

The channel names, spreading factors and bandwidths below are firmware's
own: `DisplayFormatters::getModemPresetDisplayName` and
`modemPresetToParams` (`src/mesh/MeshRadio.h`) at firmware v2.8.1.8e6a88d.
"""

import asyncio
from pathlib import Path

import pytest

from sonoran.api.routes import leaderboards
from sonoran.meshtastic import mesh_pb2, portnums_pb2, telemetry_pb2
from sonoran.radio.presets import (
    PRESETS,
    RECOGNISED_ONLY,
    modelled,
    preset_by_key,
    preset_for_channel,
    required_snr_db,
    sensitivity_of,
)

ROOT = Path(__file__).resolve().parents[2]

# (key, firmware channel name, spreading factor, bandwidth in Hz)
FIRMWARE = [
    ("SHORT_TURBO", "ShortTurbo", 7, 500_000),
    ("SHORT_FAST", "ShortFast", 7, 250_000),
    ("SHORT_SLOW", "ShortSlow", 8, 250_000),
    ("MEDIUM_FAST", "MediumFast", 9, 250_000),
    ("MEDIUM_SLOW", "MediumSlow", 10, 250_000),
    ("MEDIUM_TURBO", "MediumTurbo", 9, 500_000),
    ("LONG_TURBO", "LongTurbo", 11, 500_000),
    ("LONG_MODERATE", "LongMod", 11, 125_000),
    ("LONG_SLOW", "LongSlow", 12, 125_000),
    ("LITE_FAST", "LiteFast", 9, 125_000),
    ("LITE_SLOW", "LiteSlow", 10, 125_000),
    ("NARROW_FAST", "NarrowFast", 7, 62_500),
    ("NARROW_SLOW", "NarrowSlow", 8, 62_500),
    ("TINY_FAST", "TinyFast", 7, 15_600),
    ("TINY_SLOW", "TinySlow", 8, 15_600),
    ("LONG_FAST", "LongFast", 11, 250_000),
]


@pytest.mark.parametrize(("key", "name", "sf", "bandwidth"), FIRMWARE)
def test_every_firmware_preset_is_recognised_by_its_channel_name(
    key: str, name: str, sf: int, bandwidth: int
) -> None:
    """A topic named after a preset is that preset, whatever this table models."""
    preset = preset_for_channel(name)
    assert preset is not None, f"{name} is a preset firmware has"
    assert preset is preset_by_key(key)
    assert (preset.name, preset.spreading_factor, preset.bandwidth_hz) == (name, sf, bandwidth)


def test_long_moderate_keeps_its_old_spelling() -> None:
    """Sonoran spelled it LongModerate before it followed firmware's LongMod."""
    assert preset_for_channel("LongModerate") is preset_for_channel("LongMod")


def test_the_long_turbo_default_of_2_8_is_tagged_not_dropped() -> None:
    """2.8 makes LongTurbo the US default. Its topic is a preset, not a channel."""
    preset = preset_for_channel("LongTurbo")
    assert preset is not None and preset.key == "LONG_TURBO"


def test_a_preset_with_no_source_has_no_sensitivity_and_is_never_drawn() -> None:
    """Long slow and Very long slow have no docs budget. No figure is made up."""
    assert {preset.key for preset in RECOGNISED_ONLY} == {"LONG_SLOW", "VERY_LONG_SLOW"}
    for preset in RECOGNISED_ONLY:
        assert preset.sensitivity_dbm is None, preset.key
        assert modelled(preset) is None
        with pytest.raises(ValueError):
            sensitivity_of(preset)
        with pytest.raises(ValueError):
            required_snr_db(preset)
        assert preset not in PRESETS, "a picker would offer a preset it cannot draw"
    assert all(modelled(preset) is preset for preset in PRESETS)


def test_the_link_board_never_reads_a_missing_sensitivity_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It used to read no preset as a required SNR of 0 dB."""

    from datetime import UTC, datetime

    from sonoran.api.routes.graph import TWO_WAY, Edge

    # A strong two-way link: plenty of samples each way, and 20 dB of SNR.
    strong = Edge(
        source=1, target=2, kind="neighbor", snr=20.0, time=datetime.now(UTC), forward=9, backward=9
    )
    assert strong.strength == TWO_WAY, "the link must be one the board would rank"

    async def edges(*_: object) -> dict[object, object]:
        return {("a", "b"): strong}

    async def nothing(*_: object) -> dict[object, object]:
        return {}

    async def positions(*_: object) -> dict[int, tuple[float, float]]:
        return {1: (33.4, -112.0), 2: (33.5, -112.0)}

    async def names(*_: object) -> dict[int, str]:
        return {}

    monkeypatch.setattr(leaderboards, "_traceroute_edges", edges)
    monkeypatch.setattr(leaderboards, "_neighbor_edges", nothing)
    monkeypatch.setattr(leaderboards, "exact_positions", positions)
    monkeypatch.setattr(leaderboards, "resolve_names", names)

    async def nothing_stored(*_: object) -> None:
        return None

    # No database here: the board computes its links (#371).
    monkeypatch.setattr(leaderboards, "read_links", nothing_stored)
    board = asyncio.run(leaderboards._link_board(None, "LongSlow", 5.0))  # type: ignore[arg-type]
    assert board["rows"] == [], "an unmodelled preset gave a link a margin"
    # The control: on a modelled preset the same link is ranked.
    control = asyncio.run(leaderboards._link_board(None, "LongFast", 5.0))  # type: ignore[arg-type]
    assert len(control["rows"]) == 1


def test_the_protobufs_are_firmware_2_8_1() -> None:
    assert (ROOT / "proto" / "UPSTREAM_REV.txt").read_text().strip() == (
        "8017acbb0828703e980323bee3dd605fb7366058"
    ), "the pin is the commit the v2.8.1 tag names"
    assert portnums_pb2.PortNum.Value("PAGING_APP") == 38
    assert "soil_water_metrics" in telemetry_pb2.Telemetry.DESCRIPTOR.fields_by_name
    packet = mesh_pb2.MeshPacket.DESCRIPTOR.fields_by_number
    assert (packet[23].name, packet[24].name) == ("ack_proof_status", "slot_parity")


def test_data_did_not_change_so_no_genuine_packet_can_fail_the_round_trip() -> None:
    """#252: a `Data` field the schema does not know makes real packets fail.

    2.8.1 added none. If a future update does, this names it before a
    packet is lost.
    """
    fields = sorted((f.number, f.name) for f in mesh_pb2.Data.DESCRIPTOR.fields)
    assert fields == [
        (1, "portnum"),
        (2, "payload"),
        (3, "want_response"),
        (4, "dest"),
        (5, "source"),
        (6, "request_id"),
        (7, "reply_id"),
        (8, "emoji"),
        (9, "bitfield"),
        (10, "xeddsa_signature"),
    ]


def test_every_sensitivity_is_the_docs_budget_at_22_dbm() -> None:
    """#362: the docs' link budgets assume 22 dBm, so 22 minus the budget."""
    budgets = {
        "SHORT_TURBO": 140, "SHORT_FAST": 143, "SHORT_SLOW": 145.5, "MEDIUM_TURBO": 145,
        "MEDIUM_FAST": 148, "MEDIUM_SLOW": 150.5, "LONG_TURBO": 150, "LONG_FAST": 153,
        "LONG_MODERATE": 156, "LITE_FAST": 151, "LITE_SLOW": 153.5, "NARROW_FAST": 149,
        "NARROW_SLOW": 151.5, "TINY_FAST": 155, "TINY_SLOW": 157.5,
    }  # fmt: skip
    assert {preset.key: 22 - preset.sensitivity_dbm for preset in PRESETS} == budgets  # type: ignore[operator]
    assert preset_for_channel("LongFast").sensitivity_dbm == -131.0  # type: ignore[union-attr]
