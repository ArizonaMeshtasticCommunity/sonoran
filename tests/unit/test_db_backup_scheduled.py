"""The scheduled database backup (#216).

On 2026-09-25 the production box rebooted and the database did not start
again: the storage had lost writes that Postgres flushed, and pg_control
was stale. The newest backup was two days old, because the only backup
script ran when a person ran it.

`tools/db_backup_scheduled.sh` runs in the `backup` service. These tests
run the real script under bash, with stub `pg_dump`, `pg_dumpall`,
`pg_restore` and `df` first on PATH. The stubs let a test make each step
fail, which a live database cannot be asked to do on cue.

The property that matters most: **a dump that cannot be read back never
counts as a backup**, and it never pushes a good backup out of the
rotation. A file that looks like a backup and restores nothing is worse
than no file.
"""

import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "db_backup_scheduled.sh"

# The script reads ISO weeks with GNU `date -d`. It runs in a Linux
# container, where that is always present; BSD date has no `-d`.
needs_gnu_date = pytest.mark.skipif(
    subprocess.run(["date", "-u", "-d", "20260925", "+%G"], capture_output=True).returncode != 0,
    reason="the script runs in a Linux container and uses GNU date",
)

STUBS = {
    "pg_dumpall": 'if [ -n "$STUB_ROLES_FAIL" ]; then exit 1; fi\n'
    'if [ -n "$STUB_ROLES_EMPTY" ]; then exit 0; fi\n'
    'echo "CREATE ROLE azmsh_api;"\n',
    "pg_dump": 'if [ -n "$STUB_DUMP_FAIL" ]; then echo partial; exit 1; fi\n'
    'echo "dump of $PGDATABASE"\n',
    "pg_restore": 'if [ -n "$STUB_RESTORE_FAIL" ]; then exit 1; fi\n'
    'case "$1" in --file=/dev/null) test -s "$2" ;; *) exit 9 ;; esac\n',
    "df": 'echo "Filesystem 1024-blocks Used Available Capacity Mounted"\n'
    'echo "stub 100000000 1 ${STUB_FREE_KB:-100000000} 1% /"\n',
}


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in STUBS.items():
        stub = bin_dir / name
        stub.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
        stub.chmod(0o755)
    backups = tmp_path / "backups"
    return {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "BACKUP_DIR": str(backups),
        "PGDATABASE": "azmsh",
    }


def _run(env: dict[str, str], mode: str, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), mode],
        env={**env, **extra},
        capture_output=True,
        text=True,
        timeout=30,
    )


def _backups(env: dict[str, str]) -> list[str]:
    return sorted(os.listdir(env["BACKUP_DIR"]))


def _dumps(env: dict[str, str]) -> list[str]:
    return [f for f in _backups(env) if f.endswith(".dump")]


def _seed(env: dict[str, str], when: datetime) -> str:
    """Write a backup pair as if it were taken at `when`."""
    directory = Path(env["BACKUP_DIR"])
    directory.mkdir(exist_ok=True)
    ts = when.strftime("%Y%m%d-%H%M%S")
    (directory / f"azmsh-{ts}.dump").write_text("old", encoding="utf-8")
    (directory / f"roles-{ts}.sql").write_text("CREATE ROLE x;", encoding="utf-8")
    return f"azmsh-{ts}.dump"


def test_the_script_is_there() -> None:
    """The control, so a moved file fails as itself."""
    assert SCRIPT.exists()


@needs_gnu_date
def test_a_good_backup_is_two_files_and_a_status(env: dict[str, str]) -> None:
    done = _run(env, "once")
    assert done.returncode == 0, done.stdout + done.stderr

    files = _backups(env)
    dumps = [f for f in files if f.startswith("azmsh-")]
    roles = [f for f in files if f.startswith("roles-")]
    assert len(dumps) == 1 and len(roles) == 1
    assert dumps[0].removeprefix("azmsh-").removesuffix(".dump") == roles[0].removeprefix(
        "roles-"
    ).removesuffix(".sql"), "the pair must share one timestamp"
    assert not [f for f in files if f.startswith(".partial")]

    status = (Path(env["BACKUP_DIR"]) / "last-good").read_text(encoding="utf-8").split()
    assert abs(int(status[0]) - time.time()) < 60
    assert status[1] == dumps[0]


@pytest.mark.parametrize(
    "fault",
    ["STUB_RESTORE_FAIL", "STUB_DUMP_FAIL", "STUB_ROLES_FAIL", "STUB_ROLES_EMPTY"],
)
@needs_gnu_date
def test_a_failed_backup_leaves_nothing_that_looks_like_one(
    env: dict[str, str], fault: str
) -> None:
    """The control for the whole feature.

    Each fault is a step that fails part-way. None of them may leave a
    file with a backup's name, move `last-good`, or remove a good backup.
    """
    good = _seed(env, datetime.now(UTC) - timedelta(days=1))
    before = _backups(env)

    done = _run(env, "once", **{fault: "1"})

    assert done.returncode != 0
    assert _backups(env) == before, "nothing new, nothing removed"
    assert good in _dumps(env)
    assert not (Path(env["BACKUP_DIR"]) / "last-good").exists()


@needs_gnu_date
def test_a_dump_is_not_started_without_room_for_it(env: dict[str, str]) -> None:
    """A full disk stops the database, and on this box the other accounts."""
    _seed(env, datetime.now(UTC) - timedelta(days=1))
    before = _backups(env)

    done = _run(env, "once", STUB_FREE_KB="0")

    assert done.returncode != 0
    assert "not enough free space" in done.stdout
    assert _backups(env) == before


@needs_gnu_date
def test_a_killed_attempt_is_cleaned_up_by_the_next(env: dict[str, str]) -> None:
    directory = Path(env["BACKUP_DIR"])
    directory.mkdir()
    (directory / ".partial-20260101-000000.dump").write_text("cut short", encoding="utf-8")

    assert _run(env, "once").returncode == 0
    assert not [f for f in _backups(env) if f.startswith(".partial")]


@needs_gnu_date
def test_the_rotation_keeps_the_newest_days_and_one_per_week(env: dict[str, str]) -> None:
    # One backup a day for 60 days, ending on a known Friday.
    end = datetime(2026, 9, 25, 7, 0, tzinfo=UTC)
    for n in range(60):
        _seed(env, end - timedelta(days=n))

    done = _run(env, "prune", BACKUP_KEEP_DAILY="7", BACKUP_KEEP_WEEKLY="4")
    assert done.returncode == 0, done.stdout + done.stderr

    kept = [d.removeprefix("azmsh-")[:8] for d in _dumps(env)]
    # The newest seven days.
    daily = {(end - timedelta(days=n)).strftime("%Y%m%d") for n in range(7)}
    # The newest backup of the four newest ISO weeks. 2026-09-25 is a
    # Friday, so its week's newest backup is itself; the week before
    # ends on Sunday 2026-09-20, and so on.
    weekly = {"20260925", "20260920", "20260913", "20260906"}
    assert set(kept) == daily | weekly
    # Every kept dump still has its roles file, and no roles file is left
    # without its dump.
    roles = {f.removeprefix("roles-")[:8] for f in _backups(env) if f.startswith("roles-")}
    assert roles == set(kept)


@needs_gnu_date
def test_the_newest_backup_survives_a_rotation_set_to_zero(env: dict[str, str]) -> None:
    now = datetime.now(UTC)
    newest = _seed(env, now)
    _seed(env, now - timedelta(days=1))

    _run(env, "prune", BACKUP_KEEP_DAILY="0", BACKUP_KEEP_WEEKLY="0")

    assert _dumps(env) == [newest]


@needs_gnu_date
def test_a_dump_made_by_hand_is_never_rotated_out(env: dict[str, str]) -> None:
    """tools/db_backup.sh and a person use other names. They are not ours to delete."""
    for n in range(10):
        _seed(env, datetime.now(UTC) - timedelta(days=30 + n))
    by_hand = Path(env["BACKUP_DIR"]) / "azmsh-postrecovery-20260925-002643.dump"
    by_hand.write_text("precious", encoding="utf-8")

    _run(env, "prune", BACKUP_KEEP_DAILY="1", BACKUP_KEEP_WEEKLY="0")

    assert by_hand.exists()


def test_check_fails_with_no_backup(env: dict[str, str]) -> None:
    assert _run(env, "check").returncode == 1


def test_check_passes_on_a_fresh_backup_and_fails_on_a_stale_one(env: dict[str, str]) -> None:
    status = Path(env["BACKUP_DIR"])
    status.mkdir()
    now = int(time.time())

    (status / "last-good").write_text(f"{now - 3600}\nazmsh-x.dump\n", encoding="utf-8")
    assert _run(env, "check", BACKUP_STALE_SECONDS="7200").returncode == 0

    (status / "last-good").write_text(f"{now - 10800}\nazmsh-x.dump\n", encoding="utf-8")
    assert _run(env, "check", BACKUP_STALE_SECONDS="7200").returncode == 1


def test_an_unknown_mode_is_refused(env: dict[str, str]) -> None:
    assert _run(env, "backwards").returncode == 2


# --- the service in docker-compose.yml ----------------------------------


def _service() -> dict[str, object]:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    service: dict[str, object] = compose["services"]["backup"]
    return service


def test_the_service_gets_one_credential_and_not_the_env_file() -> None:
    """`.env` holds every credential in the stack. This service needs one."""
    service = _service()
    assert "env_file" not in service
    environment = service["environment"]
    assert isinstance(environment, dict)
    secrets = {k for k in environment if "PASSWORD" in k or k.startswith("DATABASE_URL")}
    assert secrets == {"PGPASSWORD"}
    assert "CHANNEL_KEYS" not in environment


def test_the_service_has_a_memory_limit_and_a_healthcheck() -> None:
    service = _service()
    assert "mem_limit" in service
    healthcheck = service["healthcheck"]
    assert isinstance(healthcheck, dict)
    assert "check" in healthcheck["test"]


def test_the_backups_stay_out_of_the_build_context_and_the_repository() -> None:
    """Every `docker build` would otherwise send every dump to the daemon."""
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert "backups" in dockerignore
    assert "backups/" in gitignore


@needs_gnu_date
@pytest.mark.skipif(os.geteuid() == 0, reason="root can write to a read-only directory")
def test_an_unwritable_directory_is_named_in_the_log(env: dict[str, str]) -> None:
    """Docker makes a missing bind-mount directory as root, and we are not root."""
    directory = Path(env["BACKUP_DIR"])
    directory.mkdir()
    directory.chmod(0o555)
    try:
        done = _run(env, "once")
    finally:
        directory.chmod(0o755)

    assert done.returncode != 0
    assert "BACKUP_UID" in done.stdout
