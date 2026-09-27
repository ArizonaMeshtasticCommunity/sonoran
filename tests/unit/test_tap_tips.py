"""Meanings that lived only in a `title` open on a tap (#276).

A touch screen never shows a `title`. The mobile review (section 2.7)
found four kinds of meaning that a phone could not read at all: the
gateway tag, the Statistics send-rate tags and uptime notes, the node
page's health dots, and the exact time of a message. The e2e journey
"a phone can tap what used to be a title" taps each one. These hold the
source shape, so a `title` put back fails here before a browser runs.
"""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def test_the_value_is_the_button_and_opens_the_hint_panel() -> None:
    start = APP.index("function tapTip(")
    body = APP[start : APP.index("\n}\n", start)]
    assert "type: 'button'" in body
    assert "'aria-expanded': 'false'" in body
    assert "wireHint(button, panel);" in body, "the tip does not open like a column hint"
    # One copy of the popover wiring, used by both.
    assert APP.count("function wireHint(") == 1
    hint = APP[APP.index("function fitHint(") : APP.index("function wireHint(")]
    assert "wireHint(button, panel);" in hint


def test_no_title_is_left_on_the_four_kinds() -> None:
    assert "title: 'This node uploads packets it hears to MQTT." not in APP, "gateway tag"
    assert "title: `every ${everySeconds(rate.interval_seconds)}" not in APP, "send-rate tag"
    assert "title: 'How long the node says it has been running" not in APP, "uptime note"
    assert "title: `${check.name}: " not in APP, "health dot"
    assert "title: stamp(message.seen_at), text: `${ago(message.seen_at)} ago`" not in APP, (
        "message time"
    )


def test_each_kind_is_a_tap_tip() -> None:
    assert "tapTip('tag gateway', 'gateway'" in APP
    assert "tapTip('when'," in APP
    assert "tapTip('health-dots'," in APP
    assert "The default is every" in APP
