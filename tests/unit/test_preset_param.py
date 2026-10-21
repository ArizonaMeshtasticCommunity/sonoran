"""The `preset=` filter reads the tag ingest wrote, with a fallback (#313).

These compile what each list endpoint asks the database and read the
SQL. `tests/integration/test_ingest_presets.py` runs the same requests
against rows that ingest really tagged.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.api.dependencies import get_session
from sonoran.api.preset_scope import require_preset
from sonoran.api.routes.chat import PRESET_NAMES
from sonoran.config import Settings
from sonoran.radio.presets import PRESETS
from tests.unit.job_outputs import JobOutputs
from tests.unit.test_preset_param_legacy import RecordingSession, recorded_sql


@pytest.fixture(autouse=True)
def _outputs(job_outputs: JobOutputs) -> None:
    """The gaps reads come from memory (#351), so only this page's SQL is recorded."""


LIST_PAGES = [
    "/api/chat?preset=LongFast",
    "/api/chat?preset=LongFast&channel=azmsh&metrics=true",
    "/api/chat/overview?hours=168&preset=LongFast",
    "/api/packets?limit=150&summary=true&preset=LongFast",
    "/api/stats/portnums?hours=24&preset=LongFast",
    "/api/nodes?limit=100&active_hours=24&preset=LongFast",
    "/api/nodes/facets?active_hours=24&preset=LongFast",
]


def _filtering(statements: list[str]) -> list[str]:
    return [sql for sql in statements if "preset" in sql]


@pytest.mark.parametrize("path", LIST_PAGES)
def test_every_list_page_reads_the_tag_and_falls_back_to_the_channel(
    path: str, tmp_path: Any
) -> None:
    statements = recorded_sql(path, tmp_path)
    tagged = _filtering(statements)
    assert tagged, f"{path} never filtered by preset"
    for sql in tagged:
        assert "coalesce(" in sql, f"{path} has no fallback for untagged rows:\n{sql}"
        assert "'LongFast'" in sql
        # Never a list of gateways: the read is one equality (#313).
        assert " IN (" not in sql.split("WHERE", 1)[-1] or "node_num IN" in sql


@pytest.mark.parametrize(
    ("path", "tag", "channel"),
    [
        ("/api/packets?preset=LongFast", "packet.modem_preset", "packet.channel"),
        ("/api/stats/portnums?preset=LongFast", "packet.modem_preset", "packet.channel"),
        ("/api/nodes?preset=LongFast", "node.last_preset", "node.last_channel"),
    ],
)
def test_the_fallback_names_the_right_columns(
    path: str, tag: str, channel: str, tmp_path: Any
) -> None:
    sql = _filtering(recorded_sql(path, tmp_path))[0]
    assert f"coalesce({tag}, {channel}) = %(" in sql


@pytest.mark.parametrize(
    "path", ["/api/chat?preset=LongFast", "/api/chat/overview?hours=24&preset=LongFast"]
)
def test_a_message_reads_its_one_packet_by_the_whole_unique_key(path: str, tmp_path: Any) -> None:
    """A correlated read, never a join: a join may hash all of `packet`."""
    statements = _filtering(recorded_sql(path, tmp_path))
    assert statements
    for sql in statements:
        assert "JOIN packet" not in sql
        assert "coalesce((SELECT packet.modem_preset" in sql
        # An untagged message falls back to its channel when the channel
        # names a preset, and to the default preset when it does not.
        assert "CASE WHEN (text_message.channel = ANY (ARRAY[" in sql
        assert "THEN text_message.channel ELSE %(" in sql
        for pair in (
            "packet.from_node_num = text_message.from_node_num",
            "packet.packet_id = text_message.packet_id",
            "packet.first_seen_at = text_message.seen_at",
        ):
            assert pair in sql


def test_the_overview_bounds_each_probe_by_its_window(tmp_path: Any) -> None:
    for sql in _filtering(recorded_sql("/api/chat/overview?hours=24&preset=LongFast", tmp_path)):
        assert "packet.first_seen_at >= %(" in sql


def test_preset_and_channel_apply_together(tmp_path: Any) -> None:
    sql = _filtering(recorded_sql("/api/packets?preset=LongFast&channel=azmsh", tmp_path))[0]
    assert "'azmsh'" in sql and "'LongFast'" in sql


def test_a_preset_is_named_canonically() -> None:
    assert require_preset("longfast") == "LongFast"
    assert require_preset("LONG_FAST") == "LongFast"
    assert require_preset(None) is None
    assert require_preset("") is None


@pytest.mark.parametrize(
    "path",
    [
        "/api/chat?preset=azmsh",
        "/api/chat/overview?preset=Weather",
        "/api/packets?preset=nope",
        "/api/stats/portnums?preset=nope",
        "/api/nodes?preset=nope",
        "/api/nodes/facets?preset=nope",
    ],
)
def test_a_name_that_is_not_a_preset_is_refused(path: str, tmp_path: Any) -> None:
    app = create_app(Settings(_env_file=None, coverage_cache_dir=str(tmp_path)))
    session = RecordingSession()

    async def _session() -> Any:
        yield session

    app.dependency_overrides[get_session] = _session
    response = TestClient(app).get(path)
    assert response.status_code == 422
    assert not session.statements, "a refused name must not reach the database"
    assert "modem preset" in response.text


def test_the_portnum_cache_keeps_presets_apart(tmp_path: Any) -> None:
    first = recorded_sql("/api/stats/portnums?hours=6&preset=MediumFast", tmp_path)
    second = recorded_sql("/api/stats/portnums?hours=6&preset=LongFast", tmp_path)
    assert second, "LongFast was answered from the MediumFast cache entry"
    assert "'LongFast'" in "".join(second) and "'MediumFast'" in "".join(first)


def test_an_untagged_topic_channel_message_stays_on_the_default_preset(tmp_path: Any) -> None:
    """Old azmsh and Weather messages must not leave the chat page (#313).

    Before the tag, the chat page drew every topic channel under the
    default preset. A message from before the deploy has no tag, so it
    must read as the default preset, not as its topic channel's name,
    or `'azmsh' = 'MediumFast'` hides all of them.
    """
    statements = _filtering(recorded_sql("/api/chat?preset=MediumFast", tmp_path))
    assert statements
    sql = statements[0]
    assert "ELSE %(" in sql, "an untagged topic channel has no preset to fall back to"
    assert PRESET_NAMES == [preset.name for preset in PRESETS], "a preset is missing"


# --- Several presets in one request (#383) ----------------------------

MANY = "MediumFast,LongFast"


@pytest.mark.parametrize("path", [path.replace("LongFast", MANY) for path in LIST_PAGES])
def test_every_list_page_takes_several_presets(path: str, tmp_path: Any) -> None:
    """Will: select multiple presets. Each list page keeps rows on any of them."""
    tagged = _filtering(recorded_sql(path, tmp_path))
    assert tagged, f"{path} never filtered by preset"
    for sql in tagged:
        assert "coalesce(" in sql, f"{path} has no fallback for untagged rows:\n{sql}"
        assert ") IN (" in sql, f"{path} did not ask for both presets:\n{sql}"
        assert "'MediumFast'" in sql and "'LongFast'" in sql


def test_one_preset_still_runs_one_equality(tmp_path: Any) -> None:
    """A single preset must not change its SQL because lists exist."""
    sql = _filtering(recorded_sql("/api/packets?preset=LongFast", tmp_path))[0]
    assert "coalesce(packet.modem_preset, packet.channel) = %(" in sql
    assert ") IN (" not in sql


def test_a_repeated_preset_is_one_preset(tmp_path: Any) -> None:
    sql = _filtering(recorded_sql("/api/packets?preset=LongFast,longfast", tmp_path))[0]
    assert "coalesce(packet.modem_preset, packet.channel) = %(" in sql


@pytest.mark.parametrize(
    "path",
    [
        "/api/packets?preset=LongFast,azmsh",
        "/api/chat?preset=MediumFast,nope",
        "/api/chat/overview?preset=LongFast,",
        "/api/stats/portnums?preset=,MediumFast",
        "/api/nodes?preset=LongFast,Weather",
        "/api/nodes/facets?preset=MediumFast,,LongFast",
    ],
)
def test_one_bad_name_in_a_list_refuses_the_request(path: str, tmp_path: Any) -> None:
    app = create_app(Settings(_env_file=None, coverage_cache_dir=str(tmp_path)))
    session = RecordingSession()

    async def _session() -> Any:
        yield session

    app.dependency_overrides[get_session] = _session
    response = TestClient(app).get(path)
    assert response.status_code == 422
    assert not session.statements, "a refused list must not reach the database"
    assert "modem preset" in response.text


def test_the_portnum_cache_keeps_one_preset_apart_from_two(tmp_path: Any) -> None:
    one = recorded_sql("/api/stats/portnums?hours=7&preset=MediumFast", tmp_path)
    two = recorded_sql(f"/api/stats/portnums?hours=7&preset={MANY}", tmp_path)
    assert one and two, "two presets were answered from the one-preset cache entry"
    assert ") IN (" in "".join(two)
