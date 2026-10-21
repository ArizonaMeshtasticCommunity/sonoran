"""The workflows run with a read-only token and with actions pinned by commit.

Every job here runs on self-hosted hardware that belongs to a community
member (AGENTS.md 6.2). Two rules keep what runs there fixed:

- A token that can write is a token that a compromised step can use.
  Each workflow says what its token may do, and `contents: read` is the
  most that CI needs.
- `actions/checkout@v4` is a tag, and the owner of the action can move
  a tag. A commit cannot be moved. The tag stays as a comment, so a
  reader can see which release the commit is.
"""

import re
from pathlib import Path

import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))
BY_COMMIT = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_every_workflow_sets_the_permissions_of_its_token() -> None:
    assert WORKFLOWS
    for path in WORKFLOWS:
        permissions = _load(path).get("permissions")
        assert isinstance(permissions, dict), f"{path.name} has no top-level permissions"
        assert permissions.get("contents") == "read", f"{path.name}: {permissions}"


def test_ci_needs_no_write_permission() -> None:
    permissions = _load(next(p for p in WORKFLOWS if p.name == "ci.yml"))["permissions"]
    assert permissions == {"contents": "read"}


def test_every_action_is_pinned_by_commit() -> None:
    for path in WORKFLOWS:
        for name, job in _load(path)["jobs"].items():
            for step in job.get("steps", []):
                action = step.get("uses")
                if action is None or action.startswith("./"):
                    continue
                assert BY_COMMIT.match(action), f"{path.name} {name}: {action} is not a commit"


def test_every_pin_names_its_release() -> None:
    """Would be caught: a bare commit that nobody can map to a release."""
    for path in WORKFLOWS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"uses: [\w.-]+/[\w./-]+@[0-9a-f]{40}", line):
                assert re.search(r"# v\d+\.\d+\.\d+$", line), f"{path.name}: {line.strip()}"
