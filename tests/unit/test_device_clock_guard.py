"""A device's own clock does not get to say when we heard it.

AGENTS.md 9.4. Position and telemetry carry a timestamp the device
wrote, and it was stored unconditionally as the `time` column of five
hypertables.

Measured on production before this landed: **79 `device_metrics` rows
dated in the future across 13 nodes, the furthest at 2036-02-07**. One
node had 31 of its 55 rows in a 24 hour window ahead of now.

That damage does not age out. Retention deletes by `time`, so a row
claiming 2036 is never old enough to expire, and every "last N hours"
window includes it for the next ten years. The query side was taught
to bound its windows, but that is whack-a-mole -- every new query has
to remember, and the row is still wrong.

Only the impossible direction is clamped. See `clocks.device_time`.
"""

from datetime import UTC, datetime, timedelta

from sonoran.ingest.handlers.clocks import device_time

RECEIVED = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
SLACK = timedelta(seconds=300)


def _guard(claimed: datetime) -> datetime:
    return device_time(claimed, RECEIVED, SLACK, kind="telemetry", node_num=1)


def test_a_reading_from_the_future_is_refused() -> None:
    """The case that did the damage: 2036-02-07, stored as fact."""
    claimed = datetime(2036, 2, 7, 7, 44, 57, tzinfo=UTC)
    assert _guard(claimed) == RECEIVED, (
        "a device claiming a decade in the future still sets its own row's "
        "time, which retention can never expire"
    )


def test_a_reading_from_the_past_is_kept() -> None:
    """Ordinary, and must not be thrown away.

    The mesh stores and forwards, and a gateway can upload a backlog.
    One measured upload lag on this deployment was 19.5 days. Clamping
    that would discard real readings to tidy a column.
    """
    claimed = RECEIVED - timedelta(days=19)
    assert _guard(claimed) == claimed


def test_our_own_clock_being_slightly_behind_is_not_the_node_s_fault() -> None:
    """Inside the slack, the device's stamp is taken as given."""
    assert _guard(RECEIVED + timedelta(seconds=120)) == RECEIVED + timedelta(seconds=120)


def test_the_boundary_is_inclusive() -> None:
    """Exactly at the slack is still accepted; one second past is not."""
    assert _guard(RECEIVED + SLACK) == RECEIVED + SLACK
    assert _guard(RECEIVED + SLACK + timedelta(seconds=1)) == RECEIVED


def test_a_clock_that_was_never_set_is_refused() -> None:
    """#408: a node with no time source stamps its seconds since boot.

    Telemetry uses `getTime()`, which is seconds since boot plus an
    offset that stays 0 until a time source sets it (firmware
    v2.7.26.54e0d8d, `src/gps/RTC.cpp:440-447`;
    `DeviceTelemetry.cpp:98`). The live case was Dome Light, `!a81f4ac3`:
    `time` 1970-01-15 06:30:27 with `uptime_seconds` 1233027, the same
    number. Stored as given, the row sits in a 1970 chunk and retention
    deletes it, so the node page shows no telemetry at all.
    """
    claimed = datetime.fromtimestamp(1_233_027, UTC)
    assert _guard(claimed) == RECEIVED, (
        "a boot-relative stamp from 1970 is stored as the reading's time, "
        "and retention deletes the row at once"
    )


def test_the_floor_is_the_first_firmware_commit() -> None:
    """No Meshtastic device existed before the firmware's first commit.

    meshtastic/firmware cdb7153071, 2020-02-01T16:30:53Z. A stamp from
    that moment on is a real clock (old, maybe, but see the backlog test
    above), and one second before it is not.
    """
    floor = datetime(2020, 2, 1, 16, 30, 53, tzinfo=UTC)
    assert _guard(floor) == floor
    assert _guard(floor - timedelta(seconds=1)) == RECEIVED


def test_both_device_stamped_families_use_the_guard() -> None:
    """Position and telemetry are the two that carry a device clock.

    Named by source rather than by behaviour because the handlers need
    a protobuf message to exercise; the guard's own behaviour is
    covered above.
    """
    from pathlib import Path

    handlers = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "ingest" / "handlers"
    for name in ("position.py", "telemetry.py"):
        source = (handlers / name).read_text(encoding="utf-8")
        assert "device_time(" in source, f"{name} stores a device clock unguarded"
        assert "datetime.fromtimestamp" in source
        start = source.index("datetime.fromtimestamp")
        assert "device_time(" in source[max(0, start - 300) : start + 300], (
            f"{name} converts a device timestamp somewhere the guard does not cover"
        )
