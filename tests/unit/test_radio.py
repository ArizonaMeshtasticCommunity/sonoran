"""Tests for the radio profile of a node.

The figures a prediction needs are not in the mesh. A node reports its
hardware model and nothing else about its radio. These tests pin the
three sources that fill the gap, and the order they beat each other in.

The first test is the important one. The preset table exists twice, once
in Python for the jobs and once in JavaScript for the planner form. Two
copies of the same nine numbers drift.
"""

import json
import math
import re
from pathlib import Path

import pytest

from sonoran.coverage.clutter import terminal_loss_db
from sonoran.coverage.params import DEFAULT_FREQUENCY_MHZ as FREQUENCY
from sonoran.radio.hardware import (
    INTERNAL_ANTENNA_GAIN_DBI,
    STOCK_ANTENNA_GAIN_DBI,
    SX1262_TX_POWER_DBM,
    SX1276_TX_POWER_DBM,
    hardware_profile,
)
from sonoran.radio.overrides import EMPTY, NodeOverride, Overrides, load_overrides, parse_overrides
from sonoran.radio.presets import (
    DEFAULT_NOISE_FIGURE_DB,
    PRESETS,
    noise_floor_dbm,
    preset_by_key,
    preset_for_channel,
    received_dbm_from_snr,
)
from sonoran.radio.resolve import (
    DEFAULT_ANTENNA_HEIGHT_M,
    MAX_CALIBRATION_DB,
    Source,
    resolve_profile,
)

PLANNER_PARAMS = Path("src/sonoran/web/static/planner-params.js")


def _presets_from_javascript() -> dict[str, tuple[float, int]]:
    """Return the sensitivity and bandwidth the planner form holds.

    The file has no build step, so it is read as text. The entries look
    like this:

        { key: 'LONG_FAST', label: 'Long fast', sensitivity: -139,
          bandwidthHz: 250000 },

    The bandwidth joined this in §6.5, where the frequency slot needs it:
    a slot is one bandwidth wide, so the same slot number is a different
    frequency on each preset. It is read here rather than in a case of its
    own because a bandwidth that disagreed with the Python table would
    move a predicted frequency by a whole slot with nothing on screen to
    show it.
    """
    text = PLANNER_PARAMS.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\{\s*key:\s*'([A-Z_]+)',\s*label:\s*'[^']*',\s*sensitivity:\s*(-?[\d.]+),"
        r"\s*bandwidthHz:\s*(\d+)\s*\}"
    )
    return {key: (float(value), int(bandwidth)) for key, value, bandwidth in pattern.findall(text)}


def test_the_python_and_javascript_preset_tables_agree() -> None:
    """The two preset tables must hold the same nine presets.

    The jobs predict with the Python table. The planner form predicts
    with the JavaScript one. A difference between them puts a different
    map on the same page.
    """
    javascript = _presets_from_javascript()
    python = {preset.key: (preset.sensitivity_dbm, preset.bandwidth_hz) for preset in PRESETS}

    assert javascript, "no presets were found in planner-params.js"
    assert javascript == python


def test_preset_lookup_by_key() -> None:
    assert preset_by_key("LONG_FAST") is not None
    assert preset_by_key("LONG_FAST").sensitivity_dbm == -139.0  # type: ignore[union-attr]
    assert preset_by_key("NOT_A_PRESET") is None


@pytest.mark.parametrize(
    "channel",
    ["LongFast", "longfast", "long-fast", "LONG_FAST", "Long Fast"],
)
def test_a_preset_channel_name_is_recognised_however_it_is_written(channel: str) -> None:
    """The channel name arrives from an MQTT topic and is not tidy."""
    preset = preset_for_channel(channel)
    assert preset is not None
    assert preset.key == "LONG_FAST"


@pytest.mark.parametrize("channel", [None, "", "Weather", "PKI", "azmsh"])
def test_a_channel_that_is_not_a_preset_names_no_preset(channel: str | None) -> None:
    """A topic channel rides on a preset. It does not name one.

    See AGENTS.md 9.7. Weather and PKI are the examples this mesh has.
    """
    assert preset_for_channel(channel) is None


def test_the_noise_floor_follows_the_bandwidth() -> None:
    """The floor is thermal noise in the bandwidth, plus the receiver.

    At 250 kHz that is -174 + 54 + 6, which is -114 dBm.
    """
    long_fast = preset_by_key("LONG_FAST")
    assert long_fast is not None
    assert long_fast.bandwidth_hz == 250_000
    assert noise_floor_dbm(long_fast) == pytest.approx(-114.0, abs=0.05)


def test_halving_the_bandwidth_lowers_the_floor_by_three_db() -> None:
    """A narrower channel hears less noise, so it hears further."""
    wide = preset_by_key("LONG_FAST")
    narrow = preset_by_key("LONG_MODERATE")
    assert wide is not None and narrow is not None
    assert wide.bandwidth_hz == 2 * narrow.bandwidth_hz
    difference = noise_floor_dbm(wide) - noise_floor_dbm(narrow)
    assert difference == pytest.approx(10 * math.log10(2), abs=0.01)


def test_an_snr_becomes_a_received_power() -> None:
    """A reported SNR is a ratio against the floor, not a power."""
    long_fast = preset_by_key("LONG_FAST")
    assert long_fast is not None
    floor = noise_floor_dbm(long_fast, DEFAULT_NOISE_FIGURE_DB)
    assert received_dbm_from_snr(-10.0, long_fast) == pytest.approx(floor - 10.0)


# --- hardware ----------------------------------------------------------


def test_a_known_model_is_looked_up_and_not_guessed() -> None:
    profile = hardware_profile("RAK4631")
    assert profile.chipset == "SX1262"
    assert profile.assumed_tx_power_dbm == SX1262_TX_POWER_DBM
    assert profile.inferred is False


def test_a_model_name_is_read_whatever_its_case() -> None:
    assert hardware_profile("heltec_v3").chipset == "SX1262"
    assert hardware_profile("  RAK4631  ").inferred is False


def test_an_unknown_model_gives_figures_and_says_they_are_guessed() -> None:
    """A caller must never have to test for a missing profile."""
    profile = hardware_profile("SOMETHING_RELEASED_NEXT_WEEK")
    assert profile.assumed_tx_power_dbm == SX1262_TX_POWER_DBM
    assert profile.inferred is True


@pytest.mark.parametrize("model", [None, "", "UNSET"])
def test_a_missing_model_gives_the_unknown_profile(model: str | None) -> None:
    assert hardware_profile(model).inferred is True


def test_an_older_board_is_recognised_by_its_name() -> None:
    """The hardware list grows with every firmware release.

    A rule that reads the name keeps a new board out of the unknown
    bucket without an edit to the table.
    """
    profile = hardware_profile("HELTEC_V2_1_SOMETHING")
    assert profile.chipset == "SX1276"
    assert profile.assumed_tx_power_dbm == SX1276_TX_POWER_DBM
    assert profile.inferred is True


def test_a_tracker_has_a_worse_antenna_and_cannot_change_it() -> None:
    profile = hardware_profile("TRACKER_T1000_E")
    assert profile.assumed_antenna_gain_dbi == INTERNAL_ANTENNA_GAIN_DBI
    assert profile.fixed_antenna is True


def test_an_amplified_board_is_not_predicted_at_its_ceiling() -> None:
    """A Station G2 can reach 35 dBm. Few are run there."""
    profile = hardware_profile("STATION_G2")
    assert profile.max_tx_power_dbm == 35.0
    assert profile.assumed_tx_power_dbm < profile.max_tx_power_dbm


# --- overrides ---------------------------------------------------------


def test_an_override_is_read() -> None:
    overrides = parse_overrides(
        """
        nodes:
          "!a1b2c3d4":
            antenna_gain_dbi: 5.8
            antenna_height_m: 12.0
            above_clutter: true
            note: "Rooftop omni."
        """
    )
    node = overrides.for_node("!a1b2c3d4")
    assert node.antenna_gain_dbi == 5.8
    assert node.antenna_height_m == 12.0
    assert node.above_clutter is True
    assert node.note == "Rooftop omni."


def test_a_node_with_no_entry_gets_an_empty_override() -> None:
    assert EMPTY.for_node("!nothing") == NodeOverride()


def test_a_value_outside_its_bounds_is_dropped_and_the_rest_is_kept() -> None:
    """A height in feet reads as a height in metres and is wrong.

    One typed mistake must not empty the whole map.
    """
    overrides = parse_overrides(
        """
        nodes:
          "!a1b2c3d4":
            antenna_height_m: 4000
            antenna_gain_dbi: 5.8
        """
    )
    node = overrides.for_node("!a1b2c3d4")
    assert node.antenna_height_m is None
    assert node.antenna_gain_dbi == 5.8


def test_an_unknown_key_is_dropped_and_the_rest_is_kept() -> None:
    overrides = parse_overrides(
        """
        nodes:
          "!a1b2c3d4":
            antenna_gian_dbi: 5.8
            antenna_height_m: 12.0
        """
    )
    node = overrides.for_node("!a1b2c3d4")
    assert node.antenna_height_m == 12.0
    assert node.antenna_gain_dbi is None


def test_a_number_that_is_not_a_number_is_dropped() -> None:
    overrides = parse_overrides(
        """
        nodes:
          "!a1b2c3d4":
            antenna_gain_dbi: "quite high"
        """
    )
    assert overrides.for_node("!a1b2c3d4").antenna_gain_dbi is None


def test_a_true_is_not_read_as_a_number() -> None:
    """A boolean is an integer in Python. It is not a gain."""
    overrides = parse_overrides(
        """
        nodes:
          "!a1b2c3d4":
            antenna_gain_dbi: true
        """
    )
    assert overrides.for_node("!a1b2c3d4").antenna_gain_dbi is None


@pytest.mark.parametrize(
    "text",
    ["", "nodes:", "[]", "nodes: []", "nodes:\n  '!a': not-a-mapping", "a: [unclosed"],
)
def test_a_file_that_cannot_be_used_gives_no_overrides(text: str) -> None:
    """A broken file must not stop the coverage job."""
    assert parse_overrides(text).for_node("!a1b2c3d4") == NodeOverride()


def test_a_missing_file_gives_no_overrides(tmp_path: Path) -> None:
    """That is the normal state of a new deployment."""
    assert load_overrides(tmp_path / "not-here.yaml") == EMPTY


def test_the_example_overrides_file_in_the_repository_can_be_read() -> None:
    """The file ships commented out. It must still parse."""
    assert load_overrides("config/nodes.yaml") == EMPTY


# --- resolve -----------------------------------------------------------


def test_a_node_with_no_override_uses_its_hardware() -> None:
    profile = resolve_profile("!a1b2c3d4", "RAK4631")
    assert profile.tx_power_dbm == SX1262_TX_POWER_DBM
    assert profile.antenna_gain_dbi == STOCK_ANTENNA_GAIN_DBI
    assert profile.antenna_height_m == DEFAULT_ANTENNA_HEIGHT_M
    assert profile.sources["tx_power_dbm"] == Source.HARDWARE
    assert profile.sources["antenna_height_m"] == Source.DEFAULT


def test_an_override_beats_the_hardware() -> None:
    overrides = Overrides({"!a1b2c3d4": NodeOverride(antenna_gain_dbi=5.8, antenna_height_m=12.0)})
    profile = resolve_profile("!a1b2c3d4", "RAK4631", overrides)
    assert profile.antenna_gain_dbi == 5.8
    assert profile.antenna_height_m == 12.0
    assert profile.sources["antenna_gain_dbi"] == Source.OVERRIDE
    assert profile.sources["antenna_height_m"] == Source.OVERRIDE
    # The power was not overridden, so it still comes from the hardware.
    assert profile.sources["tx_power_dbm"] == Source.HARDWARE


def test_a_guessed_hardware_profile_does_not_claim_to_be_hardware() -> None:
    """A reader must be able to tell a measurement from a guess."""
    profile = resolve_profile("!a1b2c3d4", "SOMETHING_NEW")
    assert profile.hardware_inferred is True
    assert profile.sources["tx_power_dbm"] == Source.DEFAULT


def test_eirp_adds_the_antenna_and_takes_off_the_cable() -> None:
    overrides = Overrides(
        {"!a": NodeOverride(tx_power_dbm=30.0, antenna_gain_dbi=5.8, cable_loss_db=1.5)}
    )
    profile = resolve_profile("!a", "RAK4631", overrides)
    assert profile.eirp_dbm == pytest.approx(34.3)


def test_a_calibration_offset_moves_the_effective_power_only() -> None:
    """The nameplate figure must stay readable beside the measured one."""
    profile = resolve_profile("!a", "RAK4631", calibration_offset_db=-9.0)
    assert profile.effective_eirp_dbm == pytest.approx(profile.eirp_dbm - 9.0)
    assert profile.is_measured is True
    assert profile.sources["calibration_offset_db"] == Source.CALIBRATED


def test_a_calibration_offset_is_clamped() -> None:
    """A fit outside the range is a fault, not a wrong antenna."""
    assert resolve_profile("!a", "RAK4631", calibration_offset_db=-80.0).calibration_offset_db == (
        -MAX_CALIBRATION_DB
    )
    assert resolve_profile("!a", "RAK4631", calibration_offset_db=80.0).calibration_offset_db == (
        MAX_CALIBRATION_DB
    )


def test_a_locked_node_ignores_the_calibration() -> None:
    overrides = Overrides({"!a": NodeOverride(lock_calibration=True)})
    profile = resolve_profile("!a", "RAK4631", overrides, calibration_offset_db=-9.0)
    assert profile.calibration_offset_db == 0.0
    assert profile.locked is True
    assert profile.effective_eirp_dbm == profile.eirp_dbm


def test_no_calibration_yet_is_not_a_correction_of_zero_dressed_up() -> None:
    profile = resolve_profile("!a", "RAK4631")
    assert profile.is_measured is False
    assert profile.sources["calibration_offset_db"] == Source.DEFAULT


def test_the_profile_can_be_written_as_json() -> None:
    """The API returns this. `sources` must survive the trip."""
    profile = resolve_profile("!a1b2c3d4", "RAK4631")
    written = json.dumps({"sources": dict(profile.sources)})
    assert json.loads(written)["sources"]["tx_power_dbm"] == "hardware"


# --- clutter -----------------------------------------------------------
#
# The rule used to live in `radio/resolve.py` and answered with a
# height for the engine to raise the ground by. It now answers with a
# loss in dB, from ITU-R P.2108. The three things it must still get
# right are the same, so the tests stayed and their subject moved.


def test_a_node_in_the_clutter_is_charged_for_it() -> None:
    profile = resolve_profile("!a", "RAK4631")
    assert profile.antenna_height_m == 3.0
    assert terminal_loss_db(10.0, profile.antenna_height_m, FREQUENCY, True) > 0.0


def test_a_node_marked_above_the_clutter_takes_none() -> None:
    """An operator who says the antenna is above the roofs is believed."""
    overrides = Overrides({"!a": NodeOverride(above_clutter=True)})
    profile = resolve_profile("!a", "RAK4631", overrides)
    assert profile.above_clutter is True


def test_a_mast_taller_than_the_clutter_is_above_it_whatever_the_file_says() -> None:
    """A 30 m mast in a street of 10 m houses is not in the clutter."""
    overrides = Overrides({"!a": NodeOverride(antenna_height_m=30.0)})
    profile = resolve_profile("!a", "RAK4631", overrides)
    assert profile.above_clutter is False
    assert terminal_loss_db(10.0, profile.antenna_height_m, FREQUENCY, True) == 0.0


# --- what a role implies about height -----------------------------------


def test_a_router_is_assumed_to_be_on_something() -> None:
    """A router is a sited asset and the point of it was height.

    Three metres describes the shed roof it is not on. Eight is a two
    storey roof or a short pole, and deliberately modest: a wrong guess
    upward draws coverage that is not there.
    """
    profile = resolve_profile("!a", "RAK4631", role="ROUTER")
    assert profile.antenna_height_m == 8.0
    assert profile.sources["antenna_height_m"] == "role"


def test_a_client_keeps_the_plain_default() -> None:
    for role in (None, "CLIENT", "CLIENT_MUTE", "TRACKER"):
        profile = resolve_profile("!a", "RAK4631", role=role)
        assert profile.antenna_height_m == 3.0
        assert profile.sources["antenna_height_m"] == "default"


def test_an_operator_beats_the_assumption() -> None:
    """The role height is a guess. A measured figure is not."""
    overrides = Overrides({"!a": NodeOverride(antenna_height_m=30.0)})
    profile = resolve_profile("!a", "RAK4631", overrides, role="ROUTER")
    assert profile.antenna_height_m == 30.0
    assert profile.sources["antenna_height_m"] == "override"


def test_the_assumption_says_it_is_one() -> None:
    """A number the page prints as a fact must be traceable to one.

    `AGENTS.md` 9.21 says the same about a calibration estimate.
    """
    from sonoran.radio.resolve import ROLE_ANTENNA_HEIGHT_M, Source

    assert Source.ROLE == "role"
    assert set(ROLE_ANTENNA_HEIGHT_M) == {"ROUTER", "ROUTER_LATE", "REPEATER"}


# --- a position an operator gives ---------------------------------------


def test_an_operator_may_give_a_position() -> None:
    """The escape hatch for a broker that rounds a position off.

    Most of the Arizona backbone arrives at 13 bits, which is 2.9 km,
    and cannot anchor a prediction. The operator of a router knows
    where it is.
    """
    overrides = Overrides({"!a": NodeOverride(latitude=33.4484, longitude=-112.0740)})
    assert overrides.position_of("!a") == (33.4484, -112.0740)


def test_half_a_position_is_not_a_place() -> None:
    """A latitude with no longitude is a typing mistake. Using it alone
    would put the node on the Greenwich meridian."""
    assert Overrides({"!a": NodeOverride(latitude=33.4)}).position_of("!a") is None
    assert Overrides({"!a": NodeOverride(longitude=-112.0)}).position_of("!a") is None


def test_a_node_with_no_override_has_no_given_position() -> None:
    assert Overrides({}).position_of("!a") is None


def test_a_position_outside_the_earth_is_refused() -> None:
    from sonoran.radio.overrides import parse_overrides

    text = 'nodes:\n  "!a":\n    latitude: 999.0\n    longitude: -112.0\n'
    assert parse_overrides(text).position_of("!a") is None


# --- a position is checked when the file is read (#315) -----------------
#
# A position in this file makes a node a coverage site. A mistake in one
# must be refused where it is read, with a line that names the node, and
# never half applied.


def test_half_a_position_is_refused_when_the_file_is_read(
    caplog: pytest.LogCaptureFixture,
) -> None:
    text = 'nodes:\n  "!0000abcd":\n    latitude: 33.4\n    antenna_height_m: 12.0\n'
    overrides = parse_overrides(text)
    assert overrides.for_node("!0000abcd").latitude is None
    # The rest of the entry is still a radio fact, and is kept.
    assert overrides.for_node("!0000abcd").antenna_height_m == 12.0
    assert "!0000abcd" in caplog.text
    assert "longitude" in caplog.text


def test_a_position_that_is_not_a_place_is_refused(caplog: pytest.LogCaptureFixture) -> None:
    """Null Island is what an unset position reads as."""
    text = 'nodes:\n  "!0000abcd":\n    latitude: 0.0\n    longitude: 0.0\n'
    assert parse_overrides(text).position_of("!0000abcd") is None
    assert "!0000abcd" in caplog.text


def test_a_half_position_left_by_a_bad_value_is_refused_too() -> None:
    """A longitude out of range is dropped, and the latitude goes with it."""
    text = 'nodes:\n  "!0000abcd":\n    latitude: 33.4\n    longitude: -912.0\n'
    override = parse_overrides(text).for_node("!0000abcd")
    assert override.latitude is None
    assert override.longitude is None


@pytest.mark.parametrize("node_id", ["9d0f9a75", "!9d0f9a7", "!xyz", "Towers 2"])
def test_a_node_id_that_cannot_match_a_node_is_refused(
    node_id: str, caplog: pytest.LogCaptureFixture
) -> None:
    """An entry under a name no node has would be silently never used."""
    text = f'nodes:\n  "{node_id}":\n    latitude: 33.4\n    longitude: -112.0\n'
    assert parse_overrides(text).nodes == {}
    assert node_id in caplog.text


def test_a_node_id_in_capitals_is_read() -> None:
    """The node page prints lower case, and a person may not."""
    text = 'nodes:\n  "!9D0F9A75":\n    latitude: 34.0\n    longitude: -112.7\n'
    assert parse_overrides(text).position_of("!9d0f9a75") == (34.0, -112.7)
