"""sonoran-rf-purge: the parts that need no database."""

from datetime import UTC, datetime, timedelta

from sonoran.rf.ingest import heard_at
from sonoran.rf.purge import main, retained_topics
from sonoran.rf.schema import NO_SOURCE, Status


def _status(sent: datetime) -> Status:
    return Status.model_validate({"v": 1, "station": "tempe-roof", "sent": sent})


def test_a_live_heartbeat_is_heard_when_it_arrives() -> None:
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    assert heard_at(_status(now - timedelta(seconds=2)), now, retained=False) == now


def test_a_retained_heartbeat_is_heard_when_it_was_sent() -> None:
    """After an ingest restart, a station dead for days must not look online."""
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    old = now - timedelta(days=3)
    assert heard_at(_status(old), now, retained=True) == old
    # A clock ahead of ours never makes it newer than now.
    assert heard_at(_status(now + timedelta(hours=1)), now, retained=True) == now


def test_the_retained_topics_to_clear_name_every_source() -> None:
    assert retained_topics("tempe-roof", [NO_SOURCE, "adsb-pi", "sweeper"]) == [
        "rf/v1/tempe-roof/status",
        "rf/v1/tempe-roof/registry",
        "rf/v1/tempe-roof/status/adsb-pi",
        "rf/v1/tempe-roof/status/sweeper",
    ]


def test_a_bad_station_id_or_no_database_is_refused(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    assert main(["Bad Name"]) == 2
    monkeypatch.delenv("DATABASE_URL_MIGRATE", raising=False)
    assert main(["tempe-roof"]) == 2
    assert "migrate service" in capsys.readouterr().err
