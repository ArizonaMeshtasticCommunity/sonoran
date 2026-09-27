"""Explanatory prose goes behind an ⓘ button, and guidance appears (#191, #192).

#99 moved the column explanations of two tables behind hint buttons.
Panel-level prose was not part of that work, so a sentence useful on a
first visit was printed in full on every visit after.

#192 is the other half: when a telemetry panel is empty it said so and
stopped, teaching the owner nothing. Measured on the running instance
over 7 days, of 1,189 active nodes:

    Device panel empty     849   (71%)
    Weather panel empty  1,117   (94%)

So this is the common case, not an edge case -- and 94% is also why the
Weather guidance must lead with "you need a sensor" rather than with a
setting. Leading with the setting would misdirect about a thousand
owners toward something that cannot help them.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"


def _code(name: str) -> str:
    """Return a static file with its comments removed.

    A grep over raw source has produced a false pass in this repository
    more than once, including one caused by the very comment written to
    explain the rule being checked.
    """
    text = re.sub(r"/\*.*?\*/", "", (STATIC / name).read_text(encoding="utf-8"), flags=re.S)
    return "\n".join(
        line for line in text.splitlines() if (s := line.strip()) and not s.startswith("//")
    )


def test_the_stripper_keeps_code_and_drops_comments() -> None:
    """Positive control for `_code`."""
    app = _code("app.js")
    assert "function revealHints" in app
    assert "Explanatory prose under a heading is useful once" not in app


# --- #191 ----------------------------------------------------------


def test_panel_headings_can_carry_a_hint() -> None:
    """The mechanism #99 built, extended to panels rather than rebuilt.

    #191 says: reuse `fitHint`/`hintBody`/`placeHint`. Do not build a
    second tooltip.
    """
    app = _code("app.js")
    assert "$$('h3[data-hint]', root)" in app


def test_there_is_still_only_one_hint_mechanism() -> None:
    """A second tooltip would be the thing #191 forbids."""
    app = _code("app.js")
    assert app.count("function fitHint(") == 1
    assert app.count("function placeHint(") == 1


def test_the_route_tiles_no_longer_use_a_title_tooltip() -> None:
    """#99 removed `title` tooltips on purpose.

    A finger cannot hover and a keyboard cannot reach one, so the only
    explanation of "Hops to the nearest gateway" was invisible to
    anybody on a phone.
    """
    app = _code("app.js")
    tile = app[app.index("const tile = (label, value, detail, hint)") :][:400]
    assert "title:" not in tile, "the tile still explains itself in a title attribute"
    assert "'data-hint': hint" in tile
    # And it must not borrow `stat` to be found. That class carries a
    # bigger padding and font size, and the tiles only survived it
    # because `.route-tile` happens to come later in app.css.
    assert "'route-tile stat'" not in tile


def test_an_empty_state_is_not_hidden_behind_a_button() -> None:
    """#191 names these as must-stay-visible.

    A reader who cannot see "this node reports no neighbours" is left
    looking at a blank panel wondering if it failed to load.
    """
    app = _code("app.js")
    assert "'This node reports no neighbors.'" in app
    assert "This node sends no device telemetry." in app


def test_the_reason_a_number_is_missing_stays_visible() -> None:
    """The other must-stay-visible rule, and the sharper one.

    If the reason a figure is absent goes behind a button, the figure
    reads as a fact. The "Furthest node" tiles say why they are empty
    (#193.7) and that sentence must not be swept into a hint by this
    change.

    #257 changed which sentences those are: a rounded position of its
    own now gives an estimate, so "Its own position is rounded" is gone,
    and each reason the API names has a sentence and a fix in
    `NO_DISTANCE`. The rule pinned here is unchanged: the reason is drawn
    as visible text on the tile, not as a hint.
    """
    app = _code("app.js")
    assert "It shares no position, so no distance can be measured." in app
    assert "return twoLine('Not known', why, fix);" in app
    assert "el('span', { class: 'muted', text: first })" in app


# --- #192 ----------------------------------------------------------


def test_the_weather_guidance_leads_with_the_sensor() -> None:
    """94% of empty Weather panels are nodes with no sensor.

    A setting cannot help them. The first sentence has to say so, or
    the guidance sends about a thousand owners on a hunt that cannot
    succeed.
    """
    app = _code("app.js")
    weather = app[app.index("weather: 'Weather needs") :][:400]
    sensor = weather.index("sensor")
    setting = weather.index("environment_measurement_enabled")
    assert sensor < setting, "the guidance names a setting before it names the sensor"


def test_the_device_guidance_names_real_settings() -> None:
    """Quoted from module_config.proto, not invented.

    `AGENTS.md` 9.27: this project does not state what the vendor did
    not state. These names are asserted against the vendored protobuf
    below, so a rename upstream fails here rather than misleading an
    owner.
    """
    app = _code("app.js")
    assert "device_telemetry_enabled" in app
    assert "device_update_interval" in app


def test_every_quoted_setting_exists_in_the_vendored_proto() -> None:
    """The control that makes the case above worth anything.

    Without it, the guidance could name a plausible setting that no
    firmware has, and every test here would still pass.
    """
    from sonoran.meshtastic import module_config_pb2

    telemetry = module_config_pb2.ModuleConfig.TelemetryConfig()  # type: ignore[attr-defined]
    fields = {field.name for field in telemetry.DESCRIPTOR.fields}
    app = _code("app.js")
    for name in (
        "device_telemetry_enabled",
        "device_update_interval",
        "environment_measurement_enabled",
        "environment_update_interval",
    ):
        assert name in app, f"the guidance no longer mentions {name}"
        assert name in fields, f"{name} is not a field of TelemetryConfig"


def test_no_default_interval_is_claimed() -> None:
    """The proto states no default, so neither does the page.

    A number here would be this project inventing firmware behaviour,
    which is the thing 9.27 exists to stop.
    """
    app = _code("app.js")
    for block in ("device: 'Device telemetry", "weather: 'Weather needs"):
        text = app[app.index(block) :][:600]
        assert "seconds" not in text, "the guidance claims an interval the proto does not state"


def test_the_guidance_only_appears_when_the_panel_is_empty() -> None:
    """A panel with readings needs no "why is this empty"."""
    app = _code("app.js")
    assert "list ? null : TELEMETRY_HELP.weather" in app
    assert "list ? null : TELEMETRY_HELP.device" in app


def test_the_empty_panel_offers_a_way_to_act() -> None:
    """The issue's "Done when": a way to the guidance, and to Config check."""
    app = _code("app.js")
    assert "How to turn this on" in app
    assert "href: '#config'" in app
