"""The defaults the docs promise are the defaults the form uses.

Found by reading both: `docs/PLANNER.md` said the receiver opens on Long
fast at -139 dBm, and it has opened on Medium fast at -134 dBm since
#105 moved it, deliberately, because Medium fast is what this mesh
actually runs. Nothing was broken in the code. The document had simply
never been corrected, and a reader trusting it would have assumed five
decibels of sensitivity the planner does not use -- which is a different
predicted range, not a typo.

A number written in two places drifts. These cases read the values out
of `planner-params.js` and require the tables in the document to agree,
so the next person to move a default has to move the sentence with it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARAMS = ROOT / "src" / "sonoran" / "web" / "static" / "planner-params.js"
DOC = ROOT / "docs" / "PLANNER.md"

# Each default, and the label the document's table uses for it. Only the
# ones the tables actually state a value for.
DOCUMENTED = {
    "preset": "Modem preset",
    "sensitivity": "Sensitivity",
    "tx_power": "Power",
    "rx_height": "Height",
    "system_loss": "Cable loss",
    "frequency_mhz": "Frequency",
}


def _defaults() -> dict[str, str]:
    text = PARAMS.read_text(encoding="utf-8")
    block = text[text.index("const DEFAULTS = {") :]
    block = block[: block.index("\n};")]
    # Comment lines are stripped first: DEFAULTS carries long explanatory
    # comments that mention other values, and one of them names -139.
    lines = [line for line in block.splitlines() if not line.strip().startswith(("*", "/*", "//"))]
    out: dict[str, str] = {}
    for line in lines:
        found = re.match(r"\s*(\w+):\s*(.+?),\s*$", line)
        if found:
            out[found.group(1)] = found.group(2).strip().strip("'\"")
    return out


def _row(label: str) -> str:
    """The document's table row for a field, as text."""
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"| {label} |"):
            return line
    raise AssertionError(f"no table row for {label!r} in PLANNER.md")


def test_the_defaults_parse() -> None:
    """Control: every case below passes trivially on an empty dict."""
    values = _defaults()
    assert len(values) > 10, f"only parsed {sorted(values)}"
    for name in DOCUMENTED:
        assert name in values, f"{name} is not in DEFAULTS any more"


def test_the_comment_stripping_does_not_hide_a_real_value() -> None:
    """Positive control for the stripper.

    `DEFAULTS` explains the Medium fast choice in a comment that names
    Long fast's -139 dBm. Reading the block without stripping comments
    would find that number and could be made to agree with a stale
    document -- the exact bug this file exists to catch, passing itself.
    """
    values = _defaults()
    assert values["sensitivity"] == "-134", (
        f"sensitivity parsed as {values['sensitivity']!r}; a comment may be leaking in"
    )


def test_the_receiver_defaults_match_the_document() -> None:
    """The specific drift that prompted this file."""
    values = _defaults()
    assert "Medium fast" in _row("Modem preset"), (
        f"the document names a preset the form does not use; form says {values['preset']!r}"
    )
    assert values["preset"] == "MEDIUM_FAST"
    assert "-134" in _row("Sensitivity"), (
        f"the document states a sensitivity the form does not use: {values['sensitivity']!r}"
    )


def test_every_documented_default_appears_in_its_own_row() -> None:
    """The general rule, so the next one cannot drift quietly."""
    values = _defaults()
    for name, label in DOCUMENTED.items():
        value = values[name]
        row = _row(label)
        if name == "preset":
            continue  # spelled in prose, checked above
        if name == "frequency_mhz":
            _check_derived_frequency(value, row)
            continue
        assert value in row, (
            f"PLANNER.md row for {label!r} does not state the default {value!r}: {row}"
        )


def _check_derived_frequency(value: str, row: str) -> None:
    """The frequency default is worked out from the slot, not typed.

    `DEFAULTS` holds `frequencyForSlot(DEFAULT_PRESET_KEY, DEFAULT_SLOT)`,
    so there is no literal to look for. The document states the slot in
    its own row and the frequency that slot gives. Both are checked here.
    The slot arithmetic itself is pinned by
    `test_planner_slot_and_frequency.py`.
    """
    assert value == "frequencyForSlot(DEFAULT_PRESET_KEY, DEFAULT_SLOT)", (
        f"the frequency default is no longer derived from the slot: {value!r}"
    )
    text = PARAMS.read_text(encoding="utf-8")
    found = re.search(r"const DEFAULT_SLOT = (\d+);", text)
    assert found, "DEFAULT_SLOT is not in planner-params.js any more"
    slot = int(found.group(1))
    assert f"| {slot} |" in _row("Frequency slot"), (
        f"PLANNER.md does not state the default slot {slot}: {_row('Frequency slot')}"
    )
    # Medium fast is 250 kHz wide: 902 MHz + half a slot + (slot - 1) slots.
    centre = 902 + 0.125 + (slot - 1) * 0.25
    assert f"{centre:g}" in row, f"PLANNER.md row for 'Frequency' does not state {centre:g}: {row}"


def test_the_section_numbers_have_no_gaps() -> None:
    """A reference to a section that is not there sends people nowhere.

    The directional antenna section was written as 4.4 first, which read
    as though two sections existed and had been skipped. It is 4.3 now,
    after "Preset, slot and frequency".
    """
    doc = DOC.read_text(encoding="utf-8")
    numbers = sorted({m for m in re.findall(r"^### (4\.\d+)", doc, re.M)})
    expected = [f"4.{i + 1}" for i in range(len(numbers))]
    assert numbers == expected, f"section numbering has a gap: {numbers}"
    for reference in set(re.findall(r"See (4\.\d+)\.", doc)):
        assert reference in numbers, f"the text points at {reference}, which does not exist"
