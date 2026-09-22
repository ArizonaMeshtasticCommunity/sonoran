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
from sonoran.rf.schema import Batch, Spectrum, Status
from sonoran.rf.store import Rules, Tally, store_batch, store_spectrum, store_status
from tests.integration.conftest import role_url


@pytest.fixture
def clean(migrated_engine):  # type: ignore[no-untyped-def]
    with migrated_engine.begin() as connection:
        connection.execute(text("TRUNCATE rf_station, rf_track, rf_heard, rf_latest, rf_spectrum"))
    yield


def _batch(station: str, kind: str, obs: list[dict[str, object]]) -> Batch:
    return Batch.model_validate(
        {"v": 1, "station": station, "kind": kind, "sent": datetime.now(UTC), "obs": obs}
    )


def _obs(icao: str, when: datetime, rssi: float | None, lat: float = 33.5) -> dict[str, object]:
    return {"id": icao, "t": when, "lat": lat, "lon": -112.0, "alt_m": 3000, "rssi_db": rssi}


async def _write(
    timescale_url: str, *messages: Batch | Status, rules: Rules | None = None
) -> list[Tally]:
    engine = create_async_engine(role_url(timescale_url, "azmsh_ingest"))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    tallies: list[Tally] = []
    try:
        for message in messages:
            async with factory() as session:
                received = datetime.now(UTC)
                if isinstance(message, Status):
                    await store_status(session, message, received)
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


def test_hidden_aircraft_and_later_kinds_are_not_stored(
    timescale_url: str, migrated_engine, clean: None
) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(UTC)
    tallies = asyncio.run(
        _write(
            timescale_url,
            _batch("north-site", "adsb", [_obs("a1b2c3", now, -20.0), _obs("bbbbbb", now, -9.0)]),
            _batch("north-site", "aprs", [{"id": "n0call-9", "t": now, "lat": 33, "lon": -112}]),
            _batch("north-site", "uat", [_obs("cccccc", now, -15.0)]),
            rules=Rules(hidden=frozenset({"bbbbbb"})),
        )
    )
    assert (tallies[0].stored, tallies[0].hidden) == (1, 1)
    assert tallies[1].kind_not_stored == 1
    assert tallies[2].stored == 1
    ids = {r.thing_id for r in _rows(migrated_engine, "SELECT thing_id FROM rf_latest")}
    assert ids == {"a1b2c3", "cccccc"}


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
        "stored": ["adsb", "uat"],
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
