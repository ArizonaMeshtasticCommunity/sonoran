"""Preset, slot and frequency are one setting said three ways (§6.5).

The plan asks for the three to be linked so they cannot disagree. Two
things can go wrong, and only one of them is visible.

1. **The three-way binding loops.** Each control may be edited, and a
   naive implementation has the frequency handler move the slot, whose
   handler moves the frequency, for ever. That one is loud.

2. **The slot is off by one.** `lora.channel_num` on the radio counts from
   1; `sonoran/radio/channels.py` reaches the same frequencies from a
   zero-based hash index. Confuse them and every prediction moves by one
   slot -- 250 kHz on Medium fast -- with two perfectly reasonable numbers
   on screen. That one is silent, which is why the anchor below is a
   frequency published outside this repository: LongFast in the US is slot
   20 and 906.875 MHz.

`tests/unit/js/planner_slot_cases.mjs` exercises the arithmetic. This file
pins it to the Python table that the coverage job and the RF page use, and
holds the shapes the browser code needs.

Measured in Chromium on this instance, Advanced, 1500x1050:

    opens on            slot "18 — 906.375 MHz", frequency 906.375
    choose slot 20      frequency 906.875
    type 906.375        slot 18
    type 906.500        slot "", "906.5 MHz is not the centre of a slot"
    preset LongModerate slot 18 kept, frequency 904.188, sensitivity -142,
                        208 slots offered instead of 104
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from sonoran.radio.channels import US_END_HZ, US_START_HZ, channel_for
from sonoran.radio.presets import PRESETS, preset_by_key

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
CASES = ROOT / "tests" / "unit" / "js" / "planner_slot_cases.mjs"


def test_the_cases_pass_under_node() -> None:
    """The arithmetic, exercised rather than read.

    Everything else in this file reads source text, which cannot tell a
    formula that is wrong from one that is missing. These run it.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([str(node), str(CASES)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


def _code(name: str) -> str:
    """The file with its comments removed.

    A grep over raw source has produced a false pass in this repository
    four times, most memorably a check for `--set` that matched the
    comment forbidding it.
    """
    text = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


PARAMS = _code("planner-params.js")
PLANNER = _code("planner.js")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


# --- the band, in both languages ---------------------------------------


def test_the_band_edges_are_the_same_in_both_tables() -> None:
    """The browser cannot read Python, so it holds its own two numbers.

    A deployment that ever runs another region changes both, and this is
    what makes the second one impossible to forget.
    """
    assert f"const BAND_START_HZ = {US_START_HZ};" in PARAMS, (
        "the browser's band start no longer matches sonoran/radio/channels.py"
    )
    assert f"const BAND_END_HZ = {US_END_HZ};" in PARAMS


def test_the_browser_and_the_server_agree_on_every_presets_own_channel() -> None:
    """The anchor, over all nine presets rather than one.

    `channel_for` computes a preset's DEFAULT channel from a hash of its
    name, and that hash gives a zero-based index. The browser's
    `frequencyForSlot` takes the number an operator types, which is one
    higher. So the same frequency must come out of index `n` on one side
    and slot `n + 1` on the other -- and if either ever stops being true,
    one of the two is wrong about where a node is transmitting.
    """
    slots = _slots_from_javascript()
    for preset in PRESETS:
        channel = channel_for(preset)
        expected = channel.centre_hz / 1_000_000
        got = _frequency_for_slot(preset.key, channel.slot + 1, slots)
        assert got == expected, (
            f"{preset.key}: the server puts its channel at {expected} MHz and the browser "
            f"puts slot {channel.slot + 1} at {got} MHz"
        )


def test_long_fast_is_where_the_world_says_it_is() -> None:
    """One case named in full, because it is checkable against a radio.

    LongFast in the US region is frequency slot 20 at 906.875 MHz. If this
    fails, nothing else in this file means anything.
    """
    slots = _slots_from_javascript()
    assert _frequency_for_slot("LONG_FAST", 20, slots) == 906.875
    assert channel_for(preset_by_key("LONG_FAST")).centre_hz == 906_875_000  # type: ignore[arg-type]


# --- what this mesh runs -----------------------------------------------


def test_the_planner_opens_on_slot_eighteen() -> None:
    """The azmsh.net recommendation for a metro node, and its frequency.

    The config checker asks a metro node for `channel_num` 18 on
    MEDIUM_FAST. The planner used to open on 906.875 MHz, which is
    LongFast's slot 20 and nothing this mesh is configured for, under a
    comment calling it "the middle of the US 915 band" -- which it is not
    either.
    """
    recommended = (STATIC / "vendor" / "config-checker" / "js" / "constants.js").read_text(
        encoding="utf-8"
    )
    metro = re.search(r"METRO_RECOMMENDATIONS = \{(.*?)\}", recommended, re.S)
    assert metro, "the config checker no longer states a metro recommendation"
    assert re.search(r"channelNum:\s*18", metro.group(1)), (
        "the metro recommendation is no longer slot 18; the planner default follows it"
    )
    assert "const DEFAULT_SLOT = 18;" in PARAMS, "the planner no longer opens on slot 18"
    slots = _slots_from_javascript()
    # 902 + 0.125 + 17 * 0.25. Written out so a reader can check it here.
    assert _frequency_for_slot("MEDIUM_FAST", 18, slots) == 906.375


def test_the_frequency_default_is_derived_and_not_typed() -> None:
    """A literal with the slot in a comment beside it is how the old
    906.875 came to describe a slot nothing uses."""
    assert "frequency_mhz: frequencyForSlot(DEFAULT_PRESET_KEY, DEFAULT_SLOT)" in PARAMS, (
        "the default frequency is a literal again, so it can drift from the slot it claims"
    )


# --- the binding -------------------------------------------------------


def test_the_slot_is_never_in_a_share_link() -> None:
    """Two numbers that say one thing can disagree, and a link cannot be
    checked by the person who receives it."""
    fields = re.search(r"const SHARE_FIELDS = \[(.*?)\];", PARAMS, re.S)
    assert fields, "SHARE_FIELDS is gone"
    assert "slot" not in fields.group(1), "the slot travels in the link and can contradict it"
    assert "frequency_mhz" in fields.group(1), "the frequency does not travel, so nothing does"


def test_no_handler_dispatches_an_event_that_another_would_answer() -> None:
    """The loop §6.5 warns about, closed by construction.

    The three handlers write `.value` and never dispatch `change`, so none
    of them can re-enter another. The pickers elsewhere on this form DO
    dispatch, which is why this is asserted over the linking code only and
    not over the file.
    """
    body = _function("wireChannelLink")
    assert "dispatchEvent" not in body, (
        "a channel handler dispatches an event, which another handler answers: that is the loop"
    )
    # And the preset handler, which is the third side of the binding.
    preset = PLANNER[PLANNER.index("preset.addEventListener('change'") :][:900]
    assert "dispatchEvent" not in preset, "the preset handler dispatches, so it can re-enter"
    assert "fillSlots(preset.value" in preset, "the preset no longer rebuilds the slot menu"
    assert "frequencyForSlot(preset.value, held)" in preset, (
        "the preset no longer moves the frequency, so the slot on screen would be a lie"
    )


def test_a_frequency_off_the_grid_is_reported_and_not_snapped() -> None:
    """Snapping would move somebody's prediction without being asked.

    `lora.override_frequency` is a real setting. A licensed operator may
    sit between two slots, and the honest answer is to say the slot is
    unknown rather than to pick the nearest.
    """
    body = _function("fillSlots")
    assert "'Not on a slot'" in body, "an off-grid frequency shows a slot it is not in"
    assert "is not the centre of a slot" in body, "nothing tells the reader why the slot is blank"


def test_the_slot_menu_is_rebuilt_rather_than_built_once() -> None:
    """52 slots at 500 kHz, 416 at 62.5 kHz.

    A menu built once would offer slot 300 on Short turbo, which does not
    exist, and `frequencyForSlot` would answer null for it.
    """
    assert "slotsForPreset(presetKey)" in PLANNER, "the menu does not ask how many slots there are"
    assert "function fillSlots(presetKey, megahertz)" in PLANNER


def test_the_slot_control_is_on_the_page_and_labelled() -> None:
    """A control with no label has no accessible name."""
    match = re.search(r"<label>([^<]*)<select data-planner-slot>", HTML)
    assert match, "the slot picker is not inside a label"
    assert "slot" in match.group(1).lower(), f"the slot picker reads {match.group(1)!r}"


# --- helpers -----------------------------------------------------------


def _function(name: str) -> str:
    """One top-level function's body, from its `function` line to the next.

    `index("\nfunction ")` alone was not enough: the next declaration after
    `wireChannelLink` is an `async function`, so the slice ran on for
    another two hundred lines and picked up a `dispatchEvent` belonging to
    the board picker -- a test that failed for a reason that was not there.
    """
    start = PLANNER.index(f"function {name}(")
    ends = [
        PLANNER.find(marker, start + 1)
        for marker in ("\nfunction ", "\nasync function ", "\nconst ", "\nlet ")
    ]
    stop = min(index for index in ends if index != -1)
    return PLANNER[start:stop]


def _slots_from_javascript() -> dict[str, int]:
    """The bandwidths the browser holds, read out of the source.

    Read rather than imported, because there is no build step and no
    JavaScript runtime in a pytest run. `test_radio.py` asserts these are
    the same figures as the Python table; this file only needs them to do
    the arithmetic the browser does.
    """
    pattern = re.compile(r"key:\s*'([A-Z_]+)'.*?bandwidthHz:\s*(\d+)")
    return {key: int(value) for key, value in pattern.findall(PARAMS)}


def _frequency_for_slot(key: str, slot: int, bandwidths: dict[str, int]) -> float:
    """The browser's formula, written out here on purpose.

    Not a call into the JavaScript and not a call into `channels.py`: if
    this reused either, it would agree with that one by construction and
    prove nothing. It is the formula from the firmware, and the test is
    that all three land on the same number.
    """
    bandwidth = bandwidths[key]
    hz = US_START_HZ + bandwidth / 2 + (slot - 1) * bandwidth
    # Five decimals, matching `frequencyForSlot`. Three lost a quarter of a
    # kilohertz on the 62.5 kHz preset, which is what this test found.
    return round(hz / 1_000_000, 5)
