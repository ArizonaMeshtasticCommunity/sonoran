"""The chat page reads like a chat (§6.1).

Will asked for the reading view to put the newest message at the bottom,
load older messages as you scroll up, pin the header, fill the height, and
take a date/time range instead of three fixed windows — with the count
beside the channel name instead of a sentence under it.

The plan called this the hardest item in the brief, and its risks are the
reason these cases exist. What is asserted here is the SHAPE that makes the
behaviour possible; the behaviour itself is measured by two e2e journeys
against a real browser, because no source assertion can tell you whether a
list jumped under the reader. Measured during development, on a channel
with 240 messages: the anchored row drifted 0 px across a 100-row prepend,
a reader parked mid-history stayed exactly put while a new message arrived
below them, and a reader at the newest end was carried down with it.
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "app.css").read_text(encoding="utf-8")
CSS_BARE = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)


def _rule(selector: str) -> str | None:
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS_BARE)
    return match.group(1) if match else None


def _function(name: str) -> str:
    start = APP.index(f"function {name}(")
    end = APP.index("\nfunction ", start + 10)
    return APP[start:end]


# --- the range replaced the three windows ---------------------------


def test_the_window_selector_is_gone() -> None:
    assert "data-chat-hours" not in HTML, (
        "the three fixed windows are still in the markup; a range replaced them"
    )
    # And nothing reads it any more. A removed control that something still
    # queries is this repository's most repeated bug: five removals have
    # left a live reference behind.
    assert "data-chat-hours" not in APP, (
        "app.js still reads the window selector that no longer exists"
    )


def test_the_range_control_is_there() -> None:
    for marker in ("data-chat-from", "data-chat-to", 'data-chat-quick="24"'):
        assert marker in HTML, f"the range control is missing {marker}"


def test_a_range_is_read_from_the_address_and_only_from_chat() -> None:
    """Every page keeps its settings in the one fragment.

    Reading `from`/`to` without checking the page would apply the map's or
    the planner's query to the chat — which is exactly how the gaps page
    lost its preset when it read another page's `?channel=` (#177).
    """
    source = _function("chatRangeFromAddress")
    assert "#chat" in source, "the range is read without checking the page is the chat"
    assert re.search(r"/\^#chat\(", source), (
        "the page guard is not anchored, so another page's query can be claimed"
    )


def test_a_backwards_range_is_swapped_not_refused() -> None:
    """An empty page with a valid-looking range reads as a silent mesh.

    Refusing would be defensible; swapping is kinder and cannot mislead,
    because the boxes are redrawn from the range that was actually used.
    """
    source = _function("chatRangeFromAddress")
    assert "from > to" in source, "a backwards range is not detected"
    assert "{ from: to, to: from }" in source, "a backwards range is not swapped"


def test_an_open_end_is_not_the_same_as_now() -> None:
    """`to: null` means live keeps filling; an explicit end means history.

    Without the distinction, a reader who asked for "yesterday 6pm to 8pm"
    would have tonight's messages appended to it.
    """
    assert "function chatRangeIsHistory" in APP, "nothing distinguishes a closed range"
    append = _function("chatAppendNew")
    assert "chatRangeIsHistory(range)" in append, (
        "the live updater appends without asking whether the range is closed"
    )


# --- the reading view ------------------------------------------------


def test_the_newest_message_is_at_the_bottom() -> None:
    source = _function("chatDrawRows")
    assert ".reverse()" in source, (
        "the rows are drawn in the order the API returns them, which is newest "
        "first — the reading view has to be the other way round"
    )


def test_older_messages_keep_the_reader_s_place() -> None:
    """The three lines that stop the list jumping.

    Rows added above the viewport push everything down by their own height.
    The height is measured before and after and the offset moved by the
    difference, in the same frame.
    """
    source = _function("chatLoadOlder")
    assert "scrollHeight" in source and "scrollTop" in source, (
        "nothing measures the scroller around the prepend"
    )
    assert re.search(r"scroller\.scrollTop = top \+ \(scroller\.scrollHeight - before\)", source), (
        "the scroll offset is not corrected by the height the new rows added, "
        "so the list will jump away from whatever was being read"
    )


def test_live_only_follows_a_reader_who_is_already_at_the_bottom() -> None:
    source = _function("chatAppendNew")
    assert "wasAtBottom" in source, "nothing checks where the reader was before appending"
    assert "chatAtBottom(scroller)" in source, "the at-bottom test is not used"
    assert re.search(r"if \(wasAtBottom\) scroller\.scrollTop = scroller\.scrollHeight", source), (
        "the view is not carried to the newest message even when the reader was there"
    )


def test_at_the_bottom_has_a_tolerance() -> None:
    """A strict test strands a reader whose trackpad overshot by 3 px."""
    assert "CHAT_AT_BOTTOM" in APP, "there is no at-bottom tolerance"
    match = re.search(r"const CHAT_AT_BOTTOM = (\d+)", APP)
    assert match and int(match.group(1)) > 0, "the tolerance is zero, which is a strict test"


def test_live_does_not_redraw_the_whole_chat() -> None:
    """A full redraw throws away the scroll position and every loaded page.

    The live tick calls `render(currentPage)` for every other page. For the
    chat reading view that would put a reader back at the newest message
    every fifteen seconds and discard the history they had paged in.
    """
    start = APP.index("liveTimer = setInterval(")
    body = APP[start : start + 1400]
    assert "chatAppendNew()" in body, "the live tick redraws the chat instead of updating it"
    assert "currentPage === 'chat'" in body, "the live tick does not special-case the chat"


def test_rows_are_de_duplicated_by_identity() -> None:
    """`before` is exclusive on a timestamp two messages can share.

    So the same row can arrive from two pages, and a list that trusted the
    cursor would show it twice.
    """
    assert "function chatRowKey" in APP, "there is no row identity to de-duplicate on"
    key = _function("chatRowKey")
    assert "packet_id" in key, "the identity ignores the packet id"
    assert "seen_at" in key, "the identity ignores the timestamp"
    for name in ("chatLoadOlder", "chatAppendNew"):
        assert "chatRowKey" in _function(name), f"{name} does not de-duplicate"


# --- the head -------------------------------------------------------


def test_the_count_sits_beside_the_title() -> None:
    assert "data-chat-count" in HTML, "there is no count in the head"
    # Comments stripped first: the comment at the site of the removal quotes
    # the sentence it replaced, which is the repository's practice for
    # keeping the reasoning without showing it to the reader. Checking the
    # raw file would fail on that record of the change itself.
    visible = re.sub(r"<!--.*?-->", "", HTML, flags=re.S)
    # Scoped to the chat section. The Firehose has its own "newest first."
    # subtitle and is genuinely newest-first, so a whole-file search would
    # fail on a page this change never touched.
    start = visible.index('<section class="page" data-page="chat">')
    end = visible.index('<section class="page"', start + 10)
    chat = visible[start:end]
    assert "The newest" not in chat, (
        "the sentence Will asked to remove is still rendered on the chat page"
    )
    assert "newest first" not in chat, (
        "the chat head still describes the order instead of letting the list show it"
    )


def test_the_count_does_not_claim_a_total_it_cannot_know() -> None:
    """A reading view pages backwards.

    Until it reaches the end of the range it does not know how many
    messages the range holds, so "142 messages" over the first 142 of 900
    would be a confident false statement. It says "shown" until the range
    is exhausted.
    """
    source = _function("chatHead")
    assert "chatOldestReached" in source, "the count does not know whether more remain"
    assert "shown" in source, "the count claims a total even while older messages remain"


# --- the layout -----------------------------------------------------


def test_the_head_is_pinned_by_being_outside_the_scroller() -> None:
    """Not `position: sticky`.

    A sticky header needs a containing block taller than itself, which is
    the trap that silently un-stuck the planner sidebar when one stray
    `</div>` moved `<main>` out of `.shell`. A header that is simply not
    inside the scrolling element cannot come unstuck.
    """
    page = _rule('.page.active[data-page="chat"].chat-full')
    assert page, "the chat page has no full-height rule"
    assert "display: flex" in page, "the chat page is not a column"
    assert "flex-direction: column" in page, "the chat page is not a column"
    assert "min-height: 0" in page, (
        "without `min-height: 0` a flex column will not let the scroller shrink "
        "below its content, and the content is the whole conversation"
    )
    scroller = _rule(".chat-scroll")
    assert scroller, "there is no scroller rule"
    assert "overflow-y: auto" in scroller, "the message list does not scroll on its own"
    assert "flex: 1 1 auto" in scroller, "the scroller does not take the leftover height"


def test_the_height_uses_svh_not_vh() -> None:
    """On a phone `vh` is the viewport with the browser chrome hidden.

    A `100vh` column is taller than what can be seen, so the newest message
    sits under the address bar — which is the one message the view exists
    to show.
    """
    page = _rule('.page.active[data-page="chat"].chat-full')
    assert "svh" in page, f"the chat height does not use svh: {page!r}"
    assert "100vh" not in page, f"the chat height uses vh, which overshoots on a phone: {page!r}"


def test_the_page_does_not_scroll_twice() -> None:
    """Two scrollbars, one inside the other, is how this usually goes wrong.

    The column subtracts `.content`'s own padding so it fills the viewport
    without making the document scroll. Measured: `docScrollY` 0 on a
    1400x900 window with 43 messages.
    """
    page = _rule('.page.active[data-page="chat"].chat-full')
    assert "calc(" in page, (
        "the height does not subtract the surrounding padding, so the document "
        "will scroll as well as the message list"
    )


def test_the_table_view_is_not_the_pinned_layout() -> None:
    """The table keeps newest-first and scrolls with the page."""
    source = _function("chatChannelPage")
    assert "page.classList.remove('chat-full')" in source, (
        "the table view keeps the full-height chat layout"
    )
    # Drawn by `chatDrawTable` since #297, so a page of older rows can
    # redraw the table without going through the whole page again.
    assert "chatDrawTable(page)" in source, "the table view no longer draws the rows"
    assert "chatTable(chatRows)" in _function("chatDrawTable"), (
        "the table view no longer draws the rows"
    )
