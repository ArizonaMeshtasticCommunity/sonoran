"""The weekly check-in reads one channel, and the streak reads the same one.

#262. Will: "For the whole weekly check-in it should only be for the
MediumFast channel." The scope is applied on the server, in both reads
`api/chat/tagged` makes:

- the message list the page draws, and
- the 52-week aggregate the streaks are counted from.

The second one is the reason it cannot be a browser filter. The browser
never sees the rows a streak is counted from, so a page that hid the
other channels' messages would still print runs that counted them: a
node that posted `#meshnet` on LongFast one week and MediumFast the next
would read "2 weeks" beside a list that showed it once.

These tests read the SQL each read actually sends, compiled for
PostgreSQL, rather than the helper that builds it -- a helper can be
correct and not called.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from sqlalchemy.dialects import postgresql

from sonoran.api.routes.chat import _message_streak, tagged

WEEK = timedelta(days=7)
MONDAY = datetime(2026, 9, 21, tzinfo=UTC)
DEEP_FLOOR = MONDAY - 200 * WEEK


class _Empty:
    """A result with no rows, in each shape the endpoint reads."""

    def all(self) -> list[Any]:
        return []


class _RecordingSession:
    """Records every statement the endpoint sends, and answers with nothing."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def _record(self, statement: Any) -> _Empty:
        compiled = statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
        self.sent.append(str(compiled))
        return _Empty()

    async def scalars(self, statement: Any) -> _Empty:
        return self._record(statement)

    async def execute(self, statement: Any) -> _Empty:
        return self._record(statement)


def _request(preset: str = "MediumFast") -> Any:
    settings = SimpleNamespace(default_preset=preset, store_text_messages=True)
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=settings)))


async def _sent(preset: str = "MediumFast") -> tuple[list[str], dict[str, object]]:
    session = _RecordingSession()
    body = await tagged(_request(preset), tag="meshnet", weeks=8, limit=500, session=session)  # type: ignore[arg-type]
    return session.sent, body


async def test_both_reads_are_scoped_to_the_net_channel() -> None:
    """The message list AND the streak aggregate each carry the channel."""
    sent, _ = await _sent()
    # Positive control: both reads were made, so the assertion below is
    # about two statements and cannot pass by there being none.
    assert len(sent) == 2, sent
    assert any("GROUP BY" in sql for sql in sent), "the streak aggregate was not sent"
    assert any("LIMIT" in sql for sql in sent), "the message list was not sent"
    for sql in sent:
        assert "text_message.channel = 'MediumFast'" in sql, (
            f"a check-in read is not scoped to MediumFast, so the streak can count "
            f"other channels:\n{sql}"
        )


async def test_the_channel_is_the_deployments_preset_and_is_reported() -> None:
    """A setting, not a literal, and the page is told which one was read.

    Another mesh running its net on LongFast should not have to patch
    the route; and the page description names the channel from this
    answer rather than from its own markup.
    """
    sent, body = await _sent("LongFast")
    assert body["channel"] == "LongFast"
    for sql in sent:
        assert "text_message.channel = 'LongFast'" in sql
        assert "'MediumFast'" not in sql


async def test_the_scope_is_exact_not_case_folded() -> None:
    """`trivia` and `Trivia` are two channels with two sets of people on them.

    `classify` folds case for grouping. The check-in scope must not: the
    channel name is what the MQTT topic carried.
    """
    sent, _ = await _sent()
    for sql in sent:
        assert "lower(text_message.channel)" not in sql
        assert "text_message.channel ILIKE" not in sql


# --- the streak on each message ---------------------------------------


def weeks(*offsets: int) -> frozenset[datetime]:
    return frozenset(MONDAY + offset * WEEK for offset in offsets)


def test_a_message_carries_the_run_as_of_its_own_week() -> None:
    """Not the sender's run today.

    A message from four weeks ago beside today's number would say "12
    weeks" about a week in which the run was 8.
    """
    run = weeks(-4, -3, -2, -1, 0)
    assert _message_streak(run, MONDAY, DEEP_FLOOR)["streak_weeks"] == 5
    assert _message_streak(run, MONDAY - 2 * WEEK, DEEP_FLOOR)["streak_weeks"] == 3


def test_a_message_run_uses_the_same_rules_as_the_roster() -> None:
    """First check-in, restart, and a run that reaches the floor."""
    first = _message_streak(weeks(0), MONDAY, DEEP_FLOOR)
    assert first == {"streak_weeks": 1, "streak_at_least": False, "first_ever": True}
    restart = _message_streak(weeks(-3, 0), MONDAY, DEEP_FLOOR)
    assert restart == {"streak_weeks": 1, "streak_at_least": False, "first_ever": False}
    floor = MONDAY - 2 * WEEK
    bounded = _message_streak(weeks(-2, -1, 0), MONDAY, floor)
    assert bounded["streak_weeks"] == 3
    assert bounded["streak_at_least"] is True, "a run that reaches the floor is a lower bound"


def test_a_message_with_no_run_is_not_a_zero() -> None:
    """Missing is None, which the page words as "Streak not known".

    A zero would be a missing figure drawn as a real one -- the shape of
    five bugs in this repository -- and rule 3 says a check-in's run is
    at least 1, so 0 is never true here.
    """
    for known in (None, frozenset(), weeks(-1)):
        said = _message_streak(known, MONDAY, DEEP_FLOOR)
        assert said["streak_weeks"] is None, said
        assert said["streak_weeks"] != 0
