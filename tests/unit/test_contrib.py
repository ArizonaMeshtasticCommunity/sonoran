"""Contributors: the contract and the choice of contributor (#178, #179, #181).

Each test names the claim it checks. The claims are from the issues
(Tyler) and the sources in docs/design/contributors.md.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from sonoran.contrib.dispatch import (
    JOB_WAIT,
    TARGET_ROLES,
    Candidate,
    Contributor,
    JobFacts,
    choose,
    interval_for_role,
    is_due,
    next_job,
    refuse_result,
)
from sonoran.contrib.schema import (
    MAX_HEARD,
    TOPIC_ROOT,
    Job,
    Result,
    Status,
    TopicError,
    job_topic,
    json_schema,
    node_num,
    parse_topic,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
JOB = "0123456789abcdef0123456789abcdef"
A = Contributor("phoenix", "pi5")
B = Contributor("mesa", "pi")
C = Contributor("tempe", "box")


def _ok_result(**changes: object) -> dict[str, object]:
    body: dict[str, object] = {
        "v": 1,
        "job": JOB,
        "location": "phoenix",
        "source": "pi5",
        "kind": "local_stats",
        "target": "!1234abcd",
        "outcome": "ok",
        "sent": NOW.isoformat(),
        "received": NOW.isoformat(),
        "local_stats": {"noise_floor": -105, "channel_utilization": 12.5},
    }
    body.update(changes)
    return body


# --- Topics (design 3) -------------------------------------------------


def test_topics_live_under_their_own_root() -> None:
    """Contributor traffic has its own tree, apart from msh/ and rf/v1/."""
    assert TOPIC_ROOT == "sonoran/v1/contributors"
    assert job_topic("outbox", A, JOB) == f"sonoran/v1/contributors/phoenix/pi5/outbox/{JOB}"


def test_parse_topic_splits_each_box() -> None:
    inbox = parse_topic(f"sonoran/v1/contributors/phoenix/pi5/inbox/{JOB}")
    assert (inbox.contributor, inbox.box, inbox.job) == (A, "inbox", JOB)
    status = parse_topic("sonoran/v1/contributors/phoenix/pi5/status")
    assert (status.contributor, status.box, status.job) == (A, "status", None)


@pytest.mark.parametrize(
    "topic",
    [
        f"rf/v1/phoenix/pi5/inbox/{JOB}",
        f"msh/US/AZ/phoenix/pi5/inbox/{JOB}",
        "sonoran/v1/contributors/phoenix/pi5/inbox/not-a-job",
        f"sonoran/v1/contributors/phoenix/pi5/status/{JOB}",
        "sonoran/v1/contributors/phoenix/pi5/inbox",
        f"sonoran/v1/contributors/Phoenix/pi5/inbox/{JOB}",
        f"sonoran/v1/contributors/phoenix/pi5/elsewhere/{JOB}",
    ],
)
def test_parse_topic_refuses_anything_else(topic: str) -> None:
    with pytest.raises(TopicError):
        parse_topic(topic)


def test_node_id_is_the_meshtastic_form() -> None:
    assert node_num("!1234abcd") == 0x1234ABCD
    with pytest.raises(ValueError):
        node_num("1234abcd")


# --- Messages (design 4) -----------------------------------------------


def test_ok_result_carries_the_measured_noise_floor() -> None:
    """noise_floor is LocalStats field 15, an int32 in dBm (telemetry.proto)."""
    result = Result.model_validate(_ok_result())
    assert result.local_stats is not None
    assert result.local_stats.noise_floor == -105


def test_ok_result_without_local_stats_is_invalid() -> None:
    with pytest.raises(ValidationError):
        Result.model_validate(_ok_result(local_stats=None))


def test_ok_result_without_received_is_invalid() -> None:
    with pytest.raises(ValidationError):
        Result.model_validate(_ok_result(received=None))


def test_no_reply_needs_no_local_stats() -> None:
    result = Result.model_validate(_ok_result(outcome="no_reply", local_stats=None, received=None))
    assert result.outcome == "no_reply"


def test_unknown_fields_are_ignored() -> None:
    """A newer contributor may send more; an older Sonoran still reads it."""
    Result.model_validate(_ok_result(something_new=1))


def test_only_known_job_kinds() -> None:
    with pytest.raises(ValidationError):
        Job.model_validate(
            {
                "v": 1,
                "job": JOB,
                "kind": "admin",
                "target": "!1234abcd",
                "issued": NOW.isoformat(),
                "expires": (NOW + JOB_WAIT).isoformat(),
            }
        )


def test_status_heard_list_is_capped_at_the_largest_node_db() -> None:
    """250 = MAX_NUM_NODES on an ESP32-S3 with 16 MB flash (mesh-pb-constants.h)."""
    assert MAX_HEARD == 250
    heard = [
        {"node": f"!{i:08x}", "hops": 1, "last_heard": NOW.isoformat()}
        for i in range(MAX_HEARD + 1)
    ]
    with pytest.raises(ValidationError):
        Status.model_validate(
            {
                "v": 1,
                "location": "phoenix",
                "source": "pi5",
                "sent": NOW.isoformat(),
                "heard": heard,
            }
        )


def test_json_schema_round_trips() -> None:
    schema = json_schema()
    assert json.loads(json.dumps(schema))["title"].startswith("sonoran-contributor")


# --- Targets and intervals (design 5.1) --------------------------------


def test_targets_are_the_roles_in_178() -> None:
    assert TARGET_ROLES == frozenset({"ROUTER", "ROUTER_LATE", "CLIENT_BASE"})


@pytest.mark.parametrize(
    ("role", "hours"),
    [("ROUTER", 12), ("ROUTER_LATE", 12), ("CLIENT_BASE", 1)],
)
def test_interval_is_the_firmware_telemetry_default(role: str, hours: int) -> None:
    """default_telemetry_broadcast_interval_secs, IF_ROUTER(ONE_DAY / 2, 60 * 60)."""
    assert interval_for_role(role) == timedelta(hours=hours)


def test_a_target_with_a_fresh_reading_is_not_due() -> None:
    interval = timedelta(hours=1)
    assert not is_due(NOW - timedelta(minutes=59), None, NOW, interval)
    assert is_due(NOW - timedelta(minutes=61), None, NOW, interval)


def test_a_target_never_read_is_due() -> None:
    assert is_due(None, None, NOW, timedelta(hours=1))


def test_a_round_that_failed_waits_for_the_next_interval() -> None:
    """A round ends when every candidate failed; it is not retried at once."""
    interval = timedelta(hours=12)
    assert not is_due(None, NOW - timedelta(hours=2), NOW, interval)
    assert is_due(None, NOW - timedelta(hours=13), NOW, interval)


# --- Choice of contributor (#181) --------------------------------------


def test_fewest_hops_wins() -> None:
    """#181: the shortest number of hops would be the best candidate."""
    candidates = [
        Candidate(A, hops=3, last_heard=NOW - timedelta(minutes=1)),
        Candidate(B, hops=1, last_heard=NOW - timedelta(minutes=50)),
    ]
    assert choose(candidates, NOW, timedelta(hours=1), failed=set(), busy=set()) == B


def test_the_most_recently_heard_breaks_a_tie() -> None:
    candidates = [
        Candidate(A, hops=2, last_heard=NOW - timedelta(minutes=30)),
        Candidate(B, hops=2, last_heard=NOW - timedelta(minutes=5)),
    ]
    assert choose(candidates, NOW, timedelta(hours=1), failed=set(), busy=set()) == B


def test_unknown_hops_come_last() -> None:
    candidates = [
        Candidate(A, hops=None, last_heard=NOW),
        Candidate(B, hops=6, last_heard=NOW - timedelta(minutes=30)),
    ]
    assert choose(candidates, NOW, timedelta(hours=1), failed=set(), busy=set()) == B


def test_only_contributors_that_heard_it_within_the_interval() -> None:
    """#181: contributors that heard the node within an interval."""
    candidates = [Candidate(A, hops=0, last_heard=NOW - timedelta(hours=2))]
    assert choose(candidates, NOW, timedelta(hours=1), failed=set(), busy=set()) is None


def test_a_failed_contributor_is_skipped_so_the_job_moves_on() -> None:
    """#181: reassign if needed."""
    candidates = [
        Candidate(A, hops=1, last_heard=NOW),
        Candidate(C, hops=2, last_heard=NOW),
    ]
    assert choose(candidates, NOW, timedelta(hours=1), failed={A}, busy=set()) == C


def test_a_busy_contributor_gets_no_second_job() -> None:
    candidates = [
        Candidate(A, hops=1, last_heard=NOW),
        Candidate(C, hops=2, last_heard=NOW),
    ]
    assert choose(candidates, NOW, timedelta(hours=1), failed=set(), busy={A}) == C


def test_no_candidate_no_job() -> None:
    assert choose([], NOW, timedelta(hours=1), failed=set(), busy=set()) is None


def test_job_wait_is_the_meshtastic_library_timeout() -> None:
    """MeshInterface(timeout=300), meshtastic/mesh_interface.py at 2.7.11."""
    assert JOB_WAIT == timedelta(seconds=300)


# --- Accepting a result (design 5.3; Logan on #179: security) ----------


def _facts(**changes: object) -> JobFacts:
    facts = {
        "job": JOB,
        "contributor": A,
        "kind": "local_stats",
        "target": 0x1234ABCD,
        "has_result": False,
    }
    facts.update(changes)
    return JobFacts(**facts)  # type: ignore[arg-type]


def test_a_matching_result_is_accepted() -> None:
    result = Result.model_validate(_ok_result())
    assert refuse_result(_facts(), A, result) is None


def test_no_such_job_is_refused() -> None:
    result = Result.model_validate(_ok_result())
    assert refuse_result(None, A, result) is not None


def test_another_contributors_job_is_refused() -> None:
    """A contributor cannot answer a job that was given to someone else."""
    result = Result.model_validate(_ok_result(location="mesa", source="pi"))
    assert refuse_result(_facts(), B, result) is not None


def test_a_body_that_names_another_contributor_is_refused() -> None:
    result = Result.model_validate(_ok_result(location="mesa", source="pi"))
    assert refuse_result(_facts(), A, result) is not None


def test_a_reading_for_another_node_is_refused() -> None:
    """A contributor cannot write a reading for a node it was not asked about."""
    result = Result.model_validate(_ok_result(target="!deadbeef"))
    assert refuse_result(_facts(), A, result) is not None


def test_a_second_result_for_one_job_is_refused() -> None:
    result = Result.model_validate(_ok_result())
    assert refuse_result(_facts(has_result=True), A, result) is not None


def test_a_result_with_another_job_id_in_its_body_is_refused() -> None:
    result = Result.model_validate(_ok_result(job="f" * 32))
    assert refuse_result(_facts(), A, result) is not None


def test_the_published_json_schema_matches_the_code() -> None:
    """The contributor repository copies the file. It must never drift."""
    from pathlib import Path

    published = json.loads(Path("docs/contributor-message-v1.schema.json").read_text())
    assert published == json.loads(json.dumps(json_schema()))


# --- A round: assign, reassign, end (#181) -----------------------------

HOUR = timedelta(hours=1)


def _heard(*items: tuple[Contributor, int]) -> list[Candidate]:
    return [Candidate(who, hops=hops, last_heard=NOW) for who, hops in items]


def test_a_due_target_starts_a_round_with_the_best_candidate() -> None:
    assert next_job(None, None, [], _heard((A, 2), (B, 1)), NOW, HOUR, busy=set()) == (B, NOW)


def test_an_open_job_holds_the_round() -> None:
    started = NOW - timedelta(minutes=2)
    assert next_job(None, started, [(B, None)], _heard((A, 2), (B, 1)), NOW, HOUR, set()) is None


def test_a_failed_job_moves_to_the_next_candidate_in_the_same_round() -> None:
    """#181: if the job doesn't get picked up within an interval, reassign it."""
    started = NOW - timedelta(minutes=6)
    candidates = _heard((A, 2), (B, 1))
    assert next_job(None, started, [(B, "expired")], candidates, NOW, HOUR, set()) == (A, started)


def test_a_round_ends_when_every_candidate_failed() -> None:
    started = NOW - timedelta(minutes=12)
    jobs = [(B, "no_reply"), (A, "expired")]
    assert next_job(None, started, jobs, _heard((A, 2), (B, 1)), NOW, HOUR, set()) is None


def test_a_round_with_a_reading_is_done() -> None:
    started = NOW - timedelta(minutes=12)
    reading = NOW - timedelta(minutes=10)
    assert next_job(reading, started, [(B, "ok")], _heard((A, 2), (B, 1)), NOW, HOUR, set()) is None


def test_after_the_interval_a_new_round_starts_and_forgets_old_failures() -> None:
    started = NOW - timedelta(hours=2)
    jobs = [(B, "no_reply"), (A, "expired")]
    assert next_job(None, started, jobs, _heard((A, 2), (B, 1)), NOW, HOUR, set()) == (B, NOW)
