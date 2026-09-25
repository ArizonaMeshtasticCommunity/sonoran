"""The RF map's message contract and its small rules (docs/design/rf-map.md)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from sonoran.config import Settings
from sonoran.rf.ingest import decode, rules_from
from sonoran.rf.schema import (
    KINDS,
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
from sonoran.rf.store import Rules, floor_time, guarded_time, ism_model

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
