"""Station-supplied `meta` is filtered to a flat map of short scalars.

`meta` arrives from an MQTT station. It used to be checked for one
thing: that `repr()` of it fits in a kilobyte. Inside that kilobyte it
could carry any keys, nested objects and arrays, and values of any type
— and the RF page renders every key it finds, because the non-aircraft
tooltip is a generic viewer for sources whose fields are not known in
advance.

It is rendered safely today (`rf.js` builds DOM with `el({ text })`), so
this was never a live vulnerability. It is attacker-shaped JSON on a
public API, and it becomes one the moment somebody renders it as a
string — which is how #81 happened.

**It filters rather than rejects, and that correction matters more than
the original fix.** Observations arrive in batches of up to 100. The
first version of this raised on a bad field, and measured:

    100 good observations                -> accepted, 100 stored
    1 nested-meta + 99 good observations -> WHOLE BATCH REJECTED

A station whose firmware puts one nested object in `meta` would have
lost every observation in every batch, silently, for as long as it ran,
and its operator would have seen "my station stopped reporting" with
nothing to explain it. That is a worse outcome than the shape it was
defending against — and it would have hit community members who are not
in this conversation.

`meta` is decoration; the position, altitude and signal are the
measurement. Dropping an unusable key costs nothing. Dropping the batch
costs a hundred real aircraft positions.
"""

from typing import Any

from sonoran.rf.schema import MAX_META_KEYS, MAX_META_VALUE_CHARS, Batch, Observation

BASE = {"kind": "adsb", "id": "abc123", "t": "2026-09-23T00:00:00Z", "lat": 33.4, "lon": -112.0}


def _meta(value: object) -> dict[str, Any] | None:
    return Observation.model_validate(BASE | {"meta": value}).meta


def _batch(obs: list[dict[str, Any]]) -> Batch:
    return Batch.model_validate(
        {
            "v": 1,
            "station": "testsite",
            "kind": "adsb",
            "sent": "2026-09-23T00:00:01Z",
            "obs": obs,
        }
    )


def test_one_bad_field_does_not_cost_a_whole_batch() -> None:
    """The reason this filters instead of raising.

    This is the regression that matters: it is silent, it is total, and
    it lands on somebody who cannot see why.
    """
    good = [BASE | {"id": f"g{index}"} for index in range(99)]
    bad = BASE | {"id": "bad", "meta": {"payload": {"deep": "value"}}}
    batch = _batch([bad, *good])
    assert len(batch.obs) == 100, "good observations were lost with the bad one"
    assert batch.obs[0].meta == {}, "the unusable meta was kept"


def test_a_batch_of_good_observations_is_untouched() -> None:
    """The positive control. A filter that drops everything would pass
    every test above it."""
    batch = _batch([BASE | {"id": f"g{index}"} for index in range(100)])
    assert len(batch.obs) == 100


def test_a_real_contact_keeps_its_fields() -> None:
    kept = _meta({"callsign": "SWA1234", "squawk": 1200, "emergency": False})
    assert kept == {"callsign": "SWA1234", "squawk": 1200, "emergency": False}


def test_the_usable_keys_survive_beside_an_unusable_one() -> None:
    """Filtering per key, not per observation: a station that sends one
    odd field keeps the rest of what it knows."""
    assert _meta({"<script>": "bad", "callsign": "SWA1"}) == {"callsign": "SWA1"}
    assert _meta({"note": "y" * 300, "callsign": "SWA1"}) == {"callsign": "SWA1"}


def test_nothing_recursive_survives() -> None:
    """A renderer walking `meta` should find no tree to walk."""
    for shape in ({"payload": {"deep": "v"}}, {"payload": ["a"]}, {"payload": [{"a": 1}]}):
        assert _meta(shape) == {}


def test_keys_that_are_not_plain_names_are_dropped() -> None:
    """These are rendered as text beside the value on the RF page."""
    for key in ("<script>", "../../etc/passwd", "__proto__", "call sign", "1key", ""):
        assert _meta({key: "x"}) == {}


def test_the_key_count_is_capped() -> None:
    kept = _meta({f"k{index}": index for index in range(MAX_META_KEYS + 20)})
    assert kept is not None
    assert len(kept) == MAX_META_KEYS


def test_a_value_at_the_limit_is_kept_and_one_past_it_is_not() -> None:
    assert _meta({"note": "x" * MAX_META_VALUE_CHARS}) == {"note": "x" * MAX_META_VALUE_CHARS}
    assert _meta({"note": "x" * (MAX_META_VALUE_CHARS + 1)}) == {}


def test_none_stays_none() -> None:
    assert _meta(None) is None
    assert _meta({}) == {}


def test_the_longest_aprs_comment_is_kept_whole() -> None:
    """An AX.25 information field is at most 256 octets.

    A value over the limit is dropped, not cut, so a limit below this
    loses the longest comments entirely.
    """
    comment = "North Phoenix WX3in1 #YAESUGANG RF & iGate K7XYG-10 U=13.3V " * 5
    comment = comment[:256]
    readings: dict[str, object] = {
        "symbol": "/_",
        "path": "WIDE1-1*,WIDE2-1",
        "destination": "APMI06",
        "wind_dir_deg": 120,
        "wind_kn": 0.0,
        "gust_kn": 1.74,
        "temperature_f": 64,
        "rain_today_in": 0.0,
        "rain_1h_in": 0.0,
        "pressure_hpa": 1014.0,
        "humidity": 40,
    }
    kept = _meta({"comment": comment, **readings})
    assert kept is not None
    assert kept["comment"] == comment
    assert len(kept) == len(readings) + 1
