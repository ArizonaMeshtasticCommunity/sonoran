"""Every modem preset is a choice in the menu, and several at once (#383).

Will's issue: "Add all of the other presets for people to select. ...
select multiple presets as well. ... Make MediumFast the default solo
selected."

The browser holds its own list of preset names in `preset.js`, because
the menu must offer them before any request finishes. That is a second
copy of the table in `sonoran/radio/presets.py`, so this keeps the two
the same, as `test_planner_params` does for the planner's copy.
"""

import re
from pathlib import Path

from sonoran.api.preset_scope import require_presets
from sonoran.meshtastic import config_pb2
from sonoran.radio.presets import KNOWN, preset_by_key

ROOT = Path(__file__).resolve().parents[2]
PRESET_JS = ROOT / "src" / "sonoran" / "web" / "static" / "preset.js"


def _standard() -> list[str]:
    source = PRESET_JS.read_text(encoding="utf-8")
    match = re.search(r"const STANDARD = \[(.*?)\];", source, re.S)
    assert match, "preset.js has no STANDARD list"
    return re.findall(r"'([^']+)'", match.group(1))


def test_the_menu_offers_every_preset_the_server_knows_in_its_order() -> None:
    assert _standard() == [preset.name for preset in KNOWN]


def test_every_preset_in_the_protobufs_is_offered() -> None:
    """The enum is the source: a preset added there must reach the menu."""
    enum = config_pb2.Config.LoRaConfig.ModemPreset
    offered = set(_standard())
    for key in enum.keys():
        preset = preset_by_key(key)
        assert preset is not None, f"{key} is in the protobufs and not in radio/presets.py"
        assert preset.name in offered, f"{key} ({preset.name}) is not offered in the menu"


def test_the_issue_names_are_all_offered() -> None:
    # The firmware calls LONG_MODERATE's channel "LongMod".
    for name in [
        "LongFast",
        "LongSlow",
        "LongMod",
        "LongTurbo",
        "MediumFast",
        "MediumSlow",
        "ShortFast",
        "ShortSlow",
        "ShortTurbo",
    ]:
        assert name in _standard()


def test_a_list_of_presets_is_read_canonically_and_once() -> None:
    assert require_presets("MediumFast,LongFast") == ("MediumFast", "LongFast")
    assert require_presets("longfast, MEDIUM_FAST,LongFast") == ("LongFast", "MediumFast")
    assert require_presets("LongModerate") == ("LongMod",)
    assert require_presets("MediumFast") == ("MediumFast",)
    assert require_presets(None) is None
    assert require_presets("") is None
