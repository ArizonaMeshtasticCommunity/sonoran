"""Every number on the gaps page says what it is (#265, suggested by StarSkream).

"New user seeing 'Yes 0.226' doesn't add value at the surface level. It
wasn't until I did a hover to see Uptime and Seen time then realizing
that 0.226 is the decimal percentage (22.6%)."

The page printed `String(signal.value)`, and the value is a share of
hours on one signal, a margin in dB on another, a count of gateways on a
third and an engine byte on a fourth. The fix has three halves, and each
is pinned here:

1. The unit is decided in `gaps/signals.py`, beside the rule that made
   the number, and a value cannot be constructed without one.
2. The page formats by that unit in one function, `formatValue`, which
   `js/gaps_value_cases.mjs` runs under node.
3. The page carries a key: what each column measures, what counts as a
   problem, and what the owner can do.
"""

import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sonoran.api.routes.gaps import gaps_summary
from sonoran.config import Settings
from sonoran.gaps import signals
from sonoran.gaps.signals import BAD, OK, CoverageLevels, NodeEvidence, Signal
from sonoran.radio.presets import preset_for_channel
from tests.unit.job_outputs import JobOutputs

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "tests" / "unit" / "js" / "gaps_value_cases.mjs"
STATIC = ROOT / "src" / "sonoran" / "web" / "static"


def _settings(**extra: object) -> Settings:
    return Settings(_env_file=None, **extra)  # type: ignore[arg-type]


def test_the_formatting_cases_pass_under_node() -> None:
    """StarSkream's example, the 100% rule and absent-is-not-zero, run."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([str(node), str(CASES)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "0.226 reads as 22.6%" in done.stdout, "the cases did not run StarSkream's example"


# --- 1. a value cannot exist without its unit --------------------------


def test_a_value_without_a_unit_cannot_be_made() -> None:
    """The next signal to forget its unit fails where it is built."""
    with pytest.raises(ValueError, match="no known unit"):
        Signal(BAD, "rf_in_few_hours", value=0.226)
    with pytest.raises(ValueError, match="no known unit"):
        Signal(BAD, "rf_in_few_hours", value=0.226, unit="furlongs")
    # Positive control: a signal with no number needs no unit, and one
    # with both is fine. Without these the check above could be passing
    # by refusing everything.
    assert Signal(BAD, "no_gateway_heard_it").unit is None
    assert Signal(BAD, "rf_in_few_hours", value=0.226, unit=signals.FRACTION).value == 0.226


def test_the_unit_is_served_with_the_value() -> None:
    served = Signal(OK, "adequate_margin", value=13.48, unit=signals.DB).as_dict()
    assert served["value"] == 13.48
    assert served["unit"] == "db"


def test_each_signal_names_the_unit_of_its_own_number() -> None:
    """One per signal, decided beside the rule that made the number."""
    settings = _settings()
    rf = signals.rf_intermittent(
        NodeEvidence(node_num=1, packets=500, active_hours=100, rf_hours=25), settings
    )
    assert (rf.value, rf.unit) == (0.25, signals.FRACTION)



    preset = preset_for_channel("MediumFast")
    assert preset is not None
    margin = signals.weak_best_link(
        NodeEvidence(node_num=1, best_neighbour_snr=5.0), settings, preset
    )
    assert margin.unit == signals.DB
    assert margin.value is not None


def test_a_share_just_short_of_every_hour_is_not_stored_as_one() -> None:
    """Rounded to three places, 2000 of 2001 hours was stored as 1.0.

    The page then had no way to know the score was not perfect, and
    would have printed "100%". The value is now kept whole and the page
    rounds it, saying ">99.9%" for this case.
    """
    found = signals.rf_intermittent(
        NodeEvidence(node_num=1, packets=5000, active_hours=2001, rf_hours=2000), _settings()
    )
    assert found.value is not None
    assert found.value < 1.0, "a share short of every hour was stored as a perfect one"


def test_the_prediction_is_served_in_dbm_not_as_the_engine_byte() -> None:
    """The byte carries a 200 dB offset; it printed "62" for -138 dBm.

    And a byte of zero is "the run reached here and predicted nothing",
    which has no dBm at all. It is None, never -200 dBm.
    """
    reached = CoverageLevels(
        stamp="s", available=True, threshold_level=61, levels={"7": {"usable": 90}}
    )
    found = signals.outside_predicted_usable(7, reached, "exact", 0.0)
    assert (found.state, found.value, found.unit) == (OK, -110.0, signals.DBM)

    nothing = CoverageLevels(
        stamp="s", available=True, threshold_level=61, levels={"7": {"usable": 0}}
    )
    found = signals.outside_predicted_usable(7, nothing, "exact", 0.0)
    assert found.state == BAD
    assert found.value is None, "no predicted signal was drawn as a number"
    assert found.unit is None


# --- 3. the key and the headings ---------------------------------------


def test_every_signal_has_a_key_entry_in_three_parts() -> None:
    """What it measures, what counts as a problem, what the owner can do."""
    assert set(signals.SIGNAL_KEY) == set(signals.SIGNAL_ORDER)
    for name, parts in signals.SIGNAL_KEY.items():
        assert set(parts) == {"measures", "problem", "owner"}, name
        assert all(text.strip() for text in parts.values()), name


def test_every_signal_that_carries_a_number_names_its_unit_in_the_heading() -> None:
    """`Gets out over the air only sometimes (% of hours heard)`."""
    carries = {"rf_intermittent", "weak_best_link", "outside_predicted_usable"}
    assert set(signals.SIGNAL_UNIT_LABELS) == carries
    assert signals.SIGNAL_UNIT_LABELS["rf_intermittent"].startswith("%")


def test_the_key_states_the_thresholds_this_run_used() -> None:
    """A key that said "below 50%" while the run used 40% would mislead."""
    key = signals.signal_key({"rf_ratio_bad": 0.4, "margin_bad_db": 3.0, "min_active_hours": 6})
    assert "below 40%" in key["rf_intermittent"]["problem"]
    assert "6 awake hours" in key["rf_intermittent"]["problem"]
    assert "3.0 dB" in key["weak_best_link"]["problem"]
    # A threshold the run did not report stays visible, not blank.
    assert "unknown" in signals.signal_key({})["rf_intermittent"]["problem"]


def _summary(tmp: Path, outputs: JobOutputs) -> dict[str, Any]:
    settings = _settings(coverage_cache_dir=str(tmp))
    outputs.write_index({"presets": [{"preset": "MediumFast", "node_count": 1}]})
    outputs.write_preset(
        "MediumFast",
        {
            "preset": "MediumFast",
            "signal_order": list(signals.SIGNAL_ORDER),
            "signal_labels": dict(signals.SIGNAL_LABELS),
            "thresholds": {"rf_ratio_bad": 0.5, "margin_bad_db": 5.0, "min_active_hours": 12},
            "nodes": [],
        },
    )
    request: Any = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))
    return asyncio.run(gaps_summary(request, channel="MediumFast", session=None))  # type: ignore[arg-type]


def test_the_summary_serves_the_units_and_the_key(tmp_path: Path, job_outputs: JobOutputs) -> None:
    """An assessment written before #265 still gets both: they are definitions."""
    summary = _summary(tmp_path, job_outputs)
    assert summary["signal_units"]["rf_intermittent"] == "% of hours heard"
    assert "below 50%" in summary["signal_key"]["rf_intermittent"]["problem"]


def test_the_page_formats_by_unit_and_never_prints_a_raw_value() -> None:
    """The bug, in the source: `String(signal.value)` is gone."""
    page = (STATIC / "gaps.js").read_text(encoding="utf-8")
    assert "String(signal.value)" not in page
    assert "formatValue(signal.value, signal.unit)" in page
    # "Cannot tell" draws no number at all, so it cannot read as a result.
    assert "signal.state === 'unknown' ? null : formatValue(" in page


def test_the_page_has_a_key_above_the_table() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    section = html[html.index('data-page="gaps"') :]
    section = section[: section.index("</section>")]
    assert '<details class="gap-key">' in section
    assert "data-gaps-key-signals" in section
    assert section.index('class="gap-key"') < section.index("data-gaps-table>"), (
        "the key is not above the table"
    )
    # "Cannot tell" is explained as its own answer, not folded into No.
    assert "This is not the same as No." in section


def test_the_column_hints_survive_a_redraw_that_skips_the_router() -> None:
    """A tile click, a view button and the search all redraw the table.

    None of them passes through the router, which is what turns
    `data-hint` into an info button, so the buttons vanished on the first
    redraw. Measured on the running page: 7 buttons after switching views
    with this call, 0 without it.
    """
    page = (STATIC / "gaps.js").read_text(encoding="utf-8")
    table = page[page.index("function drawTable(") :]
    table = table[: table.index("\n  }\n")]
    assert "revealHints(target.parentElement || target)" in table
    assert "hint: key[name] ? key[name].measures : null" in table
