"""A service health check must test the server the job will connect to.

`migrations` went red on #172 with

    psycopg.OperationalError: connection failed: server closed the
    connection unexpectedly

on a commit that touched a JavaScript file and a test. The cause was the
health check, and it had nothing to do with the commit.

`timescale/timescaledb-ha:pg17` initialises by starting a temporary
postgres with `-c listen_addresses=''` — the image's own entrypoint
calls it the "socket-only postgresql server" — and runs the initdb
scripts against it over the unix socket. A bare `pg_isready` uses that
same socket, so it reports success while there is **no TCP listener at
all**. GitHub marks the service healthy, the job starts, and the first
connection to the mapped port is accepted by Docker's proxy and closed.

Measured against that image, a server running with
``listen_addresses=''``:

    pg_isready                    /var/run/postgresql:5432 - accepting  (0)
    pg_isready -h 127.0.0.1       127.0.0.1:5432 - no response          (2)

Intermittent, because it is a race between how long `uv sync` takes and
how long the toolkit extensions take. On run 35880147556 the service was
healthy at 15:15:20, the job connected at 15:15:46, and the init server
had still not handed over at 15:15:51.

Over TCP the check cannot pass before the real server is listening,
which is what the job needs to know. This test holds that, because the
bare form is the one everybody writes from memory.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"


def _services() -> list[tuple[str, str, str, dict]]:
    """Every service container in every workflow, with its options."""
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_name, job in (document.get("jobs") or {}).items():
            for service_name, service in (job.get("services") or {}).items():
                found.append((path.name, job_name, service_name, service))
    return found


def test_there_is_a_service_to_check() -> None:
    """The control. Without it every assertion below passes vacuously.

    A rename or a move that took the services out of these workflows
    would otherwise turn this whole file green while checking nothing.
    """
    assert _services(), "no service containers found; this file is checking nothing"


def test_every_database_service_is_probed_over_tcp() -> None:
    for workflow, job, service, config in _services():
        options = config.get("options", "")
        if "pg_isready" not in options:
            continue
        assert "-h 127.0.0.1" in options or "-h localhost" in options, (
            f"{workflow}:{job}:{service} health-checks postgres with a bare "
            f"pg_isready, which passes over the unix socket while the "
            f"image's initdb server is still running and nothing is "
            f"listening on TCP. The job then fails with 'server closed "
            f"the connection unexpectedly'. Probe the address the job "
            f"connects to: {options!r}"
        )


def test_every_database_service_is_probed_at_all() -> None:
    """A service with no health check is worse than a wrong one.

    Without it the job starts the moment the container exists, which is
    the same failure with none of the warning.
    """
    for workflow, job, service, config in _services():
        image = str(config.get("image", ""))
        if "postgres" not in image and "timescale" not in image:
            continue
        assert "--health-cmd" in config.get("options", ""), (
            f"{workflow}:{job}:{service} runs {image} with no health check"
        )
