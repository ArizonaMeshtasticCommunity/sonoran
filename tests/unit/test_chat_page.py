"""The per channel chat page and the reaction chips.

There is no JavaScript test runner in this project, so these pin the
rules that a later edit could drop without the page looking broken.
"""

from fastapi.testclient import TestClient

from sonoran.api.app import STATIC_DIR, create_app
from sonoran.config import Settings


def _read(name: str) -> str:
    return (STATIC_DIR / name).read_text(encoding="utf-8")


def test_a_channel_has_its_own_address() -> None:
    """`#chat/<channel>` is a page that can be linked and shared (#57)."""
    app = _read("app.js")
    assert "if (known === 'chat')" in app
    assert "function chatHref(channel, view)" in app
    assert "encodeURIComponent(channel)" in app
    # The overview links to it rather than expanding in place.
    section = app[app.index("function channelSection(") :]
    section = section[: section.index("\n}\n")]
    assert "chatHref(section.channel)" in section


def test_the_channel_page_asks_for_metrics_and_is_bounded() -> None:
    """The page asks for delivery facts, and stops at the API's own limit."""
    app = _read("app.js")
    page = app[app.index("async function chatChannelPage(") :]
    page = page[: page.index("\n}\n")]
    assert "metrics: 'true'" in page
    assert "const CHAT_MAX = 500;" in app


def test_the_view_switch_is_on_the_chat_page() -> None:
    text = TestClient(create_app(Settings(_env_file=None))).get("/").text
    chat = text[text.index('data-page="chat"') :]
    chat = chat[: chat.index("</section>")]
    assert "data-chat-view" in chat
    assert 'data-chat-view-choice="table"' in chat


def test_a_reaction_hides_its_senders_until_asked() -> None:
    """Inline names took the chat page sideways at 320 px once (#44).

    A chip is an emoji and a count, and the names open under it.
    """
    app = _read("app.js")
    chip = app[app.index("function reactionChip(") :]
    chip = chip[: chip.index("\n}\n")]
    assert "el('details'" in chip
    assert "el('summary'" in chip


def test_numeral_tapbacks_are_labelled_as_possible_auto_acks() -> None:
    """A delivery signal is not an opinion, and a person may send a numeral.

    MeshMonitor's Auto Acknowledge sends a keycap: `*` direct, `1` to `7`
    hops, `#` via MQTT. They are drawn apart, each read in words, and the
    label says "possibly".
    """
    app = _read("app.js")
    assert "const AUTO_ACK = /^(?:[0-7*#]" in app
    assert "u{1F3AF}" in app, "older builds acknowledged a direct message with a direct hit"
    assert "'Possibly auto-acked'" in app
    assert "function autoAckMeaning(emoji)" in app
