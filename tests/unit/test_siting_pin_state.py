"""The one `innerHTML` escape hatch in the app cannot carry markup.

`el()` has an `html:` key that assigns `innerHTML` directly. It has
exactly one caller: the siting map's candidate pin, which interpolated
`candidate.state` into a `<span class="...">`.

`state` is a server-side enum (`ok`, `bad`, `unknown`) produced by the
gaps engine, so this was **never exploitable**. It is recorded and fixed
because of its shape, not its severity: a `str`-typed field travelling
from the API into an `innerHTML` sink by string interpolation is exactly
how #81 happened, where a node's name reached a sink the same way. The
engine's field type does not stop a later change from putting something
else in it.

Checking against a fixed set makes the sink safe by construction, so the
question never has to be asked again.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
SITING = (STATIC / "siting.js").read_text(encoding="utf-8")
APP = (STATIC / "app.js").read_text(encoding="utf-8")


def test_the_pin_state_is_checked_against_a_fixed_set() -> None:
    start = SITING.index("function pin(candidate)")
    body = SITING[start : start + 400]
    assert "PIN_STATES.has(" in body, (
        "the pin interpolates candidate.state into innerHTML without "
        "checking it against the states the engine actually produces"
    )


def test_the_set_is_the_states_the_engine_produces() -> None:
    """A set that has drifted from the engine silently draws every pin
    as `unknown`, which is a quiet way to break the map."""
    start = SITING.index("const PIN_STATES")
    declared = set(re.findall(r"'([a-z]+)'", SITING[start : start + 120]))
    assert declared == {"ok", "bad", "unknown"}, (
        f"PIN_STATES is {sorted(declared)}; siting.py defines BAD/OK/UNKNOWN "
        f"as 'bad'/'ok'/'unknown'"
    )


def test_nothing_else_uses_the_html_escape_hatch() -> None:
    """`html:` assigns innerHTML. This test is what makes the one above
    sufficient rather than merely true of one call site."""
    callers = [
        line for line in SITING.splitlines() + APP.splitlines() if re.search(r"^\s*html:", line)
    ]
    assert len(callers) == 1, (
        f"there are now {len(callers)} callers of el()'s html: escape hatch, "
        f"and each one assigns innerHTML directly: {callers}"
    )
