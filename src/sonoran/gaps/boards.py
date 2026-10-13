"""The windows the gaps leaderboards are written for (#294).

The Statistics page offers three quick ranges: 24 h, 7 d and 30 d. Two
of its leaderboards rank nodes from the gaps evidence, and Will chose on
2026-10-08 that they follow the page range (option A).

The gaps job writes one assessment for `GAPS_WINDOW_HOURS`, which is
7 days by default. That assessment is the board for its own window. For
each other window the job writes a small file beside it, with only the
counts the boards rank by. It does not repeat the signals, the siting,
the neighbour and position reads, or the full traceroute read: a
leaderboard needs none of them, and they are most of what one
assessment costs. It reads only the traceroute requests and their
answers, for the reachable board (#293).

**A custom from/to range has no file.** It is a fixed period, and the
job cannot know in advance which periods a reader will ask for. The
boards then show the assessment's own window and say "not the page
range". They never show a near window as if it were the range.

**A window never reaches past packet retention.** The boards read
`packet` and `packet_seen`, which are kept for `RETENTION_DAYS_PACKET`
days. A longer window would count deleted hours as hours in which
nobody heard a node. So the 30 d window is cut to retention, the file
says what it holds, and the page then says "not the page range".

**A long window is rebuilt less often.** Its cost grows with its length
and its answer barely moves in half an hour. Each file is rebuilt once
it is older than 1/`REFRESH_SHARE` of its window: the 24 h file every
run, the 30 d file every 6 hours. See `docs/GAPS.md` 6.1.
"""

from datetime import datetime, timedelta

from sonoran.config import Settings

#: The page's quick ranges, in hours. `STATS_RANGES` in `app.js`.
BOARD_WINDOW_HOURS: tuple[int, ...] = (24, 168, 720)

#: A file is rebuilt once it is older than this share of its window.
#: 120 keeps every board within 1 percent of its window of fresh.
REFRESH_SHARE = 120

#: The counts the direct gateways board ranks by, copied from the
#: evidence of each node. They have the names the assessment rows use,
#: so one ranking function reads either.
#:
#: The awake and heard hours were here for the old reachable board. #293
#: replaced that board with answered traceroutes, which are written under
#: `TRACE_ANSWERS`, and nothing else reads a board file.
EVIDENCE_KEYS: tuple[str, ...] = ("packets", "direct_gateways")

#: The key that holds each traced node's traceroutes and answers (#293).
#: The assessment carries it too. A file without it was written before
#: the measure existed, and is rebuilt at once.
TRACE_ANSWERS = "trace_answers"


def window_hours(settings: Settings, asked: int) -> int:
    """Return the hours a board for `asked` can truly hold.

    At most packet retention: hours past it are deleted, not quiet.
    """
    return min(asked, settings.retention_days_packet * 24)


def extra_windows(settings: Settings) -> list[int]:
    """Return the windows that need their own file, as the page names them.

    A window that the assessment already holds gets no second file.
    That is the 7 d window by default, and also a 30 d window that
    retention has cut down to the assessment's own length.
    """
    return [
        asked
        for asked in BOARD_WINDOW_HOURS
        if window_hours(settings, asked) != settings.gaps_window_hours
    ]


def refresh_after(hours: int) -> timedelta:
    """Return how old a board file may grow before it is rebuilt."""
    return timedelta(hours=hours / REFRESH_SHARE)


def is_due(held: dict[str, object] | None, hours: int, now: datetime) -> bool:
    """Return true when a board file must be written again.

    A file that is missing, unreadable, or written for another window is
    always due. The last case is a retention change: a file that holds
    14 days must not go on answering for 30. So is a file with no
    traceroute counts: it was written before #293, and the reachable
    board would say "not counted yet" for up to six hours.
    """
    if held is None or held.get("window_hours") != hours:
        return True
    if not isinstance(held.get(TRACE_ANSWERS), list):
        return True
    stamp = held.get("generated_at")
    if not isinstance(stamp, str):
        return True
    try:
        written = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    if written.tzinfo is None:
        return True
    return now - written >= refresh_after(hours)
