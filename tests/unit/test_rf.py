"""The RF map's message contract and its small rules (docs/design/rf-map.md)."""

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from sonoran.config import Settings
from sonoran.rf.ingest import decode, rules_from
from sonoran.rf.schema import (
    KINDS,
    MAX_RAW_CHARS,
    STORED_KINDS,
    THING_ID,
    Batch,
    Observation,
    Spectrum,
    Status,
    TopicError,
    json_schema,
    parse_topic,
)
from sonoran.rf.store import (
    Hearing,
    Rules,
    aprs_meta,
    floor_time,
    guarded_time,
    hearings,
    ism_model,
    stored_meta,
)

NOW = datetime(2026, 9, 22, 18, 0, 0, tzinfo=UTC)


def _batch(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "v": 1,
        "station": "tempe-roof",
        "kind": "adsb",
        "sent": "2026-09-22T18:00:00Z",
        "obs": [
            {
                "id": "A1B2C3",
                "t": "2026-09-22T17:59:58.4Z",
                "lat": 33.51,
                "lon": -112.02,
                "alt_m": 3350,
                "rssi_db": -24.1,
                "meta": {"callsign": "SWA1234"},
            }
        ],
    }
    body.update(overrides)
    return body


def test_a_good_batch_is_read_and_its_address_lower_cased() -> None:
    batch = Batch.model_validate(_batch())
    assert batch.obs[0].id == "a1b2c3"
    assert batch.obs[0].t.tzinfo is not None


def test_unknown_fields_are_ignored_so_agents_can_grow() -> None:
    body = _batch(firmware="2.0", extra={"a": 1})
    assert Batch.model_validate(body).station == "tempe-roof"


@pytest.mark.parametrize(
    "change",
    [
        {"v": 2},
        {"station": "Tempe Roof"},
        {"kind": "ais"},
        {"sent": "2026-09-22T18:00:00"},  # no zone: a clock we cannot place
        {"obs": [{"id": "a1b2c3", "t": "2026-09-22T17:59:58Z", "lat": 91, "lon": 0}]},
        {"obs": [{"id": "a1b2c3", "t": "2026-09-22T17:59:58Z", "lat": 0, "lon": 0}] * 101},
    ],
)
def test_a_message_that_breaks_the_contract_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Batch.model_validate(_batch(**change))


def test_an_oversized_meta_value_is_dropped_and_the_observation_kept() -> None:
    """This case used to be in the list above, and the change is deliberate.

    An oversized `meta` value used to reject the whole message. Since
    observations arrive in batches of up to 100, that meant one station
    sending one long field lost every observation in the batch --
    silently, for as long as its firmware did it, with its operator
    seeing only "my station stopped reporting".

    `meta` is decoration; the position and signal are the measurement.
    So the unusable field is dropped and the observation is kept. The
    size bound it was defending is still enforced, just per field
    instead of per message.
    """
    batch = Batch.model_validate(
        _batch(
            obs=[
                {
                    "id": "x",
                    "t": "2026-09-22T17:59:58Z",
                    "lat": 0,
                    "lon": 0,
                    "meta": {"k": "v" * 2000, "callsign": "SWA1"},
                }
            ]
        )
    )
    assert len(batch.obs) == 1, "the observation was lost with its bad field"
    assert batch.obs[0].meta == {"callsign": "SWA1"}, "a usable field was dropped too"


def test_a_heartbeat_is_read_with_its_counts() -> None:
    status = Status.model_validate(
        {
            "v": 1,
            "station": "tempe-roof",
            "sent": "2026-09-22T18:00:00Z",
            "lat": 33.4,
            "lon": -111.9,
            "precision_m": 1000,
            "kinds": ["adsb", "uat"],
            "counts": {"heard": 900, "sent": 60, "dropped": 840},
        }
    )
    assert status.counts.dropped == 840
    assert status.kinds == ["adsb", "uat"]


def test_topics_name_a_station_and_a_kind() -> None:
    assert parse_topic("rf/v1/tempe-roof/adsb") == ("tempe-roof", "adsb")
    assert parse_topic("rf/v1/tempe-roof/status") == ("tempe-roof", "status")
    for bad in ("msh/US/AZ/2/e/LongFast/!1", "rf/v2/tempe-roof/adsb", "rf/v1/Bad Name/adsb"):
        with pytest.raises(TopicError):
            parse_topic(bad)


def test_a_message_must_name_the_station_its_topic_names() -> None:
    """The broker limits each login to its own topic. This checks again."""
    payload = json.dumps(_batch(station="other-site")).encode()
    with pytest.raises(ValueError, match="station"):
        decode("rf/v1/tempe-roof/adsb", payload)
    with pytest.raises(ValueError, match="kind"):
        decode("rf/v1/tempe-roof/uat", json.dumps(_batch()).encode())
    assert isinstance(decode("rf/v1/tempe-roof/adsb", json.dumps(_batch()).encode()), Batch)


def test_a_clock_far_off_ours_is_replaced_by_the_time_we_received_it() -> None:
    rules = Rules()
    assert guarded_time(NOW - timedelta(seconds=2), NOW, rules) == (
        NOW - timedelta(seconds=2),
        False,
    )
    assert guarded_time(NOW + timedelta(minutes=5), NOW, rules) == (NOW, True)
    assert guarded_time(NOW - timedelta(hours=1), NOW, rules) == (NOW, True)


def test_buckets_start_on_the_step() -> None:
    step = timedelta(seconds=20)
    assert floor_time(datetime(2026, 9, 22, 18, 0, 39, 900000, tzinfo=UTC), step) == datetime(
        2026, 9, 22, 18, 0, 20, tzinfo=UTC
    )


def _spectrum(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "v": 1,
        "station": "tempe-roof",
        "kind": "spectrum",
        "t": "2026-09-22T18:00:00Z",
        "f_start_hz": 902_000_000,
        "bin_hz": 50_000,
        "sweeps": 12,
        "gain_db": 32.8,
        "p50": [-512, -509, None],
        "p95": [-470, -468, None],
        "peak": [-402, -401, None],
        "busy": [3, 0, None],
    }
    body.update(overrides)
    return body


def test_a_good_spectrum_is_read() -> None:
    spectrum = Spectrum.model_validate(_spectrum())
    assert spectrum.p50[2] is None
    assert isinstance(
        decode("rf/v1/tempe-roof/spectrum", json.dumps(_spectrum()).encode()), Spectrum
    )


@pytest.mark.parametrize(
    "change",
    [
        {"kind": "adsb"},
        {"t": "2026-09-22T18:00:00"},
        {"sweeps": 0},
        {"bin_hz": 0},
        {"p50": [-512, -509]},  # one entry short
        {"busy": [3, 0, 101]},
        {"peak": [-402, -401, 2000]},
        {"p50": [], "p95": [], "peak": [], "busy": []},
    ],
)
def test_a_bad_spectrum_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Spectrum.model_validate(_spectrum(**change))


def test_a_spectrum_must_name_the_station_its_topic_names() -> None:
    with pytest.raises(ValueError, match="station"):
        decode("rf/v1/other-site/spectrum", json.dumps(_spectrum()).encode())


def test_the_heartbeat_may_name_the_mesh_node_on_its_site() -> None:
    body = {"v": 1, "station": "tempe-roof", "sent": "2026-09-22T18:00:00Z"}
    assert Status.model_validate(body).mesh_node is None
    assert Status.model_validate({**body, "mesh_node": "!a1b2c3d4"}).mesh_node == "!a1b2c3d4"
    with pytest.raises(ValidationError):
        Status.model_validate({**body, "mesh_node": "a1b2c3d4"})


def test_the_published_json_schema_matches_the_code() -> None:
    """Agent builders read the file. It must never drift from the models."""
    published = json.loads(Path("docs/rf-message-v1.schema.json").read_text())
    assert published == json.loads(json.dumps(json_schema()))


def _static(name: str) -> str:
    from sonoran.api.app import STATIC_DIR

    return (STATIC_DIR / name).read_text(encoding="utf-8")


def test_the_rf_page_loads_before_the_router() -> None:
    """A reload straight to #rf must find its page already registered."""
    from fastapi.testclient import TestClient

    from sonoran.api.app import create_app
    from sonoran.config import Settings

    html = TestClient(create_app(Settings(_env_file=None))).get("/").text
    assert html.index("static/rf.js") < html.index("static/app.js")
    assert 'data-page="rf"' in html
    assert 'data-nav="rf"' in html
    assert '<symbol id="i-rf"' in html


def test_text_off_the_air_is_never_built_into_html() -> None:
    """A callsign or station name is set as text, never as markup."""
    source = _static("rf.js")
    for risky in ("innerHTML", "insertAdjacentHTML", "bindTooltip(`", "bindPopup(`", "html:"):
        assert risky not in source, risky


def test_the_page_is_about_every_source_not_only_aircraft() -> None:
    """The RF map is aircraft, APRS, sondes, sensors and the band."""
    html = _static("index.html")
    page = html[html.index('data-page="rf"') :]
    page = page[: page.index("</section>")]
    for word in ("aircraft", "APRS", "radiosondes", "weather sensors", "900 MHz band"):
        assert word in page, word
    assert "data-rf-sources" in page
    source = _static("rf.js")
    for key in ("'aircraft'", "'aprs'", "'sonde'", "'ism'", "'spectrum'"):
        assert f"key: {key}" in source, key
    # Stored or not comes from the server, never from the page.
    assert "api/rf/kinds" in source


def test_the_page_says_what_it_does_not_claim() -> None:
    """Design 1.3: not air traffic control, not the whole sky."""
    html = _static("index.html")
    page = html[html.index('data-page="rf"') :]
    page = page[: page.index("</section>")]
    assert "was not received by any of our stations" in page
    assert "not for navigation" in page


# --- phases 3 and 4: APRS, radiosondes, weather sensors ---------------


def test_every_kind_is_stored_and_has_an_id_rule() -> None:
    """A kind with no rule would raise a KeyError in the writer, not be refused."""
    assert STORED_KINDS == frozenset(KINDS)
    assert set(THING_ID) == set(KINDS)


@pytest.mark.parametrize(
    ("kind", "thing_id"),
    [
        ("adsb", "a1b2c3"),
        ("adsb", "~a1b2c3"),
        ("uat", "a1b2c3"),
        ("aprs", "kd7abc-9"),
        ("aprs", "kd7abc"),
        ("aprs", "n0call-15"),
        ("sonde", "v1234567"),
        ("sonde", "dfm-21012345"),
        ("ism", "acurite-tower-1234"),
        ("ism", "fineoffset-wh51-0a3b"),
        ("ism", "lacrosse-tx141thbv2-17"),
    ],
)
def test_an_id_of_the_right_shape_is_accepted(kind: str, thing_id: str) -> None:
    assert THING_ID[kind].match(thing_id)


@pytest.mark.parametrize(
    ("kind", "thing_id"),
    [
        # A callsign is not an aircraft address, and the reverse.
        ("adsb", "kd7abc-9"),
        ("aprs", "a1b2c3d4e5"),
        ("aprs", "kd7abc-100"),
        ("aprs", "kd7abc-"),
        ("aprs", "kd7abc>apdw16"),
        ("sonde", "-v1234567"),
        ("sonde", "v123 4567"),
        ("ism", "-acurite"),
        ("ism", "acurite tower 1234"),
        ("ism", "a" * 65),
        ("ism", "<script>"),
    ],
)
def test_an_id_of_the_wrong_shape_is_refused(kind: str, thing_id: str) -> None:
    assert not THING_ID[kind].match(thing_id)


def _ism(thing_id: str, meta: dict[str, object] | None) -> Observation:
    return Observation.model_validate(
        {"id": thing_id, "t": NOW, "lat": 33.5, "lon": -112.0, "meta": meta}
    )


def test_the_ism_model_comes_from_meta_even_when_it_holds_a_dash() -> None:
    """Splitting the id would make `acurite` of `acurite-tower-1234`."""
    obs = _ism("acurite-tower-1234", {"model": "Acurite-Tower", "id": 1234})
    assert ism_model(obs) == "acurite-tower"


@pytest.mark.parametrize(
    "meta",
    [
        None,
        {},
        {"model": ""},
        {"model": 7},
        # The id names another device than meta does.
        {"model": "Fineoffset-WH51"},
        # A prefix of the model in the id is not the model.
        {"model": "Acurite-Tower-Plus"},
    ],
)
def test_an_ism_reading_without_a_matching_model_is_malformed(
    meta: dict[str, object] | None,
) -> None:
    assert ism_model(_ism("acurite-tower-1234", meta)) is None


def test_the_ism_allow_list_is_read_as_lower_case_and_empty_by_default() -> None:
    assert Settings(_env_file=None).rf_ism_allow == []
    assert rules_from(Settings(_env_file=None)).ism_allow == frozenset()
    settings = Settings(_env_file=None, rf_ism_allow="Acurite-Tower, Fineoffset-WH51")
    assert rules_from(settings).ism_allow == frozenset({"acurite-tower", "fineoffset-wh51"})


def test_direct_is_optional_so_older_agents_still_validate() -> None:
    """A v1 field added later must be optional, or every running agent breaks."""
    older = Batch.model_validate(_batch(kind="aprs", obs=[{**_bare_obs(), "id": "kd7abc-9"}]))
    assert older.obs[0].direct is None
    newer = Batch.model_validate(
        _batch(kind="aprs", obs=[{**_bare_obs(), "id": "kd7abc-9", "direct": True}])
    )
    assert newer.obs[0].direct is True


def _bare_obs() -> dict[str, object]:
    return {"t": "2026-09-22T17:59:58Z", "lat": 33.5, "lon": -112.0}


def test_the_tooltip_shows_a_comment_whole() -> None:
    """A comment is what a person typed. It is never cut to fit.

    Other `meta` fields are cut to 40 characters and to a few entries.
    The comment is kept out of that list, so neither cut can reach it,
    and it wraps instead. Both tooltips that show one are checked.
    """
    rf = _static("rf.js")
    assert "const { comment, ...meta } = row.meta || {};" in rf
    assert "'comment'" in rf[rf.index("const APRS_KEYS") : rf.index("function aprsTooltip")]
    lines = [text for text in rf.splitlines() if "'rf-comment'" in text]
    assert len(lines) == 2, lines
    for line in lines:
        assert re.search(r"text: String\((meta\.)?comment\)", line), line
        assert "slice" not in line, line
    assert re.search(r"\.rf-tip \.rf-comment \{[^}]*white-space: normal", _static("app.css"))


# --- how an APRS packet reached the station (design 5.1) ---------------


def _aprs(thing_id: str, **fields: object) -> Observation:
    return Observation.model_validate(
        {"id": thing_id, "t": NOW, "lat": 33.6, "lon": -112.1, "rssi_db": -80.0, **fields}
    )


@pytest.mark.parametrize(
    "thing_id",
    ["cw1234", "kf7abcdef-15", ";eoc_tempe", ";146.94-px", ";field_day"],
)
def test_internet_sources_objects_and_items_have_aprs_ids(thing_id: str) -> None:
    assert THING_ID["aprs"].match(thing_id)


@pytest.mark.parametrize("thing_id", [";", "; x", ";a/b", ";a#b", ";toolongname", "kd7abc-100"])
def test_a_bad_object_or_station_id_is_refused(thing_id: str) -> None:
    assert not THING_ID["aprs"].match(thing_id)


def test_a_direct_packet_is_a_hearing_of_the_sender_where_it_is() -> None:
    assert hearings("aprs", _aprs("na7sv-9", direct=True)) == [
        Hearing("na7sv-9", -80.0, 33.6, -112.1)
    ]


def test_a_relayed_packet_credits_the_digipeater_and_places_nothing() -> None:
    """The station heard W7MOT-3, at W7MOT-3's level, not the sender."""
    found = hearings("aprs", _aprs("w7sa-12", direct=False, via="W7MOT-3"))
    assert found == [Hearing("w7mot-3", -80.0, None, None)]


@pytest.mark.parametrize(
    "fields",
    [
        {"direct": False},
        {},
        {"direct": False, "via": "wide2-1*"},
        {"direct": False, "via": "WIDE2-1"},
        {"direct": False, "via": "wide1"},
        {"direct": False, "via": "tcpip"},
        {"direct": False, "via": "qar"},
    ],
)
def test_a_relayed_packet_through_an_unnamed_digipeater_credits_nobody(
    fields: dict[str, object],
) -> None:
    """An untraced alias, or an older agent that sends no flag: no hearing."""
    assert hearings("aprs", _aprs("w7sa-12", **fields)) == []


def test_an_object_is_never_heard_but_its_sender_is() -> None:
    """An object's position is not where its transmitter is."""
    found = hearings("aprs", _aprs(";field_day", direct=True, via="kd7abc"))
    assert found == [Hearing("kd7abc", -80.0, None, None)]


def test_a_blurred_sender_is_counted_but_places_no_cell() -> None:
    assert hearings("aprs", _aprs("kd7abc", direct=True, precision_m=18_500)) == [
        Hearing("kd7abc", -80.0, None, None)
    ]
    # Blurred less than a cell still places it.
    assert hearings("aprs", _aprs("kd7abc", direct=True, precision_m=185)) == [
        Hearing("kd7abc", -80.0, 33.6, -112.1)
    ]


def test_every_other_kind_is_heard_directly_whatever_it_says() -> None:
    obs = _aprs("a1b2c3", direct=False, via="w7mot-3")
    assert hearings("adsb", obs) == [Hearing("a1b2c3", -80.0, 33.6, -112.1)]


def test_the_stored_meta_says_how_it_was_heard_and_the_agent_cannot_forge_it() -> None:
    obs = _aprs(
        "w7sa-12",
        direct=False,
        via="W7MOT-3",
        precision_m=185.0,
        meta={"comment": "hi", "direct": True, "via": "nobody"},
    )
    assert aprs_meta(obs) == {
        "comment": "hi",
        "direct": False,
        "via": "w7mot-3",
        "precision_m": 185.0,
    }
    # No via, no precision: the keys are removed, not left as the agent sent them.
    bare = _aprs("kd7abc", direct=True, meta={"via": "forged", "precision_m": 1})
    assert aprs_meta(bare) == {"direct": True}


def test_the_tooltip_says_how_an_aprs_packet_was_heard() -> None:
    rf = _static("rf.js")
    for phrase in (
        "Heard through ",
        "Repeated by a digipeater that did not sign the path",
        "Repeated by ",
        "From the internet, put on the air by ",
        "not a transmitter",
        # We never blurred it: the wording must say who did.
        "The sender blurred its own position",
    ):
        assert phrase in rf, phrase


# --- the raw frame, for the RF table ------------------------------------


def test_raw_is_optional_and_an_over_long_one_is_dropped_not_the_batch() -> None:
    """One bad frame must not cost the other 99 points, or be cut to fit."""
    obs = [
        {**_bare_obs(), "id": "kd7abc-9", "raw": "KD7ABC-9>APRS,WIDE2-1:!3330.00N/11200.00W>"},
        {**_bare_obs(), "id": "kd7abc-8", "raw": "x" * (MAX_RAW_CHARS + 1)},
        {**_bare_obs(), "id": "kd7abc-7"},
    ]
    batch = Batch.model_validate(_batch(kind="aprs", obs=obs))
    assert [o.raw for o in batch.obs] == [obs[0]["raw"], None, None]


def test_raw_is_stored_from_the_contract_field_and_cannot_be_forged_in_meta() -> None:
    forged = {"comment": "hi", "raw": "not what I sent"}
    aircraft = _aprs("a1b2c3", raw="8D4840D6202CC371C32CE0576098", meta=forged)
    assert stored_meta("adsb", aircraft) == {"comment": "hi", "raw": "8D4840D6202CC371C32CE0576098"}
    # No raw sent: the forged key is removed, not kept.
    assert stored_meta("adsb", _aprs("a1b2c3", meta=forged)) == {"comment": "hi"}
    # APRS keeps its hearing facts beside it.
    aprs = stored_meta("aprs", _aprs("kd7abc", direct=True, raw="KD7ABC>APRS:>hi"))
    assert aprs == {"direct": True, "raw": "KD7ABC>APRS:>hi"}
    assert stored_meta("sonde", _aprs("v1234567")) is None


def test_the_rf_page_has_a_table_with_the_raw_frame_beside_the_decoded() -> None:
    rf = _static("rf.js")
    html = _static("index.html")
    assert "data-rf-table-toggle" in html and "data-rf-table-grid" in html
    for label in ("'ICAO'", "'Callsign'", "'Squawk'", "'How heard'", "'Sent with'", "'Raw'"):
        assert f"label: {label}" in rf, label
    # The raw frame is set as text inside <code>, like every other cell.
    assert "el('code', { class: 'rf-raw', text })" in rf
