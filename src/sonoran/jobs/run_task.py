"""Run one job once, as a child of the jobs supervisor (#371).

    python -m sonoran.jobs.run_task coverage

The supervisor (`sonoran/jobs/supervisor.py`) starts one of these per
run and watches its memory. It exits 0 when the job finished and 1 when
it failed; the supervisor logs either and keeps its own clock.
"""

import asyncio
import sys

from sonoran.config import get_settings
from sonoran.jobs import scheduler, supervisor
from sonoran.logging import configure_logging, get_logger

logger = get_logger(__name__)


def main(argv: list[str]) -> int:
    """Run the job named in `argv[1]`. Return the process's exit code."""
    if len(argv) != 2 or argv[1] not in scheduler.JOB_BODIES:
        print(f"usage: run_task <{'|'.join(sorted(scheduler.JOB_BODIES))}>", file=sys.stderr)
        return 2
    settings = get_settings()
    configure_logging(settings.log_level)
    supervisor.lower_own_priority()
    try:
        asyncio.run(scheduler.run_body(argv[1], settings))
    except Exception:
        logger.exception("the %s job failed", argv[1])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
