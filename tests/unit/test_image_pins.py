"""Every image this project builds on is pinned, and the app cannot rewrite itself.

A moving tag (`python:3.13-slim`, `timescale/timescaledb-ha:pg17`)
gives two builds of one commit two different systems, and nothing
records which one ran. The tag stays in the reference so a reader can
see what it tracks. The digest is what Docker pulls.

The application user must not own `/app`. The process reads its code
there and writes nothing there. The only places it writes are the cache
directories under `/var/lib/sonoran` (AGENTS.md 9.14, item 3).
"""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILES = (ROOT / "Dockerfile", ROOT / "tools" / "backup.Dockerfile")
COMPOSE = ROOT / "docker-compose.yml"
PINNED = re.compile(r"^[a-z0-9./_-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")


def _from_images(dockerfile: Path) -> list[str]:
    images = []
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        found = re.match(r"^FROM\s+(\S+)", line)
        if found:
            images.append(found.group(1))
        found = re.match(r"^COPY\s+--from=(\S+)", line)
        if found:
            images.append(found.group(1))
    return images


def _instructions(dockerfile: Path) -> list[str]:
    """The Dockerfile's instructions, with continued lines joined."""
    text = dockerfile.read_text(encoding="utf-8").replace("\\\n", " ")
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def test_every_dockerfile_image_is_pinned_by_digest() -> None:
    for dockerfile in DOCKERFILES:
        images = _from_images(dockerfile)
        assert images, f"{dockerfile.name} names no image"
        for image in images:
            assert PINNED.match(image), f"{dockerfile.name} uses {image!r}, not a pinned digest"


def test_every_compose_image_is_pinned_by_digest() -> None:
    services = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    images = {name: s["image"] for name, s in services.items() if "image" in s}
    assert "timescaledb" in images
    for name, image in images.items():
        assert PINNED.match(image), f"{name} uses {image!r}, not a pinned digest"


def test_the_app_user_does_not_own_the_app() -> None:
    for instruction in _instructions(ROOT / "Dockerfile"):
        if "chown" not in instruction:
            continue
        assert "/app" not in instruction, f"the app user is given its own code: {instruction}"
        assert "--chown" not in instruction or "root" in instruction, instruction


def test_the_app_user_owns_its_caches() -> None:
    """Would be caught: a fix that took every chown out, caches included."""
    owned = [i for i in _instructions(ROOT / "Dockerfile") if "chown" in i]
    assert any("/var/lib/sonoran" in i and "azmsh" in i for i in owned)
    for cache in ("terrain", "landcover", "coverage"):
        assert any(f"/var/lib/sonoran/{cache}" in i for i in _instructions(ROOT / "Dockerfile"))
