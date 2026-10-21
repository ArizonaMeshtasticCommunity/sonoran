"""Every service that needs the database can reach it by name.

The database is on the `sonoran-internal` network only, so two stacks
on one host cannot reach each other's database (PR #320). A service
that waits for the database must therefore be on that network too.
Otherwise it cannot resolve `timescaledb` and does not start.

`contrib` was added on `main` while #320 was open, and it was left on
the default network. These tests catch that kind of miss.
"""

from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _services() -> dict[str, dict]:
    return yaml.safe_load(COMPOSE.read_text())["services"]


def _networks(service: dict) -> set[str]:
    networks = service.get("networks")
    if networks is None:
        return {"default"}
    return set(networks)


def _needs_database(service: dict) -> bool:
    return "timescaledb" in (service.get("depends_on") or {})


DATABASE_USERS = sorted(name for name, s in _services().items() if _needs_database(s))


def test_the_database_users_are_found() -> None:
    """Would be caught: a reader that finds no service proves nothing."""
    assert {"web", "migrate", "ingest", "jobs", "contrib", "backup"} <= set(DATABASE_USERS)


@pytest.mark.parametrize("name", DATABASE_USERS)
def test_each_database_user_shares_a_network_with_it(name: str) -> None:
    services = _services()
    shared = _networks(services[name]) & _networks(services["timescaledb"])
    assert shared, f"{name} cannot resolve timescaledb: no shared network"
