"""Run each job in its own process, with its own memory limit (#371).

Every job used to run inside the one jobs process, under the
container's one memory limit. When anything went past it, the kernel
killed the container, and every job died with it: 14 times between
2026-09-30 and 2026-10-05, once in each coverage cycle. A long-lived
Python process also keeps its peak memory after a run.

Now the jobs process is a small supervisor, and each run is a child
process (`python -m sonoran.jobs.run_task <name>`):

- **A limit per job.** `JOBS_MEMORY_LIMITS` names each job's ceiling in
  MB. A watchdog adds up the memory (RSS) of the job's whole process
  tree, coverage's engine workers included, once a second. A job that
  passes its ceiling is killed alone, and waits its normal interval
  before the next try: retrying a job that cannot fit at once is the
  livelock of 2026-09-21.
- **Jobs overlap when they fit.** The supervisor knows how much memory
  the container has (its cgroup limit, or `JOBS_MEMORY_BUDGET_MB`) and
  starts a job only when the job fits beside the ones running. A job
  that does not fit waits its turn. One bigger than the whole budget
  runs alone. So overlap is a matter of memory: at `JOBS_MEMORY_LIMIT`
  900m a coverage run (planned at about 720 MB) leaves no room, and the
  other jobs wait for it; a larger limit lets them run beside it.
- **Planned by measurement.** Each run records its peak. A job is
  planned at its last peak plus `PLAN_MARGIN`, never above its ceiling,
  and at its ceiling until it has a recorded peak. So the overlap follows
  what the jobs really use on this deployment, not a guess.
- **The kernel kills a job, never the supervisor.** Children raise
  their OOM score, so if the container ever runs out anyway, the kernel
  takes a job and everything else keeps running.
- **Memory goes back after each run.** A child returns all of it when
  it exits.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from sonoran.config import Settings
from sonoran.logging import get_logger

logger = get_logger(__name__)

#: Each job's ceiling, in MB, unless `JOBS_MEMORY_LIMITS` says otherwise.
#: Coverage peaked at about 627 MB on 2026-10-05 (precision 13, one
#: worker). The others were never measured alone; their ceilings are
#: generous on purpose, and each run's peak is logged and kept.
DEFAULT_LIMITS_MB: dict[str, float] = {
    "coverage": 800.0,
    "calibration": 400.0,
    "gaps": 400.0,
    "read-models": 400.0,
    "rf-rollup": 250.0,
    "snapshot": 250.0,
    # A whole run on the default region with 780 000 joined rows peaked
    # at 493 MB (review of PR 344, synthetic rows). The first real peak
    # is logged; lower this when it is known.
    "activity_heatmap": 800.0,
}

#: A job with no recorded peak and no configured ceiling is planned at this.
UNKNOWN_LIMIT_MB = 400.0

#: A job is planned at its last peak times this.
PLAN_MARGIN = 1.15

#: Memory the container keeps free beside the supervisor itself.
HEADROOM_MB = 50.0

#: How often the watchdog reads a job's memory, after its first seconds.
WATCH_SECONDS = 1.0
#: For a run's first `EARLY_SECONDS`, it reads every `EARLY_WATCH_SECONDS`,
#: so a short job still records a peak.
EARLY_SECONDS = 5.0
EARLY_WATCH_SECONDS = 0.25
#: A finished run lowers the recorded peak by at most this share, so one
#: short run (coverage with nothing to plan, say) cannot make the next
#: plan too small to be safe.
PEAK_DECAY = 0.9

#: The OOM score a child gives itself: the kernel's first choice.
CHILD_OOM_SCORE_ADJ = 1000


class OverLimit(Exception):
    """A job passed its memory ceiling and was killed."""


def parse_limits(text: str) -> dict[str, float]:
    """Read `name=MB,name=MB` into a mapping. Bad entries are logged and skipped."""
    limits: dict[str, float] = {}
    for item in (part.strip() for part in text.split(",")):
        if not item:
            continue
        name, _, value = item.partition("=")
        try:
            limits[name.strip()] = float(value)
        except ValueError:
            logger.warning("ignored a memory limit that is not a number: %r", item)
    return limits


def limits_for(settings: Settings) -> dict[str, float]:
    """Each job's ceiling: the defaults, with `JOBS_MEMORY_LIMITS` over them."""
    return DEFAULT_LIMITS_MB | parse_limits(settings.jobs_memory_limits)


def container_limit_mb() -> float | None:
    """The memory limit of this container, in MB, or None when it has none."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            text = Path(path).read_text(encoding="ascii").strip()
        except OSError:
            continue
        if text == "max":
            return None
        try:
            value = int(text) / 1_048_576
        except ValueError:
            continue
        # cgroup v1 writes a number near 2**63 for "no limit".
        return None if value > 1_000_000_000 else value
    return None


def rss_mb(pid: int) -> float:
    """The resident memory of one process, in MB. 0 when it is gone."""
    return _status_kb(pid, "VmRSS:") / 1024


def _status_kb(pid: int, field_name: str) -> float:
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="ascii").splitlines():
            if line.startswith(field_name):
                return float(line.split()[1])
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


def share_mb(pid: int) -> float:
    """One process's share of memory (PSS), in MB, or its RSS when PSS is unreadable.

    PSS divides each shared page between the processes that map it. A
    tree's RSS counts the Python runtime and its libraries once per
    process: a coverage child and its engine worker read about 50 MB
    more than they hold. Summed PSS is what the container is charged.
    """
    try:
        for line in Path(f"/proc/{pid}/smaps_rollup").read_text(encoding="ascii").splitlines():
            if line.startswith("Pss:"):
                return float(line.split()[1]) / 1024
    except (OSError, ValueError, IndexError):
        pass
    return rss_mb(pid)


def process_tree(root: int) -> list[int]:
    """The process and every process below it."""
    children: dict[int, list[int]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            # The command name is in parentheses and can hold spaces.
            stat = (entry / "stat").read_text(encoding="ascii", errors="replace")
            parent = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(parent, []).append(int(entry.name))
    tree, waiting = [], [root]
    while waiting:
        pid = waiting.pop()
        tree.append(pid)
        waiting.extend(children.get(pid, []))
    return tree


def tree_rss_mb(root: int) -> float:
    """The memory of a process and everything below it, in MB (summed PSS)."""
    return sum(share_mb(pid) for pid in process_tree(root))


def _kill_tree(root: int) -> None:
    for pid in reversed(process_tree(root)):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _peak_file(settings: Settings, name: str) -> Path:
    return Path(settings.coverage_cache_dir) / "attempts" / f"{name}.peak"


def read_peak(settings: Settings, name: str) -> float | None:
    """The peak of the job's last finished run, in MB, across restarts."""
    try:
        return float(_peak_file(settings, name).read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def _record_peak(settings: Settings, name: str, peak: float) -> None:
    """Keep a finished run's peak, falling by at most `PEAK_DECAY` a run."""
    previous = read_peak(settings, name)
    if previous is not None:
        peak = max(peak, previous * PEAK_DECAY)
    path = _peak_file(settings, name)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{peak:.0f}", encoding="ascii")
    except OSError:
        logger.warning("could not record the peak of the %s job at %s", name, path)


def planned_mb(settings: Settings, name: str) -> float:
    """How much memory to set aside for one run of a job."""
    ceiling = limits_for(settings).get(name, UNKNOWN_LIMIT_MB)
    peak = read_peak(settings, name)
    return ceiling if peak is None else min(ceiling, peak * PLAN_MARGIN)


@dataclass
class Budget:
    """The memory the jobs may use together, shared out between runs."""

    total_mb: float | None
    used_mb: float = 0.0
    running: int = 0
    _changed: asyncio.Condition | None = field(default=None, repr=False)

    def _condition(self) -> asyncio.Condition:
        if self._changed is None:
            self._changed = asyncio.Condition()
        return self._changed

    def fits(self, wanted_mb: float) -> bool:
        """True when a run of this size may start now.

        Nothing running: always, so a job bigger than the whole budget
        still runs, alone.
        """
        if self.total_mb is None or self.running == 0:
            return True
        return self.used_mb + wanted_mb <= self.total_mb

    async def acquire(self, name: str, wanted_mb: float) -> None:
        """Wait until the run fits, then set its memory aside."""
        changed = self._condition()
        async with changed:
            if not self.fits(wanted_mb):
                logger.info(
                    "the %s job waits for memory: needs %.0f MB, %.0f of %.0f MB in use",
                    name,
                    wanted_mb,
                    self.used_mb,
                    self.total_mb or 0,
                )
            await changed.wait_for(lambda: self.fits(wanted_mb))
            self.used_mb += wanted_mb
            self.running += 1

    async def release(self, wanted_mb: float) -> None:
        """Give a finished run's memory back, and wake the waiting runs."""
        changed = self._condition()
        async with changed:
            self.used_mb = max(0.0, self.used_mb - wanted_mb)
            self.running = max(0, self.running - 1)
            changed.notify_all()


def budget_for(settings: Settings) -> Budget:
    """The jobs' shared budget: the container's limit, less the supervisor."""
    if settings.jobs_memory_budget_mb > 0:
        return Budget(settings.jobs_memory_budget_mb)
    limit = container_limit_mb()
    if limit is None:
        return Budget(None)
    own = rss_mb(os.getpid())
    return Budget(max(limit - own - HEADROOM_MB, 0.0))


async def run_job(name: str, settings: Settings, budget: Budget) -> None:
    """Run one job in a child process, inside its share of the budget.

    Raises `OverLimit` when the job passed its ceiling and was killed,
    and RuntimeError when it failed on its own.
    """
    ceiling = limits_for(settings).get(name, UNKNOWN_LIMIT_MB)
    wanted = planned_mb(settings, name)
    await budget.acquire(name, wanted)
    started = time.monotonic()
    peak = 0.0
    try:
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "sonoran.jobs.run_task", name
        )
        while True:
            early = time.monotonic() - started < EARLY_SECONDS
            try:
                await asyncio.wait_for(
                    child.wait(), timeout=EARLY_WATCH_SECONDS if early else WATCH_SECONDS
                )
                break
            except TimeoutError:
                pass
            now_mb = tree_rss_mb(child.pid)
            peak = max(peak, now_mb)
            if now_mb > ceiling:
                _kill_tree(child.pid)
                await child.wait()
                raise OverLimit(
                    f"the {name} job used {now_mb:.0f} MB, over its limit of {ceiling:.0f} MB, "
                    "and was stopped"
                )
        logger.info(
            "the %s job used at most %.0f MB of its %.0f MB limit (planned %.0f MB) in %.0fs",
            name,
            peak,
            ceiling,
            wanted,
            time.monotonic() - started,
        )
        if child.returncode != 0:
            # A failed run is not a measure of the job: it may have ended
            # before it reached its working size.
            raise RuntimeError(f"the {name} job exited with {child.returncode}")
        if peak > 0:
            _record_peak(settings, name, peak)
    finally:
        await budget.release(wanted)


def lower_own_priority() -> None:
    """Make this process the kernel's first choice when memory runs out.

    Raising one's own OOM score needs no privilege. Called by a child at
    start, so the supervisor and the other jobs outlive it.
    """
    try:
        Path("/proc/self/oom_score_adj").write_text(str(CHILD_OOM_SCORE_ADJ), encoding="ascii")
    except OSError:
        pass
