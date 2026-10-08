"""The modem preset that ingest gives each observation and packet (#313).

These test the memory alone. `tests/integration/test_ingest_presets.py`
runs the same rules through the real pipeline as the ingest role.
"""

from datetime import UTC, datetime, timedelta

from sonoran.ingest.presets import PresetTracker

T0 = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
GW_A = 0xA0000001
GW_B = 0xB0000002
SENDER = 0x5E4D0001


def _tracker(**kwargs: object) -> PresetTracker:
    return PresetTracker(conflict_window=timedelta(minutes=60), **kwargs)  # type: ignore[arg-type]


def _at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


# --- the preset of one observation ---------------------------------------


def test_a_preset_named_topic_is_its_own_preset() -> None:
    tracker = _tracker()
    seen = tracker.observe(GW_A, "LongFast", _at(0))
    assert seen.preset == "LongFast"
    assert seen.uplink == "LongFast"


def test_a_preset_name_in_another_spelling_is_still_that_preset() -> None:
    seen = _tracker().observe(GW_A, "longfast", _at(0))
    assert seen.preset == "LongFast"


def test_a_topic_channel_takes_the_preset_of_its_gateway() -> None:
    tracker = _tracker()
    tracker.observe(GW_A, "MediumFast", _at(0))
    seen = tracker.observe(GW_A, "azmsh", _at(5))
    assert seen.preset == "MediumFast"
    # A topic channel says nothing about the gateway, so nothing is stored.
    assert seen.uplink is None


def test_a_topic_channel_from_an_unknown_gateway_has_no_preset() -> None:
    seen = _tracker().observe(GW_A, "azmsh", _at(0))
    assert seen.preset is None
    assert seen.uplink is None


def test_an_empty_topic_channel_from_an_unknown_gateway_has_no_preset() -> None:
    assert _tracker().observe(GW_A, None, _at(0)).preset is None


def test_one_gateway_does_not_lend_its_preset_to_another() -> None:
    tracker = _tracker()
    tracker.observe(GW_A, "LongFast", _at(0))
    assert tracker.observe(GW_B, "azmsh", _at(1)).preset is None


# --- the state of one gateway --------------------------------------------


def test_two_presets_inside_the_window_make_a_gateway_ambiguous() -> None:
    tracker = _tracker()
    tracker.observe(GW_A, "LongFast", _at(0))
    tracker.observe(GW_A, "MediumFast", _at(10))
    assert tracker.observe(GW_A, "azmsh", _at(20)).preset is None
    # Its own preset-named uploads still carry their own preset.
    assert tracker.observe(GW_A, "LongFast", _at(21)).preset == "LongFast"


def test_a_reconfigured_gateway_switches_once_the_window_passes() -> None:
    tracker = _tracker()
    tracker.observe(GW_A, "LongFast", _at(0))
    tracker.observe(GW_A, "MediumFast", _at(5))
    assert tracker.observe(GW_A, "azmsh", _at(59)).preset is None
    # LongFast was last heard at minute 0, so at minute 61 it is outside
    # the window and the newest preset wins at once.
    assert tracker.observe(GW_A, "azmsh", _at(61)).preset == "MediumFast"


def test_a_gateway_keeps_its_preset_when_it_goes_quiet() -> None:
    tracker = _tracker()
    tracker.observe(GW_A, "LongFast", _at(0))
    assert tracker.observe(GW_A, "azmsh", _at(60 * 24)).preset == "LongFast"


def test_the_same_preset_again_is_never_ambiguous() -> None:
    tracker = _tracker()
    for minute in range(0, 30, 3):
        tracker.observe(GW_A, "MediumFast", _at(minute))
    assert tracker.observe(GW_A, "azmsh", _at(31)).preset == "MediumFast"


def test_a_seeded_gateway_is_known_after_a_restart() -> None:
    tracker = _tracker()
    tracker.seed(GW_A, "LongFast", _at(-600))
    assert tracker.observe(GW_A, "azmsh", _at(0)).preset == "LongFast"


def test_a_seed_with_a_name_that_is_not_a_preset_is_ignored() -> None:
    tracker = _tracker()
    tracker.seed(GW_A, "azmsh", _at(-5))
    assert tracker.observe(GW_A, "azmsh", _at(0)).preset is None


def test_a_seed_older_than_a_live_upload_does_not_win() -> None:
    tracker = _tracker()
    tracker.observe(GW_A, "MediumFast", _at(0))
    tracker.seed(GW_A, "LongFast", _at(-600))
    assert tracker.observe(GW_A, "azmsh", _at(1)).preset == "MediumFast"


# --- the majority vote of one packet -------------------------------------


def test_the_first_vote_of_a_new_packet_is_already_written() -> None:
    tracker = _tracker()
    change = tracker.vote(SENDER, 1, "LongFast", _at(0), is_new=True)
    assert change is not None
    assert change.preset == "LongFast"
    assert change.inserted is True
    assert change.first_seen_at == _at(0)
    assert change.exact is True


def test_a_matching_vote_changes_nothing() -> None:
    tracker = _tracker()
    tracker.vote(SENDER, 1, "LongFast", _at(0), is_new=True)
    assert tracker.vote(SENDER, 1, "LongFast", _at(0.1), is_new=False) is None


def test_the_majority_flips_only_when_it_is_beaten() -> None:
    tracker = _tracker()
    tracker.vote(SENDER, 1, "LongFast", _at(0), is_new=True)
    # One each is a tie, and a tie keeps the value already stored.
    assert tracker.vote(SENDER, 1, "MediumFast", _at(0.1), is_new=False) is None
    change = tracker.vote(SENDER, 1, "MediumFast", _at(0.2), is_new=False)
    assert change is not None
    assert change.preset == "MediumFast"
    assert change.inserted is False
    assert change.first_seen_at == _at(0), "the update finds the row by its own time"
    assert change.exact is True


def test_no_preset_casts_no_vote() -> None:
    tracker = _tracker()
    assert tracker.vote(SENDER, 1, None, _at(0), is_new=True) is None
    change = tracker.vote(SENDER, 1, "LongFast", _at(0.1), is_new=False)
    assert change is not None
    assert change.preset == "LongFast"
    assert change.inserted is False, "the row was inserted with no preset"
    assert tracker.vote(SENDER, 1, None, _at(0.2), is_new=False) is None


def test_two_packets_are_counted_apart() -> None:
    tracker = _tracker()
    tracker.vote(SENDER, 1, "LongFast", _at(0), is_new=True)
    change = tracker.vote(SENDER, 2, "MediumFast", _at(0), is_new=True)
    assert change is not None and change.preset == "MediumFast"
    assert tracker.vote(SENDER, 1, "MediumFast", _at(0.1), is_new=False) is None


def test_a_forgotten_packet_starts_a_new_tally_with_an_inexact_time() -> None:
    tracker = _tracker(tally_ttl=timedelta(minutes=10))
    tracker.vote(SENDER, 1, "LongFast", _at(0), is_new=True)
    # Past the time limit the tally is gone, as after a restart.
    change = tracker.vote(SENDER, 1, "MediumFast", _at(11), is_new=False)
    assert change is not None
    assert change.preset == "MediumFast"
    assert change.exact is False, "nothing here knows when the packet was first stored"
    assert change.first_seen_at == _at(11)


def test_the_tally_holds_no_more_than_its_limit() -> None:
    tracker = _tracker(tally_size=3)
    for packet_id in range(5):
        tracker.vote(SENDER, packet_id, "LongFast", _at(0), is_new=True)
    assert tracker.tally_count() == 3
    # Packet 0 was evicted, so a second vote for it starts again.
    change = tracker.vote(SENDER, 0, "MediumFast", _at(0.1), is_new=False)
    assert change is not None and change.exact is False


def test_a_new_packet_replaces_a_stale_tally_of_the_same_key() -> None:
    tracker = _tracker()
    tracker.vote(SENDER, 1, "LongFast", _at(0), is_new=True)
    tracker.vote(SENDER, 1, "LongFast", _at(0.1), is_new=False)
    change = tracker.vote(SENDER, 1, "MediumFast", _at(1), is_new=True)
    assert change is not None
    assert change.preset == "MediumFast"
    assert change.first_seen_at == _at(1)
