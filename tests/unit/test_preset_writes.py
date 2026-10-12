"""The ingest role's preset UPDATEs must never read `packet` first (#313).

An ORM `update()` picks how to sync the session from its WHERE clause.
For a BETWEEN it runs `SELECT packet.id, packet.first_seen_at` before
the UPDATE, and `azmsh_ingest` may not read `packet.id`. On the first
deploy of #313 that refused every repeat of a packet stored before the
restart, and each refused message was lost.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from sonoran.ingest.preset_writes import store_last_preset, store_packet_preset
from sonoran.ingest.presets import PacketPreset

NOW = datetime(2026, 10, 12, 11, 0, tzinfo=UTC)


class _Recording:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any, *args: object, **kwargs: object) -> None:
        self.statements.append(statement)


def _sync_option(statement: Any) -> object:
    return statement.get_execution_options().get("synchronize_session", "auto")


@pytest.mark.parametrize("exact", [True, False])
def test_the_packet_update_never_syncs_the_session(exact: bool) -> None:
    session = _Recording()
    change = PacketPreset("LongFast", NOW, exact=exact, inserted=False)
    asyncio.run(store_packet_preset(session, 1, 2, change, timedelta(minutes=10)))  # type: ignore[arg-type]
    [statement] = session.statements
    assert _sync_option(statement) is False, "the update may SELECT packet.id first"


def test_the_node_update_never_syncs_the_session() -> None:
    session = _Recording()
    asyncio.run(store_last_preset(session, 0x31300001, "LongFast", NOW))  # type: ignore[arg-type]
    [statement] = session.statements
    assert _sync_option(statement) is False
