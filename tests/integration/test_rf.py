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
from sonoran.rf.schema import Batch, Registry, Spectrum, Status
from sonoran.rf.store import (
    Rules,
    Tally,
    store_batch,
    store_registry,
    store_spectrum,
    store_status,
)
from tests.integration.conftest import role_url


@pytest.fixture
def clean(migrated_engine):  # type: ignore[no-untyped-def]
    with migrated_engine.begin() as connection:
        connection.execute(
            text("TRUNCATE rf_station, rf_source, rf_track, rf_heard, rf_latest, rf_spectrum")
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
    *messages: Batch | Status | Registry | str,
    rules: Rules | None = None,
) -> list[Tally]:
    """Write each message as the ingest role. A bare station id removes
    that station's registry entry, as an empty retained message does."""
    engine = create_async_engine(role_url(timescale_url, "azmsh_ingest"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tallies: list[Tally] = []
    try:
        for message in messages:
            async with factory() as session:
                received = datetime.now(UTC)
                if isinstance(message, Status):
                    await store_status(session, message, received)
                elif isinstance(message, Registry):
                    await store_registry(session, message.station, message, received)
                elif isinstance(message, str):
                    await store_registry(session, message, None, received)
                else:
                    tallies.append(await store_batch(session, message, received, rules or Rules()))
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


def test_two_stations_hearing_one_aircraft_make_one_point_the_loudest(
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
    assert track[0].station_id == "south-site" and track[0].rssi_db == -12.0

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
        "views": ["spectrum"],
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
    assert len(hour["rows"]) == 8
    assert hour["bins"] == 3 and hour["f_start_hz"] == 902_000_000
    assert day["bucket_minutes"] == 6
    assert len(day["rows"]) <= 3
    loud = max(day["rows"], key=lambda row: row["p95"][1])
    assert loud["p95"][1] == -260, "the highest 95th percentile in the bucket is kept"
    assert loud["p50"][1] == -500, "the median of the medians ignores one loud minute"
    by_name = {item["name"]: item for item in channels["channels"]}
    assert by_name["LongFast"]["centre_hz"] == 906_875_000
    assert refused.status_code == 422
    # The station has no heartbeat, so it is not listed; spectrum alone
    # does not invent a station.
    assert all(item["station"] != "west-site" for item in stations)


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
