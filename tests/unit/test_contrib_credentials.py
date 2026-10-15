"""The dispatcher's broker password reaches `contrib` and no other service.

docs/ARCHITECTURE.md 2.1: a credential added to `.env` goes into
`x-no-credentials`, and only the service that uses it gets it back. The
`contrib` login is the only one that may publish jobs (#178), so the api,
which faces the internet, must never hold it.
"""

from pathlib import Path

import yaml

COMPOSE = Path(__file__).resolve().parents[2] / "docker-compose.yml"


def _services() -> dict[str, dict]:
    return yaml.safe_load(COMPOSE.read_text())["services"]


def test_the_contrib_password_is_blanked_for_every_other_service() -> None:
    for name, service in _services().items():
        if name in ("contrib", "mesh-graph") or "env_file" not in service:
            continue
        environment = service.get("environment") or {}
        assert environment.get("CONTRIB_MQTT_PASSWORD") == "", name


def test_contrib_gets_its_password_back() -> None:
    environment = _services()["contrib"]["environment"]
    assert "${CONTRIB_MQTT_PASSWORD" in str(environment.get("CONTRIB_MQTT_PASSWORD"))
