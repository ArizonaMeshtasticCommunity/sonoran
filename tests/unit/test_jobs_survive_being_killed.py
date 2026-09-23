"""A job the kernel kills must not become a livelock.

On the dev box the coverage job is killed by the OOM killer part-way
through every run -- `docker run` reports exit **137**. Docker's
`unless-stopped` policy restarts the container, `at_start` re-runs
coverage immediately, and the kernel kills it again. Eleven restarts
were recorded in one stretch and coverage never completed once.

The cost was not the wasted work. The box has **one core**, so the
restart storm starved the thing people actually look at: measured on
that box minutes apart, `/api/graph` served in 0.32 s with the jobs
container stopped and 2.06 s with it running.

The fix is to remember that a task was *tried*, across restarts, and
let `at_start` mean "if it is actually due".

**Why the record is written before the run, not after.** A process that
is killed part-way through never reaches an "after". Recording success
would leave the file empty for ever on exactly the deployment that
needs the backoff, and the livelock would continue with a test proving
it was fixed. That is the single load-bearing decision here, so it has
its own case below.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sonoran.config import Settings
from sonoran.jobs.scheduler import (
    Task,
    _read_last_attempt,
    _record_attempt,
    _startup_delay,
)


def _settings(tmp_path: Path) -> Settings:
    return Settings(_env_file=None, coverage_cache_dir=str(tmp_path))


def _task(name: str = "coverage", interval: float = 3600.0, at_start: bool = True) -> Task:
    async def run() -> None:  # pragma: no cover - never called here
        raise AssertionError("this test never runs the task")

    return Task(name=name, run=run, next_delay=lambda: interval, at_start=at_start)


def test_a_fresh_box_still_runs_at_once(tmp_path: Path) -> None:
    """The reason `at_start` exists must survive the fix.

    A new deployment should produce a coverage map without waiting an
    hour for the first timer.
    """
    assert _startup_delay(_task(), _settings(tmp_path)) == 0.0


def test_a_restart_soon_after_an_attempt_waits(tmp_path: Path) -> None:
    """The livelock, closed."""
    settings = _settings(tmp_path)
    _record_attempt(settings, "coverage")
    delay = _startup_delay(_task(interval=3600.0), settings)
    assert delay > 3500.0, f"a restart re-ran the job immediately (delay {delay})"


def test_a_restart_after_the_interval_runs(tmp_path: Path) -> None:
    """Backoff must not become a block.

    A job that is genuinely due has to run, or the fix trades a
    livelock for a dashboard that never updates.
    """
    settings = _settings(tmp_path)
    path = tmp_path / "attempts" / "coverage.txt"
    path.parent.mkdir(parents=True)
    long_ago = datetime.now(UTC).timestamp() - 7200.0
    path.write_text(str(long_ago), encoding="utf-8")
    assert _startup_delay(_task(interval=3600.0), settings) == 0.0


def test_the_attempt_is_recorded_before_the_run_not_after(tmp_path: Path) -> None:
    """The load-bearing decision, asserted directly.

    `_record_attempt` must be callable with no outcome to report, so
    the scheduler can call it *before* `task.run()`. A signature that
    took a result, or an implementation that only wrote on success,
    would be useless to a process that gets SIGKILLed mid-run -- which
    is the only deployment that needs this.
    """
    settings = _settings(tmp_path)
    assert _read_last_attempt(settings, "coverage") is None
    _record_attempt(settings, "coverage")
    assert _read_last_attempt(settings, "coverage") is not None


def test_the_scheduler_records_before_running() -> None:
    """And the call site really is in that order.

    Read from the source because the ordering is the property, and a
    behavioural test would have to kill a process to observe it.
    Comments are stripped first: this repository has produced a false
    pass four times from a grep that matched a comment about the code.
    """
    import inspect

    from sonoran.jobs import scheduler

    source = inspect.getsource(scheduler._run_forever)
    code = "\n".join(
        stripped for line in source.splitlines() if (stripped := line.split("#", 1)[0].rstrip())
    )
    record = code.index("_record_attempt(")
    run = code.index("await task.run()")
    assert record < run, "the attempt is recorded after the run, which a kill would skip"


def test_a_task_that_does_not_start_at_once_is_unaffected(tmp_path: Path) -> None:
    """`at_start=False` keeps its full delay, recorded attempt or not."""
    settings = _settings(tmp_path)
    _record_attempt(settings, "gaps")
    assert _startup_delay(_task("gaps", 1800.0, at_start=False), settings) == 1800.0


@pytest.mark.parametrize("junk", ["", "not a number", "   "])
def test_an_unreadable_record_is_treated_as_no_record(tmp_path: Path, junk: str) -> None:
    """A corrupt file must not stop the jobs process.

    Failing closed here would mean one bad byte in a cache volume stops
    every scheduled job on the deployment.
    """
    settings = _settings(tmp_path)
    path = tmp_path / "attempts" / "coverage.txt"
    path.parent.mkdir(parents=True)
    path.write_text(junk, encoding="utf-8")
    assert _read_last_attempt(settings, "coverage") is None
    assert _startup_delay(_task(), settings) == 0.0


def test_recording_into_an_unwritable_place_does_not_raise(tmp_path: Path) -> None:
    """A read-only cache volume costs the backoff, not the process."""
    blocker = tmp_path / "cache"
    blocker.write_text("I am a file, not a directory", encoding="utf-8")
    settings = Settings(_env_file=None, coverage_cache_dir=str(blocker))
    _record_attempt(settings, "coverage")  # must not raise
    assert _read_last_attempt(settings, "coverage") is None
