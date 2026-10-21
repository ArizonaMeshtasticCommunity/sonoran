"""A message on a node page links to its packet (#387).

Will, in #387: "When you click on the time since the message was sent
(16m ago) on an individual node info page it currently does a small
popup with an expansion of the date. [...] we should make it when you
click it, it takes you to that individual packet page."

The chat page and the dashboard already do this. `messageItem` in
`app.js` draws the time as a link when the message carries a
`packet_id`, and as a popup button when it does not. The node page uses
the same `messageItem`, but `/api/nodes/{id}/detail` sent each message
without `packet_id` and without `from_node`, so every time on the node
page fell back to the popup. The sender button was empty for the same
reason: it reads `from_name` or `from_node`, and both were missing.

A packet is identified by (`from_node_num`, `packet_id`) (AGENTS.md
9.1). The link needs both halves. The `text_message.id` surrogate key is
not a packet ID, so a test below gives the two different values.

The browser half is the e2e journey "a message time on a node page
opens its packet (#387)" in `tools/dev/e2e.js`. It clicks the time and
checks that the packet page shows that packet.
"""

from datetime import UTC, datetime
from typing import Any

import pytest

from sonoran.api.routes.nodes import _messages
from sonoran.db.models import TextMessage

SENDER = 173125640  # !0a51b008
RECIPIENT = 173121537  # !0a51a001
BROADCAST = 0xFFFFFFFF
SINCE = datetime(2026, 10, 20, tzinfo=UTC)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    """Enough of an `AsyncSession` for `_messages`.

    `_messages` makes one `scalar` call (the count), one `scalars` call
    (the rows) and, through `resolve_names`, one `execute` call (the
    node table).
    """

    def __init__(
        self, rows: list[TextMessage], nodes: list[tuple[int, str | None, str | None]]
    ) -> None:
        self._rows = rows
        self._nodes = nodes

    async def scalar(self, statement: Any) -> int:
        return len(self._rows)

    async def scalars(self, statement: Any) -> _Result:
        return _Result(self._rows)

    async def execute(self, statement: Any) -> _Result:
        return _Result(list(self._nodes))


def _message(*, surrogate: int, packet_id: int | None, to: int = BROADCAST) -> TextMessage:
    return TextMessage(
        id=surrogate,
        packet_id=packet_id,
        from_node_num=SENDER,
        to_node_num=to,
        channel="azmsh",
        body="hello",
        emoji=False,
        seen_at=datetime(2026, 10, 21, 8, 11, tzinfo=UTC),
    )


async def _recent(rows: list[TextMessage]) -> list[dict[str, object]]:
    session = _Session(rows, [(SENDER, "Prescott Hillside", "PRES"), (RECIPIENT, "Tucson", "TUC")])
    answer = await _messages(session, SENDER, SINCE, limit=25)  # type: ignore[arg-type]
    recent = answer["recent"]
    assert isinstance(recent, list)
    return recent


@pytest.mark.asyncio
async def test_a_node_page_message_carries_the_key_of_its_packet() -> None:
    """Both halves of the packet's identity, so the page can link to it."""
    (message,) = await _recent([_message(surrogate=7, packet_id=100017)])
    assert message["packet_id"] == 100017
    assert message["from_node"] == "!0a51b008"


@pytest.mark.asyncio
async def test_the_packet_id_is_the_meshtastic_id_not_the_row_id() -> None:
    """Would be caught: a link built from `text_message.id`.

    The surrogate key is a row number. It names no packet, and a link
    built from it opens "packet not found", or worse, another packet.
    """
    (message,) = await _recent([_message(surrogate=100017, packet_id=950001)])
    assert message["packet_id"] == 950001, "the message sent its row ID as its packet ID"


@pytest.mark.asyncio
async def test_a_message_with_no_packet_says_so_and_invents_none() -> None:
    """An old row with no packet keeps the popup, not a broken link.

    `messageItem` draws the popup when `packet_id` is null. A row written
    before ingest stored the packet ID has none, and nothing may guess one.
    """
    (message,) = await _recent([_message(surrogate=7, packet_id=None)])
    assert message["packet_id"] is None


@pytest.mark.asyncio
async def test_the_sender_has_a_name_to_print() -> None:
    """The sender button on the node page was empty (#387).

    `messageItem` prints `from_name`, or `from_node` when there is no
    name. Neither was sent, so the button had no text and no accessible
    name, and it opened no node.
    """
    (message,) = await _recent([_message(surrogate=7, packet_id=100017, to=RECIPIENT)])
    assert message["from_name"] == "Prescott Hillside"
    # The recipient keeps its own name. A direct message is drawn from it.
    assert message["to_node"] == "!0a51a001"
    assert message["to_name"] == "Tucson"
