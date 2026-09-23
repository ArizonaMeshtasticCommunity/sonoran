"""MQTT and editable values, the last interface gap with cfgtest (#118).

Upstream's `ConfigFixer.fix()` already takes `userOverrides` and
`mqttConfig`; Sonoran simply passed neither. So this is a form and a
validator, and the behaviour comes from the vendored logic — which is
what #118 asks for, "so the behaviour matches upstream exactly".

Verified in a browser end to end, reading the file that comes out:

    mqtt enabled            in file: true
    broker address          in file: true
    username                in file: true
    password                in file: true
    30m -> 1800 seconds     in file: true
    password in localStorage: false

That fifth line was reported FALSE on the first run and the code was
fine: the export writes snake_case (`position_broadcast_secs`) and my
check looked for camelCase. A false negative from my own instrument,
which would have sent me debugging working code. Recorded because the
lesson is the same one this suite keeps relearning — the measurement
can be wrong in either direction.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
CHECK = (STATIC / "config-check.js").read_text(encoding="utf-8")
FIXER = (STATIC / "vendor" / "config-checker" / "js" / "fixer.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")


def test_the_fixer_is_given_the_overrides_and_the_mqtt_settings() -> None:
    """Without this the form is decoration: the panel fills in, the
    reader presses export, and nothing they typed is in the file."""
    assert "ConfigFixer.fix(" in CHECK
    call = CHECK[CHECK.index("ConfigFixer.fix(") :][:220]
    assert "extras.overrides" in call and "extras.mqtt" in call


def test_a_value_that_is_not_a_time_blocks_the_export() -> None:
    """#118: "a bad value blocks export with a clear message".

    Exporting with a silently dropped interval is worse than not
    exporting, because the reader flashes it and finds out on the mesh.
    """
    start = CHECK.index("function readExtras(")
    body = CHECK[start : CHECK.index("\n}", start)]
    assert "return null;" in body, "a bad value no longer stops the export"
    assert "Nothing was exported." in body, "the reader is not told the export was refused"


def test_the_time_parser_has_not_drifted_from_upstreams() -> None:
    """The one real risk in this change.

    Upstream keeps `parseTimeSecs` inside a closure in `fixer.js` and
    does not export it, so the check here is a second copy of its
    regular expression. If upstream's grammar changes, the form starts
    accepting what the fixer rejects — or worse, rejecting what it
    accepts, which looks like a bug in the reader's input.

    Comparing the patterns is the cheapest way to find out.
    """
    # The units upstream's grammar accepts, read off `fixer.js` rather
    # than remembered. If this list stops matching, the two have drifted.
    upstream = FIXER[FIXER.index("function parseTimeSecs(") :][:900]
    units = ("days?", "hours?", "minutes?", "seconds?", "hrs", "mins", "secs")
    for unit in units:
        assert unit in upstream, (
            f"upstream no longer accepts {unit!r}; this test is comparing "
            f"against a grammar that has moved"
        )
    ours = CHECK[CHECK.index("function secondsFrom(") :][:900]
    for unit in units:
        assert unit in ours, (
            f"the local time check no longer accepts {unit!r} while the "
            f"vendored fixer still does, so the form refuses input the "
            f"fixer would have taken"
        )


def test_the_password_is_never_stored() -> None:
    """The page's whole promise is that nothing leaves the device, and
    a saved broker password would be the one thing on it worth taking.

    `remember()` is what writes to localStorage here; it must not learn
    about the MQTT fields.
    """
    start = CHECK.index("function remember(")
    body = CHECK[start : CHECK.index("\n}", start)]
    assert "password" not in body and "mqtt" not in body.lower(), (
        "the config page now persists something MQTT-shaped; the password "
        "must live only in the field and the downloaded file"
    )
    field = HTML[HTML.index('data-mqtt="password"') - 120 :][:260]
    assert 'autocomplete="off"' in field, "the password field invites the browser to remember it"


def test_the_panel_says_mqtt_is_optional_before_it_asks_for_anything() -> None:
    """It puts a node's traffic on somebody else's broker. A reader
    should meet that as a choice, not as a form to complete."""
    start = HTML.index("data-config-extras")
    panel = HTML[start : HTML.index("</details>", start)]
    assert "Optional:" in panel
    assert "optional" in panel.lower().split('<p class="sub">')[1][:400]
    assert panel.index("summary") < panel.index('data-mqtt="enabled"')


def test_the_panel_only_appears_once_there_is_a_config() -> None:
    assert "data-config-extras hidden" in HTML
    assert "if (extras) extras.hidden = false;" in CHECK
