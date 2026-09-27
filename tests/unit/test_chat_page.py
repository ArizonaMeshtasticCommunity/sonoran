"""The per channel chat page and the reaction chips.

There is no JavaScript test runner in this project, so these pin the
rules that a later edit could drop without the page looking broken.
"""

from pathlib import Path

import pytest
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


def test_the_channel_page_asks_for_metrics_and_pages_instead_of_capping() -> None:
    """The page asks for delivery facts, and has no ceiling to apologise for.

    Both halves of this changed with §6.1 and both are still real claims.

    `metrics: 'true'` moved into `chatFetch`, which is the one place that
    talks to `/api/chat` now -- asserting it inside `chatChannelPage` would
    fail for a refactor that kept the behaviour, so it is asserted where it
    lives and the caller is checked to use it.

    `CHAT_MAX = 500` is gone deliberately. It existed because "Load older"
    raised a LIMIT and re-asked for the whole list from the newest message
    down, so every press re-fetched what it already had and the page had to
    stop somewhere. Paging backwards with `before` asks only for what is
    missing, so the cap has nothing to protect and the apology under it
    ("This page stops at 500 messages") is gone with it.
    """
    app = _read("app.js")
    fetch = app[app.index("async function chatFetch(") :]
    fetch = fetch[: fetch.index("\n}\n")]
    assert "metrics: 'true'" in fetch, "the chat no longer asks for delivery metrics"
    assert "before" in fetch and "since" in fetch, (
        "the fetch takes no cursor, so it cannot page backwards"
    )

    page = app[app.index("async function chatChannelPage(") :]
    page = page[: page.index("\n}\n")]
    assert "chatFetch(channel" in page, "the channel page does not go through chatFetch"

    assert "CHAT_MAX" not in app.replace("`CHAT_STEP`/`CHAT_MAX`", ""), (
        "the 500-message cap is back; paging with a cursor does not need one"
    )
    assert "This page stops at" not in app, "the page still apologises for a limit it no longer has"


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


def test_numeral_tapbacks_are_auto_acks_only_where_they_cannot_be_people() -> None:
    """The rule changed on 2026-09-26, reported by Will.

    Trivia's 1-4 are people answering the quiz and were being drawn as
    delivery receipts. Measured on the live instance while fixing it: of 40
    recent Trivia messages, 7 carried a numeral tapback, every one of them
    an answer.

    So a mark only counts on MediumFast, LongFast and azmsh, and the label
    dropped its hedge -- on those channels a digit is not ambiguous.

    Two things this test deliberately no longer requires. `#` (via MQTT),
    `0` and the older direct hit (U+1F3AF) are NO LONGER auto-acks: Will
    chose to recognise only the marks operators see on their own radios,
    accepting that an MQTT ack now reads as a reaction somebody chose. That
    is recorded in `docs/design/2026-09-26-ux-overhaul.md` §2.1, and the
    assertions below are written to fail if somebody restores them without
    revisiting it.
    """
    labels = _read("labels.js")
    assert "const AUTO_ACK_MARK = /^(?:[1-7*]" in labels, "the mark set changed"
    assert "u{1F3AF}" not in labels, (
        "the direct-hit mark is back as an auto-ack; see ux-overhaul §2.1 first"
    )
    assert "'#'" not in labels.split("AUTO_ACK_CHANNELS")[0], (
        "the MQTT mark is back as an auto-ack; see ux-overhaul §2.1 first"
    )
    assert "AUTO_ACK_CHANNELS = new Set(['MediumFast', 'LongFast', 'azmsh'])" in labels
    assert "function isAutoAck(emoji, channel)" in labels
    assert "function autoAckMeaning(emoji)" in labels

    app = _read("app.js")
    assert "'Auto-acked'" in app, "the label still hedges"
    assert "'Possibly auto-acked'" not in app
    # The channel has to reach the renderer, or the rule can never fire.
    assert "reactionChips(message.reactions, message.channel)" in app, (
        "the channel is not passed to the chips, so no tapback can be classified"
    )


def test_the_auto_ack_cases_pass_under_node() -> None:
    """The rule itself, run against the emoji the live payload carries.

    Written after reading real messages: `2️⃣ 7️⃣ 🐦‍⬛` on one MediumFast
    message is why acks and reactions have to be split per-emoji rather
    than per-message, and Trivia's numerals are the reported bug.
    """
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    cases = Path(__file__).resolve().parent / "js" / "auto_ack_cases.mjs"
    done = subprocess.run([node, str(cases)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr
