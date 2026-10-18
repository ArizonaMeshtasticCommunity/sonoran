"""A reading without a noise floor says why (#178, #182).

A target on firmware 2.5 to 2.7.24 answers a LocalStats request but
never sets `noise_floor`; 2.7.25 is the first that does
(src/modules/Telemetry/DeviceTelemetry.cpp, checked tag by tag). The
node page must not show such a reading as if the floor were missing by
fault.
"""

from pathlib import Path

APP = (Path(__file__).resolve().parents[2] / "src/sonoran/web/static/app.js").read_text()
PANEL = APP[APP.index("function localStatsPanel(") : APP.index("function messagesPanel(")]


def test_a_reading_without_a_noise_floor_names_the_firmware_it_needs() -> None:
    assert "2.7.25" in PANEL
    assert "stats.noise_floor == null" in PANEL


def test_the_note_shows_only_with_a_reading() -> None:
    """No reading at all is 'not measured yet', not a firmware question."""
    note = PANEL.index("firmware 2.7.25 or newer")  # the text the reader sees
    guard = PANEL.rfind("if (", 0, note)
    assert "stats.time" in PANEL[guard:note]
