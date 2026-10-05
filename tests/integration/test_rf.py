"""The RF map against TimescaleDB, written as the real ingest role.

Every write goes through `azmsh_ingest`, so these tests also prove the
column grants of revision 0013 are enough: the role cannot read the RF
tables, and each upsert is an insert that does nothing on conflict and
then an update. See `docs/design/rf-map.md` section 5.
"""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.rf.guard import Guard
from sonoran.rf.schema import Batch, Custom, Registry, Spectrum, Status
from sonoran.rf.store import (
    Rules,
    Tally,
    store_batch,
    store_custom,
    store_registry,
    store_spectrum,
    store_status,
)
from tests.integration.conftest import role_url


@pytest.fixture
def clean(migrated_engine):  # type: ignore[no-untyped-def]
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE rf_station, rf_source, rf_track, rf_heard, rf_latest, "
                "rf_spectrum, rf_spectrum_hour, rf_custom, rf_trust, rf_hidden_mod, "
                "rf_operator_log"
            )
        )
    yield


def _batch(station: str, kind: str, obs: list[dict[str, object]]) -> Batch:
    return Batch.model_validate(
        {"v": 1, "station": station, "kind": kind, "sent": datetime.now(UTC), "obs": obs}
    )


def _obs(icao: str, when: datetime, rssi: float | None, lat: float = 33.5) -> dict[str, object]:
    return {"id": icao, "t": when, "lat": lat, "lon": -112.0, "alt_m": 3000, "rssi_db": rssi}


async def _write(
    timescale_url: str,
    *messages: Batch | Status | Registry | Custom | str,
    rules: Rules | None = None,
    guard: Guard | None = None,
) -> list[Tally]:
    """Write each message as the ingest role. A bare station id removes
    that station's registry entry, as an empty retained message does.
    With a `guard`, its trust levels are read first, as the ingest role."""
    engine = create_async_engine(role_url(timescale_url, "azmsh_ingest"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tallies: list[Tally] = []
    try:
        if guard is not None:
            async with factory() as session:
                await guard.refresh(session)
        for message in messages:
            async with factory() as session:
                received = datetime.now(UTC)
                if isinstance(message, Status):
                    await store_status(session, message, received, guard)
                elif isinstance(message, Custom):
                    tallies.append(
                        await store_custom(session, message, received, rules or Rules(), guard)
                    )
                elif isinstance(message, Registry):
                    await store_registry(session, message.station, message, received)
                elif isinstance(message, str):
                    await store_registry(session, message, None, received)
                else:
                    tallies.append(
                        await store_batch(session, message, received, rules or Rules(), guard)
                    )
                await session.commit()
    finally:
        await engine.dispose()
    return tallies


def _rows(migrated_engine, sql: str) -> list:  # type: ignore[no-untyped-def]
    with migrated_engine.begin() as connection:
        return list(connection.execute(text(sql)))


def _client(timescale_url: str, **extra: object) -> TestClient:
    settings = Settings(
        _env_file=None, database_url_api=role_url(timescale_url, "azmsh_api"), **extra
    )
    return TestClient(create_app(settings))


def test_two_stations_hearing_one_aircraft_make_one_point_the_first_received(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).replace(second=5, microsecond=0)
    asyncio.run(
        _write(
            timescale_url,
            _batch("north-site", "adsb", [_obs("a1b2c3", now, -30.0, lat=33.6)]),
            _batch("south-site", "adsb", [_obs("a1b2c3", now + timedelta(seconds=2), -12.0)]),
            _batch("north-site", "adsb", [_obs("a1b2c3", now + timedelta(seconds=4), -31.0)]),
        )
    )
    track = _rows(migrated_engine, "SELECT station_id, rssi_db, lat FROM rf_track")
    assert len(track) == 1, "one point per aircraft per bucket, across stations"
    # The first received, never the loudest: a level is a number the
    # station reports, and a modified agent could claim any (#324).
    assert track[0].station_id == "north-site" and track[0].rssi_db == -30.0

    heard = {
        r.station_id: r
        for r in _rows(migrated_engine, "SELECT station_id, heard, best_rssi_db FROM rf_heard")
    }
    assert heard["north-site"].heard == 2
    assert heard["north-site"].best_rssi_db == -30.0
    assert heard["south-site"].heard == 1

    latest = _rows(migrated_engine, "SELECT t, station_id FROM rf_latest")
    assert len(latest) == 1
    assert latest[0].station_id == "north-site", "the newest point wins rf_latest"


def test_an_older_point_never_overwrites_a_newer_one(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    asyncio.run(
        _write(
            timescale_url,
            _batch("north-site", "adsb", [_obs("a1b2c3", now, -20.0, lat=33.7)]),
            _batch("south-site", "adsb", [_obs("a1b2c3", now - timedelta(seconds=30), -5.0)]),
        )
    )
    latest = _rows(migrated_engine, "SELECT lat FROM rf_latest")
    assert latest[0].lat == 33.7


def test_hidden_aircraft_are_not_stored(timescale_url: str, migrated_engine, clean: None) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    tallies = asyncio.run(
        _write(
            timescale_url,
            _batch("north-site", "adsb", [_obs("a1b2c3", now, -20.0), _obs("bbbbbb", now, -9.0)]),
            _batch("north-site", "uat", [_obs("cccccc", now, -15.0)]),
            rules=Rules(hidden=frozenset({"bbbbbb"})),
        )
    )
    assert (tallies[0].stored, tallies[0].hidden) == (1, 1)
    assert tallies[1].stored == 1
    ids = {r.thing_id for r in _rows(migrated_engine, "SELECT thing_id FROM rf_latest")}
    assert ids == {"a1b2c3", "cccccc"}


def test_aprs_and_sondes_are_stored_and_a_bad_id_is_refused(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    tallies = asyncio.run(
        _write(
            timescale_url,
            _batch(
                "north-site",
                "aprs",
                [
                    {"id": "KD7ABC-9", "t": now, "lat": 33.4, "lon": -112.1},
                    # An aircraft address is not a callsign with an SSID.
                    {"id": "kd7abc-100", "t": now, "lat": 33.4, "lon": -112.1},
                ],
            ),
            _batch(
                "north-site",
                "sonde",
                [{"id": "V1234567", "t": now, "lat": 33.6, "lon": -112.3, "alt_m": 18000}],
            ),
        )
    )
    assert (tallies[0].stored, tallies[0].rejected) == (1, 1)
    assert tallies[1].stored == 1
    rows = {
        (r.kind, r.thing_id) for r in _rows(migrated_engine, "SELECT kind, thing_id FROM rf_latest")
    }
    assert rows == {("aprs", "kd7abc-9"), ("sonde", "v1234567")}


def test_a_relayed_aprs_packet_is_mapped_but_not_heard(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    """A digipeated packet says where the sender is, not how far we hear.

    Missing `direct` counts as relayed: a NULL is not an unknown to
    include (AGENTS.md 9.22). An aircraft carries no such field and is
    always heard.
    """
    now = datetime.now(UTC)
    (aprs, adsb) = asyncio.run(
        _write(
            timescale_url,
            _batch(
                "north-site",
                "aprs",
                [
                    {
                        "id": "na7sv-9",
                        "t": now,
                        "lat": 33.6,
                        "lon": -112.1,
                        "rssi_db": -80.0,
                        "direct": True,
                    },
                    # Tucson, through a mountaintop digipeater.
                    {
                        "id": "w7sa-12",
                        "t": now,
                        "lat": 32.1,
                        "lon": -110.9,
                        "rssi_db": -70.0,
                        "direct": False,
                    },
                    # An older agent that sends no flag at all.
                    {"id": "kg0km", "t": now, "lat": 33.6, "lon": -112.3, "rssi_db": -75.0},
                ],
            ),
            _batch("north-site", "adsb", [_obs("a1b2c3", now, -20.0)]),
        )
    )
    assert (aprs.stored, aprs.relayed) == (3, 2)
    assert (adsb.stored, adsb.relayed) == (1, 0)

    latest = {
        r.thing_id: r.rssi_db
        for r in _rows(migrated_engine, "SELECT thing_id, rssi_db FROM rf_latest")
    }
    # Every one is on the map. Only the direct one keeps a signal level.
    assert latest == {"na7sv-9": -80.0, "w7sa-12": None, "kg0km": None, "a1b2c3": -20.0}
    heard = {r.thing_id for r in _rows(migrated_engine, "SELECT thing_id FROM rf_heard")}
    assert heard == {"na7sv-9", "a1b2c3"}


def test_a_digipeater_is_credited_and_placed_from_its_own_beacon(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    """The station heard W7MOT-3, so the heard layer says so, where W7MOT-3 is.

    The relayed packet is louder than the digipeater's own beacon. The
    louder hearing places nothing, so it must not erase the position the
    beacon gave. An object is never a hearing, and its sender, never
    heard on its own, has no position to be drawn at.
    """
    now = datetime.now(UTC)
    (tally,) = asyncio.run(
        _write(
            timescale_url,
            _batch(
                "north-site",
                "aprs",
                [
                    {
                        "id": "w7mot-3",
                        "t": now,
                        "lat": 33.62,
                        "lon": -112.56,
                        "rssi_db": -60.0,
                        "direct": True,
                    },
                    {
                        "id": "w7sa-12",
                        "t": now,
                        "lat": 32.1,
                        "lon": -110.9,
                        "rssi_db": -50.0,
                        "direct": False,
                        "via": "W7MOT-3",
                    },
                    {
                        "id": ";field_day",
                        "t": now,
                        "lat": 33.4,
                        "lon": -111.9,
                        "rssi_db": -70.0,
                        "direct": True,
                        "via": "kd7abc",
                        "meta": {"owner": "kd7abc", "object": "object"},
                    },
                ],
            ),
        )
    )
    assert (tally.stored, tally.relayed) == (3, 2)
    heard = {
        r.thing_id: (r.heard, r.best_rssi_db, r.lat)
        for r in _rows(migrated_engine, "SELECT thing_id, heard, best_rssi_db, lat FROM rf_heard")
    }
    assert heard == {"w7mot-3": (2, -50.0, 33.62), "kd7abc": (1, -70.0, None)}
    meta = {
        r.thing_id: r.meta for r in _rows(migrated_engine, "SELECT thing_id, meta FROM rf_latest")
    }
    assert meta["w7sa-12"] == {"direct": False, "via": "w7mot-3"}
    assert meta[";field_day"]["owner"] == "kd7abc"

    with _client(timescale_url) as client:
        cells = client.get("/api/rf/heard/north-site?kind=aprs").json()["cells"]
        track = client.get("/api/rf/track/aprs/%3Bfield_day").json()
    # One cell, the digipeater's. Tucson and the object are not reach.
    assert [(c["lat"], c["lon"], c["heard"]) for c in cells] == [(33.62, -112.56, 2)]
    assert len(track["points"]) == 1


def _sensor(thing_id: str, model: str | None, when: datetime) -> dict[str, object]:
    meta: dict[str, object] = {"temperature_c": 31.5}
    if model is not None:
        meta["model"] = model
    return {"id": thing_id, "t": when, "lat": 33.5, "lon": -112.0, "meta": meta}


def test_a_sensor_is_stored_only_when_its_model_is_allowed(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    """rtl_433 hears the neighbours' tyres and doorbells too (design 8)."""
    now = datetime.now(UTC)
    sensors = _batch(
        "north-site",
        "ism",
        [
            _sensor("acurite-tower-1234", "Acurite-Tower", now),
            # A tyre sensor: decoded, never allow-listed.
            _sensor("schrader-00a1b2c3", "Schrader", now),
            # A prefix of an allowed model is not that model.
            _sensor("acurite-5", "Acurite", now),
            # Malformed: no model, and a model the id does not carry.
            _sensor("acurite-tower-99", None, now),
            _sensor("acurite-tower-77", "Fineoffset-WH51", now),
        ],
    )
    # The default: an empty allow-list stores nothing. Malformed readings
    # are still told apart from readings nobody allowed.
    (closed,) = asyncio.run(_write(timescale_url, sensors, rules=Rules()))
    assert (closed.stored, closed.not_allowed, closed.rejected) == (0, 3, 2)
    assert _rows(migrated_engine, "SELECT 1 FROM rf_latest WHERE kind = 'ism'") == []

    (opened,) = asyncio.run(
        _write(timescale_url, sensors, rules=Rules(ism_allow=frozenset({"acurite-tower"})))
    )
    assert (opened.stored, opened.not_allowed, opened.rejected) == (1, 2, 2)
    ids = {
        r.thing_id
        for r in _rows(migrated_engine, "SELECT thing_id FROM rf_latest WHERE kind = 'ism'")
    }
    assert ids == {"acurite-tower-1234"}


def test_a_heartbeat_is_kept_and_updated(timescale_url: str, migrated_engine, clean: None) -> None:  # type: ignore[no-untyped-def]
    def status(heard: int) -> Status:
        return Status.model_validate(
            {
                "v": 1,
                "station": "north-site",
                "sent": datetime.now(UTC),
                "lat": 33.4,
                "lon": -111.9,
                "precision_m": 1000,
                "kinds": ["adsb"],
                "counts": {"heard": heard, "sent": 10, "dropped": heard - 10},
            }
        )

    asyncio.run(_write(timescale_url, status(100), status(250)))
    rows = _rows(migrated_engine, "SELECT heard, dropped FROM rf_station")
    assert len(rows) == 1
    assert (rows[0].heard, rows[0].dropped) == (250, 240)


def test_the_api_serves_stations_latest_tracks_and_heard_cells(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    asyncio.run(
        _write(
            timescale_url,
            Status.model_validate(
                {"v": 1, "station": "north-site", "sent": now, "lat": 33.4, "lon": -111.9}
            ),
            _batch(
                "north-site",
                "adsb",
                [_obs("a1b2c3", now - timedelta(seconds=40), -20.0), _obs("dddddd", now, -8.0)],
            ),
            _batch("north-site", "adsb", [_obs("a1b2c3", now, -18.0, lat=33.55)]),
        )
    )
    with _client(timescale_url, rf_hidden_ids=["dddddd"]) as client:
        stations = client.get("/api/rf/stations").json()
        latest = client.get("/api/rf/latest?kind=adsb&minutes=5")
        track = client.get("/api/rf/track/adsb/A1B2C3?hours=1").json()
        heard = client.get("/api/rf/heard/north-site?hours=1").json()
        assert client.get("/api/rf/heard/Not A Station").status_code == 422
        assert client.get("/api/rf/track/ais/a1b2c3").status_code == 404
        assert client.get("/api/rf/track/adsb/dddddd").status_code == 404

    assert stations[0]["station"] == "north-site" and stations[0]["online"] is True
    body = latest.json()
    assert [row["id"] for row in body] == ["a1b2c3"], "a hidden aircraft is never shown"
    assert latest.headers["X-Total-Count"] == "1"
    assert [p["lat"] for p in track["points"]] == [33.5, 33.55], "oldest first"
    assert heard["cells"] and all(cell["heard"] >= 1 for cell in heard["cells"])


def test_rf_never_counts_as_meshtastic(timescale_url: str, migrated_engine, clean: None) -> None:  # type: ignore[no-untyped-def]
    """RF is separate: it adds no node, packet, upload or gateway.

    RF stations are not Meshtastic gateways, and what they hear is not
    a mesh packet. The dashboard's counts must not move.
    """
    with _client(timescale_url) as client:
        before = client.get("/api/stats").json()
    now = datetime.now(UTC)
    asyncio.run(
        _write(
            timescale_url,
            Status.model_validate(
                {"v": 1, "station": "north-site", "sent": now, "lat": 33.4, "lon": -111.9}
            ),
            _batch("north-site", "adsb", [_obs("a1b2c3", now, -20.0), _obs("eeeeee", now, -9.0)]),
        )
    )
    with _client(timescale_url) as client:
        after = client.get("/api/stats").json()
        kinds = client.get("/api/rf/kinds").json()
    for key in ("node_count", "packet_count", "observation_count", "gateway_count"):
        assert after[key] == before[key], key
    assert kinds == {
        "known": ["adsb", "uat", "aprs", "sonde", "ism"],
        "stored": ["adsb", "aprs", "ism", "sonde", "uat"],
        "views": ["spectrum", "sweeps", "custom"],
    }


def _minute(
    station: str, when: datetime, p50: list[int | None], busy: list[int | None]
) -> Spectrum:
    return Spectrum.model_validate(
        {
            "v": 1,
            "station": station,
            "kind": "spectrum",
            "t": when,
            "f_start_hz": 902_000_000,
            "bin_hz": 50_000,
            "sweeps": 12,
            "gain_db": 32.8,
            "p50": p50,
            "p95": [None if v is None else v + 40 for v in p50],
            "peak": [None if v is None else v + 90 for v in p50],
            "busy": busy,
        }
    )


async def _write_spectrum(timescale_url: str, *minutes: Spectrum) -> list[bool]:
    engine = create_async_engine(role_url(timescale_url, "azmsh_ingest"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    stored: list[bool] = []
    try:
        for minute in minutes:
            async with factory() as session:
                stored.append(await store_spectrum(session, minute, datetime.now(UTC), Rules()))
                await session.commit()
    finally:
        await engine.dispose()
    return stored


def test_a_minute_of_the_band_is_stored_once_by_the_ingest_role(  # type: ignore[no-untyped-def]
    timescale_url: str, migrated_engine, clean: None
) -> None:
    """The ingest role can write it, not read it, and a repeat is ignored."""
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    first = _minute("west-site", now + timedelta(seconds=7), [-500, -490, None], [1, 50, None])
    stored = asyncio.run(_write_spectrum(timescale_url, first, first))
    assert stored == [True, False]
    with migrated_engine.begin() as connection:
        minute, p50 = connection.execute(text("SELECT t, p50 FROM rf_spectrum")).one()
    assert minute == now, "floored to the minute"
    assert p50 == [-500, -490, None], "an unswept bin stays NULL"


def test_the_spectrum_api_buckets_a_long_window_and_keeps_bursts(  # type: ignore[no-untyped-def]
    timescale_url: str, migrated_engine, clean: None
) -> None:
    """A day is sent as at most 240 rows, and a burst is never averaged away."""
    # Inside the ten minutes the clock guard trusts. An older stamp is a
    # clock fault and is stored at the minute it arrived (design 5.3).
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    minutes = [
        _minute("west-site", now - timedelta(minutes=i), [-500, -500, -500], [0, 0, 0])
        for i in range(8)
    ]
    # One loud minute on bin 1, inside what will be one bucket.
    minutes[3] = _minute("west-site", now - timedelta(minutes=3), [-500, -300, -500], [0, 80, 0])
    asyncio.run(_write_spectrum(timescale_url, *minutes))
    with _client(timescale_url) as client:
        hour = client.get("/api/rf/spectrum/west-site?hours=1").json()
        day = client.get("/api/rf/spectrum/west-site?hours=24").json()
        channels = client.get("/api/rf/channels").json()
        stations = client.get("/api/rf/stations").json()
        refused = client.get("/api/rf/spectrum/NOT_A_STATION")
    assert hour["bucket_minutes"] == 1
    assert len(_swept(hour)) == 8
    # Every other minute of the hour is there too, as not swept.
    assert len(hour["rows"]) in (60, 61) and not hour["rows"][0]["minutes"]
    assert hour["bins"] == 3 and hour["f_start_hz"] == 902_000_000
    assert hour["range"]["id"] == "-:902000000:50000:3"
    assert day["bucket_minutes"] == 6
    assert len(_swept(day)) <= 3
    loud = max(_swept(day), key=lambda row: row["p95"][1])
    assert loud["p95"][1] == -260, "the highest 95th percentile in the bucket is kept"
    assert loud["p50"][1] == -500, "the median of the medians ignores one loud minute"
    by_name = {item["name"]: item for item in channels["channels"]}
    assert by_name["LongFast"]["centre_hz"] == 906_875_000
    assert refused.status_code == 422
    # The station has no heartbeat, so it is not listed; spectrum alone
    # does not invent a station.
    assert all(item["station"] != "west-site" for item in stations)


def _swept(answer: dict) -> list[dict]:  # type: ignore[type-arg]
    """The rows of a waterfall that hold a sweep."""
    return [row for row in answer["rows"] if row["minutes"]]


def _beat(station: str, source: str | None, kinds: list[str], heard: int) -> Status:
    body: dict[str, object] = {
        "v": 1,
        "station": station,
        "sent": datetime.now(UTC),
        "lat": 33.4,
        "lon": -111.9,
        "precision_m": 1000,
        "kinds": kinds,
        "agent_version": "0.4.0",
        "counts": {"heard": heard, "sent": heard, "dropped": 0},
    }
    if source:
        body["source"] = source
    return Status.model_validate(body)


def _registry(station: str, sources: list[str]) -> Registry:
    return Registry.model_validate(
        {
            "v": 1,
            "station": station,
            "sent": datetime.now(UTC),
            "display_name": "Tempe roof",
            "owner": "Logan",
            "sources": sources,
        }
    )


def test_two_sources_make_one_location_with_both_listed(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    """#305: an ADS-B Pi and a sweeper Pi at one site are one station.

    Written as the ingest role, so this also proves the 0018 grants. A
    sweeper with no position must not erase the ADS-B Pi's position.
    """
    sweeper = _beat("tempe-roof", "sweeper", [], 0)
    sweeper = sweeper.model_copy(update={"lat": None, "lon": None, "precision_m": None})
    asyncio.run(
        _write(
            timescale_url,
            _registry("tempe-roof", ["adsb-pi", "sweeper", "spare"]),
            _beat("tempe-roof", "adsb-pi", ["adsb", "uat"], 40),
            sweeper,
            # A second heartbeat updates the row, it does not add one.
            _beat("tempe-roof", "adsb-pi", ["adsb", "uat"], 50),
        )
    )
    assert len(_rows(migrated_engine, "SELECT 1 FROM rf_source")) == 2

    with _client(timescale_url) as client:
        stations = client.get("/api/rf/stations").json()

    assert len(stations) == 1
    site = stations[0]
    assert site["station"] == "tempe-roof"
    assert site["display_name"] == "Tempe roof" and site["owner"] == "Logan"
    assert site["registered"] is True and site["online"] is True
    assert (site["lat"], site["lon"]) == (33.4, -111.9)
    assert site["kinds"] == ["adsb", "uat"]
    assert site["counts"] == {"heard": 50, "sent": 50, "dropped": 0}
    by_name = {s["source"]: s for s in site["sources"]}
    assert set(by_name) == {"adsb-pi", "sweeper", "spare"}
    assert by_name["adsb-pi"]["online"] is True
    assert by_name["spare"]["last_seen"] is None, "registered, no heartbeat yet"
    assert all(s["registered"] for s in site["sources"])


def test_a_location_in_the_registry_shows_before_its_first_heartbeat(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    asyncio.run(_write(timescale_url, _registry("new-site", ["pi"])))
    with _client(timescale_url) as client:
        site = client.get("/api/rf/stations").json()[0]
    assert site["station"] == "new-site"
    assert site["last_seen"] is None and site["online"] is False
    assert site["lat"] is None


def test_removing_a_registry_entry_keeps_the_station_and_its_heartbeats(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    asyncio.run(
        _write(
            timescale_url,
            _registry("tempe-roof", ["adsb-pi"]),
            _beat("tempe-roof", "adsb-pi", ["adsb"], 5),
            "tempe-roof",
        )
    )
    with _client(timescale_url) as client:
        site = client.get("/api/rf/stations").json()[0]
    assert site["registered"] is False and site["display_name"] is None
    assert [s["source"] for s in site["sources"]] == ["adsb-pi"]
    assert site["sources"][0]["registered"] is False


def test_an_agent_without_a_source_still_reads_as_before(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    """The agents in the field send no source. Their station is unchanged."""
    asyncio.run(_write(timescale_url, _beat("north-site", None, ["adsb", "aprs"], 7)))
    rows = _rows(migrated_engine, "SELECT kinds, heard FROM rf_station")
    assert rows == [(["adsb", "aprs"], 7)]
    with _client(timescale_url) as client:
        site = client.get("/api/rf/stations").json()[0]
    assert site["kinds"] == ["adsb", "aprs"]
    assert site["counts"]["heard"] == 7
    assert [s["source"] for s in site["sources"]] == [None]


async def _rollup(timescale_url: str, now: datetime) -> int:
    """Run the hourly rollup as the jobs role, as if it were `now`."""
    from sonoran.jobs import rf_rollup

    engine = create_async_engine(role_url(timescale_url, "azmsh_jobs"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as session:
            return await rf_rollup.run_once(session, now=now)
    finally:
        await engine.dispose()


def test_the_hourly_rollup_keeps_bursts_and_feeds_the_week_view(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    """The 3 and 7 day windows read hours rolled up by the jobs role.

    The ingest's clock guard stores an old stamp at the time it arrived,
    so the minutes are written now and the rollup is run as if it were
    two hours later, when their hour is finished.
    """
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    minutes = [
        _minute("west-site", now - timedelta(minutes=i), [-500, -500, -500], [0, 0, 0])
        for i in range(8)
    ]
    minutes[3] = _minute("west-site", now - timedelta(minutes=3), [-500, -300, -500], [0, 80, 0])
    asyncio.run(_write_spectrum(timescale_url, *minutes))

    later = now + timedelta(hours=2)
    built = asyncio.run(_rollup(timescale_url, later))
    rows = _rows(
        migrated_engine, "SELECT minutes, p50, p95, busy, peak, peak_min, t FROM rf_spectrum_hour"
    )
    # Eight minutes fall in one hour, or two when they straddle the hour.
    assert built == len(rows) and 1 <= len(rows) <= 2
    assert sum(row[0] for row in rows) == 8
    loud = max(rows, key=lambda row: row[2][1])
    assert loud[2][1] == -260, "the highest 95th percentile in the hour is kept"
    assert loud[1][1] == -500, "the median of the medians ignores one loud minute"
    assert loud[3][1] == round(80 / loud[0]), "busy is the mean over the hour's minutes"
    # The loudest moment, and the minute of the hour it happened in.
    assert loud[4][1] == -300 + 90, "peak keeps the loudest single moment"
    loud_minute = now - timedelta(minutes=3)
    assert loud[5][1] == int((loud_minute - loud[6]).total_seconds() // 60)

    # Run again: the recent hours are built again, never twice over.
    asyncio.run(_rollup(timescale_url, later))
    assert len(_rows(migrated_engine, "SELECT 1 FROM rf_spectrum_hour")) == len(rows)

    with _client(timescale_url) as client:
        week = client.get("/api/rf/spectrum/west-site?hours=168").json()
        three = client.get("/api/rf/spectrum/west-site?hours=72").json()
        too_long = client.get("/api/rf/spectrum/west-site?hours=169")
    assert week["bucket_minutes"] == 60 and three["bucket_minutes"] == 60
    assert len(_swept(week)) == len(rows)
    assert week["bins"] == 3 and week["sweeps_per_minute"] == 12
    assert max(row["p95"][1] for row in _swept(week)) == -260
    assert max(row["peak"][1] for row in _swept(week)) == -210
    assert all(len(row["peak_min"]) == 3 for row in _swept(week))
    assert too_long.status_code == 422


def test_full_resolution_is_two_hours_of_minutes_from_the_last_three_days(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    minutes = [
        _minute("west-site", now - timedelta(minutes=i), [-500, -500, -500], [0, 0, 0])
        for i in range(8)
    ]
    minutes[3] = _minute("west-site", now - timedelta(minutes=3), [-500, -300, -500], [0, 80, 0])
    asyncio.run(_write_spectrum(timescale_url, *minutes))
    start = (now - timedelta(minutes=30)).isoformat()
    with _client(timescale_url) as client:
        full = client.get("/api/rf/spectrum/west-site", params={"start": start}).json()
        empty = client.get(
            "/api/rf/spectrum/west-site",
            params={"start": (now - timedelta(days=2)).isoformat()},
        ).json()
        too_old = client.get(
            "/api/rf/spectrum/west-site",
            params={"start": (now - timedelta(days=3, minutes=5)).isoformat()},
        )
        future = client.get(
            "/api/rf/spectrum/west-site",
            params={"start": (now + timedelta(hours=1)).isoformat()},
        )
        naive = client.get("/api/rf/spectrum/west-site", params={"start": "2026-10-04T12:00:00"})
    assert full["bucket_minutes"] == 1 and full["hours"] == 2
    assert len(_swept(full)) == 8, "one row per minute"
    assert len(full["rows"]) == 120, "the minutes not swept are sent as such"
    assert "peak_min" not in _swept(full)[0], "a one-minute row needs no peak minute"
    assert max(row["peak"][1] for row in _swept(full)) == -210
    assert empty["rows"] == [] and empty["bucket_minutes"] == 1
    assert too_old.status_code == 422
    assert future.status_code == 422
    assert naive.status_code == 422


def test_the_rollup_finds_nothing_to_do_without_minutes(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    assert asyncio.run(_rollup(timescale_url, datetime.now(UTC))) == 0
    with _client(timescale_url) as client:
        week = client.get("/api/rf/spectrum/west-site?hours=168").json()
    assert week == {"station": "west-site", "hours": 168, "bucket_minutes": 60, "rows": []}


def test_purging_a_station_removes_its_rows_and_puts_back_honest_points(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    """`sonoran-rf-purge`: one bad station goes; the honest one stays.

    Both hear aircraft a1b2c3; the bad one is heard last, so it holds the
    latest position. After the purge the latest position comes back from
    the honest station's track.
    """
    from sonoran.rf.purge import purge, survey

    now = datetime.now(UTC)
    asyncio.run(
        _write(
            timescale_url,
            _beat("good-site", "pi", ["adsb"], 1),
            _beat("bad-site", "pi", ["adsb"], 1),
            # A minute apart: in another 20 s slot from the bad point, so the
            # bad station cannot take this one over in rf_track.
            _batch("good-site", "adsb", [_obs("a1b2c3", now - timedelta(seconds=60), -20.0)]),
            _batch("bad-site", "adsb", [_obs("a1b2c3", now, -5.0, lat=40.0)]),
            _batch("bad-site", "adsb", [_obs("bbbbbb", now, -5.0)]),
        )
    )
    asyncio.run(
        _write_spectrum(timescale_url, _minute("bad-site", now, [-500, -500, -500], [0, 0, 0]))
    )
    assert _rows(migrated_engine, "SELECT station_id FROM rf_latest WHERE thing_id = 'a1b2c3'") == [
        ("bad-site",)
    ]

    with migrated_engine.begin() as conn:
        dry = survey(conn, "bad-site")
    assert dry.counts["rf_station"] == 1 and dry.counts["rf_spectrum"] == 1
    assert dry.sources == ["pi"]

    with migrated_engine.begin() as conn:
        report = purge(conn, "bad-site")
    assert report.restored == 1, "a1b2c3 came back from good-site; bbbbbb had no one else"
    for table in (
        "rf_track",
        "rf_latest",
        "rf_heard",
        "rf_spectrum",
        "rf_spectrum_hour",
        "rf_custom",
        "rf_source",
        "rf_station",
    ):
        assert _rows(migrated_engine, f"SELECT 1 FROM {table} WHERE station_id = 'bad-site'") == []
    latest = _rows(migrated_engine, "SELECT thing_id, station_id, lat FROM rf_latest ORDER BY 1")
    assert latest == [("a1b2c3", "good-site", 33.5)]
    assert _rows(migrated_engine, "SELECT station_id FROM rf_station") == [("good-site",)]


# --- Any range, trust, and members' mods (#324) -----------------------


def _ranged(
    station: str,
    when: datetime,
    f_start: int,
    *,
    source: str | None = None,
    name: str | None = None,
    level: int = -500,
) -> Spectrum:
    body: dict[str, object] = {
        "v": 1,
        "station": station,
        "kind": "spectrum",
        "t": when,
        "f_start_hz": f_start,
        "bin_hz": 25_000,
        "sweeps": 12,
        "gain_db": 20.0,
        "p50": [level, level],
        "p95": [level + 40, level + 40],
        "peak": [level + 90, level + 90],
        "busy": [0, 10],
    }
    if source:
        body["source"] = source
    if name:
        body["name"] = name
    return Spectrum.model_validate(body)


def test_a_station_sweeping_two_ranges_keeps_both_and_offers_a_picker(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    """Two dongles at one station, in the same minutes: both are stored."""
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    minutes = []
    for i in range(3):
        when = now - timedelta(minutes=i)
        minutes += [
            _ranged("west-site", when, 902_000_000, level=-500),
            _ranged("west-site", when, 420_000_000, source="pi2", name="uhf", level=-400),
        ]
    stored = asyncio.run(_write_spectrum(timescale_url, *minutes))
    assert stored == [True] * 6, "a second range in the same minute is not a repeat"
    with _client(timescale_url) as client:
        ranges = client.get("/api/rf/spectrum/west-site/ranges").json()["ranges"]
        uhf = client.get(
            "/api/rf/spectrum/west-site", params={"hours": 1, "range": "pi2:420000000:25000:2"}
        ).json()
        ism = client.get(
            "/api/rf/spectrum/west-site", params={"hours": 1, "range": "-:902000000:25000:2"}
        ).json()
        bad = client.get("/api/rf/spectrum/west-site", params={"range": "pi2:<b>:1:2"})
        sweeps = client.get("/api/rf/sweeps").json()["ranges"]
    assert {r["id"] for r in ranges} == {"pi2:420000000:25000:2", "-:902000000:25000:2"}
    named = next(r for r in ranges if r["source"] == "pi2")
    assert named["name"] == "uhf" and named["f_end_hz"] == 420_050_000 and named["minutes"] == 3
    assert uhf["range"]["name"] == "uhf"
    assert {row["p50"][0] for row in _swept(uhf)} == {-400}
    assert {row["p50"][0] for row in _swept(ism)} == {-500}, "two ranges are never mixed"
    assert bad.status_code == 422
    assert [(r["f_start_hz"], r["minutes"]) for r in sweeps] == [
        (420_000_000, 3),
        (902_000_000, 3),
    ]

    later = now + timedelta(hours=2)
    asyncio.run(_rollup(timescale_url, later))
    hours = _rows(migrated_engine, "SELECT DISTINCT source, f_start_hz FROM rf_spectrum_hour")
    assert sorted(hours) == [("-", 902_000_000), ("pi2", 420_000_000)]


def test_a_dongle_taking_turns_shows_where_it_was_elsewhere_as_not_swept(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    minutes = [
        _ranged("west-site", now - timedelta(minutes=i), 902_000_000 if i % 2 else 420_000_000)
        for i in range(8)
    ]
    asyncio.run(_write_spectrum(timescale_url, *minutes))
    start = (now - timedelta(minutes=10)).isoformat()
    with _client(timescale_url) as client:
        full = client.get(
            "/api/rf/spectrum/west-site",
            params={"start": start, "range": "-:902000000:25000:2"},
        ).json()
    rows = {row["t"][:16]: row for row in full["rows"]}
    for i in range(8):
        key = (now - timedelta(minutes=i)).isoformat()[:16]
        assert bool(rows[key]["minutes"]) == bool(i % 2), key
        if not i % 2:
            assert "p50" not in rows[key], "a minute not swept carries no level"


def test_what_a_station_reports_it_sweeps_is_kept_and_shown_as_reported(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    beat = _beat("west-site", "pi2", [], 0).model_copy(
        update={
            "sweeps": Status.model_validate(
                {
                    "v": 1,
                    "station": "west-site",
                    "sent": now,
                    "sweeps": [
                        {
                            "tool": "rtl_power",
                            "f_start_hz": 420_000_000,
                            "f_end_hz": 420_050_000,
                            "bin_hz": 25_000,
                            "gain_db": 20,
                            "dwell_s": 60,
                            "command": "rtl_power -f 420000000:420050000:25000 -g 20 -",
                        },
                        {
                            "tool": "rtl_power",
                            "f_start_hz": 144_000_000,
                            "f_end_hz": 148_000_000,
                            "bin_hz": 10_000,
                            "gain_db": 20,
                            "dwell_s": 60,
                        },
                    ],
                }
            ).sweeps
        }
    )
    asyncio.run(_write(timescale_url, beat))
    asyncio.run(
        _write_spectrum(timescale_url, _ranged("west-site", now, 420_000_000, source="pi2"))
    )
    with _client(timescale_url) as client:
        sweeps = client.get("/api/rf/sweeps").json()["ranges"]
        station = client.get("/api/rf/stations").json()[0]
    measured = next(r for r in sweeps if r["f_start_hz"] == 420_000_000)
    assert measured["reported"]["command"].startswith("rtl_power -f 420000000")
    only = next(r for r in sweeps if r["f_start_hz"] == 144_000_000)
    assert only["minutes"] == 0 and only["id"] is None
    assert len(station["sources"][0]["sweeps"]) == 2
    assert station["trust"] == "new"


def _trust(migrated_engine, station: str, level: str, source: str = "*") -> None:  # type: ignore[no-untyped-def]
    from sonoran.rf.guard import TRUST_LEVELS
    from sonoran.rf.operator import set_trust

    with migrated_engine.begin() as conn:
        set_trust(conn, station, source, TRUST_LEVELS[level], None, "test")


def test_a_trusted_station_takes_a_shared_point_and_a_quarantined_one_adds_nothing(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    """Trust is set by an operator and read by the ingest role (revision 0020)."""
    _trust(migrated_engine, "good-site", "trusted")
    _trust(migrated_engine, "bad-site", "quarantined")
    now = datetime.now(UTC) - timedelta(seconds=2)
    tallies = asyncio.run(
        _write(
            timescale_url,
            _batch("new-site", "adsb", [_obs("a1b2c3", now, -10.0)]),
            _batch("good-site", "adsb", [_obs("a1b2c3", now, -40.0)]),
            _batch("new-site", "adsb", [_obs("a1b2c3", now, -5.0)]),
            _batch("bad-site", "adsb", [_obs("bbbbbb", now, -5.0)]),
            guard=Guard(),
        )
    )
    track = _rows(migrated_engine, "SELECT thing_id, station_id, trust FROM rf_track ORDER BY 1")
    assert track == [("a1b2c3", "good-site", 2)], "trusted beats new; quarantined adds nothing"
    assert tallies[-1].withheld == 1
    heard = _rows(migrated_engine, "SELECT station_id FROM rf_heard WHERE thing_id = 'bbbbbb'")
    assert heard == [("bad-site",)], "a quarantined station keeps its own view"
    log = _rows(migrated_engine, "SELECT actor, action, detail FROM rf_operator_log ORDER BY id")
    assert log[0] == ("test", "trust", "good-site: new -> trusted")


def test_a_station_cannot_take_shared_points_with_claims(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    """Maximal level, a clock a minute ahead, a position nothing could hear."""
    now = datetime.now(UTC)
    guard = Guard()
    honest = [_beat(name, None, ["adsb"], 1) for name in ("north-site", "south-site")]
    liar = _beat("liar-site", None, ["adsb"], 1)
    tallies = asyncio.run(
        _write(
            timescale_url,
            *honest,
            liar,
            _batch("north-site", "adsb", [_obs("a1b2c3", now, -30.0, lat=33.4)]),
            _batch("south-site", "adsb", [_obs("a1b2c3", now, -28.0, lat=33.41)]),
            # Loud, early, and 100 km from where two others heard it.
            _batch(
                "liar-site", "adsb", [_obs("a1b2c3", now + timedelta(seconds=59), 50.0, lat=34.3)]
            ),
            # Loud and early, at a plausible place.
            _batch(
                "liar-site", "adsb", [_obs("cccccc", now + timedelta(seconds=59), 50.0, lat=33.4)]
            ),
            guard=guard,
        )
    )
    assert tallies[-2].doubtful == 1
    track = _rows(migrated_engine, "SELECT station_id, lat FROM rf_track WHERE thing_id = 'a1b2c3'")
    assert track == [("north-site", 33.4)]
    latest = _rows(
        migrated_engine, "SELECT station_id, lat FROM rf_latest WHERE thing_id = 'a1b2c3'"
    )
    assert latest[0].station_id != "liar-site"
    # A clock a minute ahead holds nothing: the shared time is when we got it.
    early = _rows(migrated_engine, "SELECT t, received_at FROM rf_latest WHERE thing_id = 'cccccc'")
    assert early[0][0] <= early[0][1]


def _mod(station: str, mod: str, points: list[dict[str, object]]) -> Custom:
    return Custom.model_validate(
        {
            "v": 1,
            "station": station,
            "kind": "custom",
            "mod": mod,
            "sent": datetime.now(UTC),
            "points": points,
        }
    )


def test_mods_are_stored_shown_as_unverified_and_hidden_on_request(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    from sonoran.rf.operator import hide_mod
    from sonoran.rf.purge import purge_mod

    now = datetime.now(UTC)
    asyncio.run(
        _write(
            timescale_url,
            _beat("west-site", None, [], 0),
            _beat("bad-site", None, [], 0),
            _mod(
                "west-site",
                "lightning",
                [
                    {"id": "s1", "t": now, "heard_here": True, "meta": {"km": 12, "x": "a\u202eb"}},
                    {"id": "s2", "t": now, "lat": 33.0, "lon": -112.0},
                    {"id": "s3", "t": now},
                ],
            ),
            _mod("west-site", "noise", [{"id": "n1", "t": now, "heard_here": True}]),
            _mod("bad-site", "fake", [{"id": "f1", "t": now, "heard_here": True}]),
            guard=Guard(),
        )
    )
    _trust(migrated_engine, "bad-site", "quarantined")
    with _client(timescale_url) as client:
        before = client.get("/api/rf/custom").json()
    by_id = {row["id"]: row for row in before}
    assert set(by_id) == {"s1", "s2", "s3", "n1"}, "a quarantined station's mods are not shown"
    assert (by_id["s1"]["lat"], by_id["s1"]["precision_m"]) == (33.4, 1000)
    assert by_id["s1"]["meta"] == {"km": 12, "x": "ab"}
    assert by_id["s2"]["placement"] == "reported" and by_id["s3"]["lat"] is None
    assert by_id["s1"]["mod"] == "lightning" and by_id["s1"]["station"] == "west-site"

    with migrated_engine.begin() as conn:
        hide_mod(conn, "west-site", "noise", True, "too busy", "test")
    with _client(timescale_url) as client:
        hidden = {row["id"] for row in client.get("/api/rf/custom").json()}
    assert hidden == {"s1", "s2", "s3"}

    with migrated_engine.begin() as conn:
        report = purge_mod(conn, "west-site", "lightning")
    assert report.counts == {"rf_custom": 3}
    left = _rows(migrated_engine, "SELECT station_id, mod FROM rf_custom ORDER BY 1, 2")
    assert left == [("bad-site", "fake"), ("west-site", "noise")]
