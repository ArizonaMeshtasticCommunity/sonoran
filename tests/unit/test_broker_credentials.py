"""Each broker password reaches only the service that logs in with it.

docs/ARCHITECTURE.md 2.1: every service is handed the whole `.env`, so a
credential must be blanked in each service that does not use it. The api
faces the internet; anything that reads its environment would hand over
whatever it holds.

| Password                | The one service that uses it                  |
|-------------------------|-----------------------------------------------|
| `MQTT_PASSWORD`         | ingest (`mqtt/client.py`, via `ingest/pipeline.py`) |
| `RF_MQTT_PASSWORD`      | rf-ingest (`rf/ingest.py`)                    |
| `CONTRIB_MQTT_PASSWORD` | contrib (`contrib/service.py`)                |

The service that uses a password must not set it in `environment:`,
not even to `${...}`: `environment:` beats every `env_file`, so a value
there would replace a password a host gives that service in its own
override file.
"""

from pathlib import Path

import pytest
import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
OWNER = {
    "MQTT_PASSWORD": "ingest",
    "RF_MQTT_PASSWORD": "rf-ingest",
    "CONTRIB_MQTT_PASSWORD": "contrib",
}


def _services() -> dict[str, dict]:
    return yaml.safe_load(COMPOSE.read_text())["services"]


def _with_env_file() -> dict[str, dict]:
    return {name: s for name, s in _services().items() if "env_file" in s}


@pytest.mark.parametrize("password", sorted(OWNER))
def test_every_other_service_has_it_blanked(password: str) -> None:
    for name, service in _with_env_file().items():
        if name == OWNER[password]:
            continue
        environment = service.get("environment") or {}
        assert environment.get(password) == "", f"{name} holds {password}"


@pytest.mark.parametrize("password", sorted(OWNER))
def test_its_own_service_takes_it_from_the_env_files(password: str) -> None:
    environment = _with_env_file()[OWNER[password]].get("environment") or {}
    assert password not in environment


def test_the_api_holds_no_broker_password_at_all() -> None:
    """Would be caught: a denylist that forgot the internet-facing api."""
    environment = _services()["web"]["environment"]
    for password in OWNER:
        assert environment.get(password) == ""
