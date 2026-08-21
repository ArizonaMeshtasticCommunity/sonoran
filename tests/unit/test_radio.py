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


def _presets_from_javascript() -> dict[str, float]:
    """Return the preset sensitivities the planner form holds.

    The file has no build step, so it is read as text. The entries look
    like this:

        { key: 'LONG_FAST', label: 'Long fast', sensitivity: -139 },
    """
    text = PLANNER_PARAMS.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\{\s*key:\s*'([A-Z_]+)',\s*label:\s*'[^']*',\s*sensitivity:\s*(-?[\d.]+)\s*\}"
    )
    return {key: float(value) for key, value in pattern.findall(text)}


def test_the_python_and_javascript_preset_tables_agree() -> None:
    """The two preset tables must hold the same nine presets.

    The jobs predict with the Python table. The planner form predicts
    with the JavaScript one. A difference between them puts a different
    map on the same page.
    """
    javascript = _presets_from_javascript()
    python = {preset.key: preset.sensitivity_dbm for preset in PRESETS}

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
