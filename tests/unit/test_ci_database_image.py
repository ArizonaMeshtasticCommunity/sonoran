"""CI and the integration tests run one pinned TimescaleDB, on tmpfs.

`timescale/timescaledb-ha:pg17` is a moving tag. It changed 6 times in
14 days, and each change pulled about 4 GB again on the CI runners'
shared, slow disk. On that disk the image's init server also could not
flush its shutdown checkpoint in 60 s under load, so the container
exited 1 and every database test failed. Pinning the digest stops the
pulls, and tmpfs takes the database off the disk.

Three places name the image: the `migrations` and `e2e` services in
`.github/workflows/ci.yml`, and `tests/integration/conftest.py`. This
holds them to one digest, so an update cannot reach one and miss the
others.
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
CONFTEST = ROOT / "tests" / "integration" / "conftest.py"
PINNED = re.compile(r"^timescale/timescaledb-ha:pg17@sha256:[0-9a-f]{64}$")
PGDATA_TMPFS = "--tmpfs /home/postgres/pgdata/data:rw,uid=1000,gid=1000,mode=0700"


def _services() -> dict[str, dict[str, str]]:
    jobs = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]
    return {name: jobs[name]["services"]["timescaledb"] for name in ("migrations", "e2e")}


def _fixture_image() -> str:
    source = CONFTEST.read_text(encoding="utf-8")
    found = re.search(r'TIMESCALE_IMAGE = \(\s*"([^"]+)"\s*"([^"]+)"\s*\)', source)
    assert found, "TIMESCALE_IMAGE is not the two-part pinned string any more"
    return found.group(1) + found.group(2)


def test_every_ci_database_is_the_same_pinned_image() -> None:
    images = {name: service["image"] for name, service in _services().items()}
    images["conftest"] = _fixture_image()
    for name, image in images.items():
        assert PINNED.match(image), f"{name} uses {image!r}, not a pinned digest"
    assert len(set(images.values())) == 1, f"the three disagree: {images}"


def test_every_ci_database_keeps_its_files_in_ram() -> None:
    for name, service in _services().items():
        assert PGDATA_TMPFS in service["options"], f"the {name} database is on the runner's disk"
    source = CONFTEST.read_text(encoding="utf-8")
    assert "container.tmpfs.update(TIMESCALE_TMPFS)" in source
    assert '"/home/postgres/pgdata/data": "rw,uid=1000,gid=1000,mode=0700' in source


def test_the_deployment_runs_the_database_that_ci_tested() -> None:
    """The compose database and the backup image are the CI digest too.

    The backup's pg_dump must have the major version of the server, and
    a deployment should run the build that CI tested. So two more places
    name the image: the `timescaledb` service of docker-compose.yml and
    the `FROM` of tools/backup.Dockerfile. They take the same digest.
    """
    ci = _services()["migrations"]["image"]
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    backup = (ROOT / "tools" / "backup.Dockerfile").read_text(encoding="utf-8")
    found = re.search(r"^FROM\s+(\S+)", backup, re.MULTILINE)
    assert found, "tools/backup.Dockerfile has no FROM"
    images = {"compose": compose["services"]["timescaledb"]["image"], "backup": found.group(1)}
    assert images == {"compose": ci, "backup": ci}, f"CI tests {ci!r}, the deployment runs {images}"
