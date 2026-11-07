"""The workflows run with a read-only token and with actions pinned by commit.

Every job here runs on self-hosted hardware that belongs to a community
member (AGENTS.md 6.2). Two rules keep what runs there fixed:

- A token that can write is a token that a compromised step can use.
  Each workflow says what its token may do, and `contents: read` is the
  most that CI needs.
- `actions/checkout@v7` is a tag, and the owner of the action can move
  a tag. A commit cannot be moved. The tag stays as a comment, so a
  reader can see which release the commit is.
"""

import json
import re
from pathlib import Path

import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))
ROOT = Path(__file__).resolve().parents[2]
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


SAME_REPOSITORY = "github.event.pull_request.head.repo.full_name == github.repository"
PUSH = "github.event_name == 'push'"


def _triggers(workflow: dict) -> set[str]:
    # YAML 1.1 reads the key `on` as True.
    on = workflow.get("on", workflow.get(True))
    if isinstance(on, str):
        return {on}
    return set(on or ())


def test_no_self_hosted_job_runs_for_a_pull_request_from_a_fork() -> None:
    """A pull request from a fork runs its author's code on the runner.

    The runners are a community member's machine, with Docker on it. A
    pull request from a fork can change any test, the Dockerfile or the
    workflow itself, so each self-hosted job of a workflow that a pull
    request starts must refuse a fork.
    """
    checked = 0
    for path in WORKFLOWS:
        workflow = _load(path)
        if not _triggers(workflow) & {"pull_request", "pull_request_target"}:
            continue
        for name, job in workflow["jobs"].items():
            if "self-hosted" not in str(job.get("runs-on")):
                continue
            condition = " ".join(str(job.get("if", "")).split())
            assert SAME_REPOSITORY in condition, f"{path.name} {name} runs for a fork"
            checked += 1
    assert checked, "no self-hosted job of a pull request workflow was checked"


MICROVM = ["self-hosted", "sonoran-microvm"]


def test_every_job_runs_in_a_microvm() -> None:
    """Each job asks for a Firecracker microVM, never for any runner.

    `runs-on: self-hosted` alone takes any self-hosted runner of the
    organization, including one where jobs share a machine and its
    Docker. The `sonoran-microvm` label takes a VM that runs one job and
    is destroyed (ci-runner, README.md).
    """
    checked = 0
    for path in WORKFLOWS:
        for name, job in _load(path)["jobs"].items():
            assert job.get("runs-on") == MICROVM, f"{path.name} {name}: {job.get('runs-on')}"
            checked += 1
    assert checked


ONLY_ON_HOSTED = "${{ runner.environment == 'github-hosted' && '--with-deps' || '' }}"


def test_no_job_installs_system_packages_in_a_microvm() -> None:
    """`--with-deps` runs only on a GitHub-hosted runner.

    It installs Chromium's system libraries with sudo apt. The microVM
    image has them already, and a job must not change the system that
    it runs on. live-e2e.yml once used it on every runner.
    """
    for path in WORKFLOWS:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "--with-deps" in line and not line.lstrip().startswith("#"):
                assert ONLY_ON_HOSTED in line, f"{path.name}: {line.strip()}"


def test_the_test_job_sets_up_node() -> None:
    """The unit suite runs JavaScript with node, and fails without it.

    The old shared runner had node installed, so the test job worked
    without asking for it. A microVM has no node until a step installs
    it, and 97 tests failed with "node is not on PATH" (run 41548026423).
    """
    steps = _load(next(p for p in WORKFLOWS if p.name == "ci.yml"))["jobs"]["test"]["steps"]
    uses = [str(step.get("uses", "")) for step in steps]
    assert any(action.startswith("actions/setup-node@") for action in uses), uses


def test_setup_node_checks_for_the_latest_security_patch() -> None:
    """A cached Node 22 build must not hide a newer security patch."""
    checked = 0
    for path in WORKFLOWS:
        for name, job in _load(path)["jobs"].items():
            for step in job.get("steps", []):
                if not str(step.get("uses", "")).startswith("actions/setup-node@"):
                    continue
                inputs = step.get("with", {})
                assert str(inputs.get("node-version")) == "22", f"{path.name} {name}: {inputs}"
                assert inputs.get("check-latest") is True, f"{path.name} {name}: {inputs}"
                checked += 1
    assert checked


def test_node_tools_are_locked_and_audited() -> None:
    """The browser and linter must not return to an unsafe ad-hoc install."""
    manifest = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    tools = manifest["devDependencies"]
    playwright = tuple(int(part) for part in tools["playwright"].split("."))
    eslint = tuple(int(part) for part in tools["eslint"].split("."))
    assert playwright >= (1, 55, 1), "Playwright is vulnerable to CVE-2025-59288"
    assert eslint >= (10, 0, 0), "ESLint 9 is no longer supported"
    assert (ROOT / "package-lock.json").is_file()

    workflows = "\n".join(path.read_text(encoding="utf-8") for path in WORKFLOWS)
    assert "npm install" not in workflows
    assert "npm ci --ignore-scripts" in workflows
    assert "npm audit --audit-level=high" in workflows


def test_the_guard_still_runs_ci_on_main() -> None:
    """Would be caught: a guard that stopped every run, pushes to main too."""
    workflow = _load(next(p for p in WORKFLOWS if p.name == "ci.yml"))
    assert "push" in _triggers(workflow)
    for name, job in workflow["jobs"].items():
        condition = " ".join(str(job.get("if", "")).split())
        assert f"{PUSH} ||" in condition, f"ci.yml {name} does not run on a push"
