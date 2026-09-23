"""Station-supplied `meta` is a flat map of short scalars, or it is refused.

`meta` arrives from an MQTT station. It used to be checked for exactly
one thing: that `repr()` of it fits in a kilobyte. Inside that kilobyte
it could carry any keys, nested objects and arrays, and values of any
type -- and the RF page renders every key it finds, because the
non-aircraft tooltip is a generic viewer for sources whose fields are
not known in advance.

It is rendered safely today (`rf.js` builds DOM with `el({ text })`), so
this was never a live vulnerability. It is attacker-shaped JSON on a
public API, and it becomes one the moment somebody renders it as a
string -- which is how #81 happened, when a node's name reached an
innerHTML sink.

A key allowlist, which is what #148 suggested, would close it hardest
and would also delete the generic viewer for `aprs`, `sonde` and `ism`.
Bounding the shape removes the category and keeps the function.
"""

import pytest
from pydantic import ValidationError

from sonoran.rf.schema import MAX_META_KEYS, MAX_META_VALUE_CHARS, Observation

BASE = {"kind": "adsb", "id": "abc123", "t": "2026-09-23T00:00:00Z", "lat": 33.4, "lon": -112.0}


def _obs(meta: object) -> Observation:
    return Observation.model_validate(BASE | {"meta": meta})


def test_a_real_looking_contact_still_validates() -> None:
    """The control. A guard that refuses everything proves nothing."""
    observation = _obs(
        {"callsign": "SWA1234", "flight": "SWA1234", "squawk": 1200, "emergency": False}
    )
    assert observation.meta is not None
    assert observation.meta["callsign"] == "SWA1234"


def test_none_and_empty_are_fine() -> None:
    assert _obs(None).meta is None
    assert _obs({}).meta == {}


@pytest.mark.parametrize(
    ("name", "meta"),
    [
        ("a nested object", {"payload": {"deep": "value"}}),
        ("a list", {"payload": ["a", "b"]}),
        ("a list of objects", {"payload": [{"a": 1}]}),
        ("a nested list", {"payload": [[1, 2]]}),
    ],
)
def test_nothing_recursive_gets_through(name: str, meta: dict[str, object]) -> None:
    """A renderer that walks `meta` should not find a tree to walk."""
    with pytest.raises(ValidationError):
        _obs(meta)


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("a script tag", "<script>"),
        ("a path", "../../etc/passwd"),
        ("a dunder", "__proto__"),
        ("a space", "call sign"),
        ("a leading digit", "1key"),
        ("empty", ""),
    ],
)
def test_keys_must_be_plain_names(name: str, key: str) -> None:
    """These are rendered as text beside the value, on the RF page."""
    with pytest.raises(ValidationError):
        _obs({key: "x"})


def test_a_long_value_is_refused() -> None:
    with pytest.raises(ValidationError):
        _obs({"note": "x" * (MAX_META_VALUE_CHARS + 1)})


def test_a_value_at_the_limit_is_kept() -> None:
    """The boundary in the direction that must not over-refuse."""
    assert _obs({"note": "x" * MAX_META_VALUE_CHARS}).meta is not None


def test_too_many_keys_are_refused() -> None:
    with pytest.raises(ValidationError):
        _obs({f"k{index}": index for index in range(MAX_META_KEYS + 1)})


def test_the_size_cap_still_applies() -> None:
    """The check this replaced must not have been lost in replacing it."""
    with pytest.raises(ValidationError):
        _obs({f"k{index}": "y" * 100 for index in range(12)})
