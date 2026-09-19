"""The initial migration refuses to create a role on a known password.

Revision 0001 used to default all three role passwords to `change_me`,
and `.env.example` never named the variables that set them while
shipping `change_me` inside all three DSNs. `tools/db_restore.sh` tells
an operator to copy that file. So the documented first run produced a
working deployment whose three least-privilege database roles were all
reachable with a password published in this repository, and nothing
anywhere reported a fault.

The fix is to have no default at all. These tests pin the refusal and
the quoting: a password is chosen by an operator, it is interpolated
into a `CREATE ROLE` statement, and it must be a value rather than
grammar.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "sonoran"
    / "db"
    / "migrations"
    / "versions"
    / "0001_initial.py"
)


def _initial() -> ModuleType:
    """Load revision 0001 by path.

    The versions directory is not a package, because Alembic loads each
    revision by file. So is this.
    """
    spec = importlib.util.spec_from_file_location("sonoran_initial_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


initial = _initial()


# --- the refusal -------------------------------------------------------


def test_a_missing_role_password_stops_the_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No variable, no roles. This used to return "change_me"."""
    monkeypatch.delenv("AZMSH_INGEST_PASSWORD", raising=False)
    with pytest.raises(initial.MissingRolePassword) as caught:
        initial._password("AZMSH_INGEST_PASSWORD")
    # The message has to name the variable. This is read once, by
    # somebody watching a deployment fail.
    assert "AZMSH_INGEST_PASSWORD" in str(caught.value)


def test_an_empty_role_password_stops_the_migration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty variable is not a password, and PostgreSQL would take it."""
    monkeypatch.setenv("AZMSH_API_PASSWORD", "")
    with pytest.raises(initial.MissingRolePassword):
        initial._password("AZMSH_API_PASSWORD")


@pytest.mark.parametrize("placeholder", sorted(initial.PLACEHOLDER_PASSWORDS))
def test_the_published_placeholder_stops_the_migration(
    placeholder: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Copying .env.example unedited must not produce a working deployment.

    This is the whole defect. The old default was `change_me` and the
    example file used it, so the failing state looked exactly like the
    working one.
    """
    monkeypatch.setenv("AZMSH_JOBS_PASSWORD", placeholder)
    with pytest.raises(initial.MissingRolePassword):
        initial._password("AZMSH_JOBS_PASSWORD")


def test_a_real_password_is_returned_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """The guard refuses the known values and nothing else."""
    monkeypatch.setenv("AZMSH_INGEST_PASSWORD", "a-real-one")
    assert initial._password("AZMSH_INGEST_PASSWORD") == "a-real-one"


def test_a_password_that_merely_contains_the_placeholder_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The test is equality, not a substring.

    A guard that refused any password containing `change_me` would
    refuse a perfectly good one and send its owner looking for a fault
    that is not there.
    """
    monkeypatch.setenv("AZMSH_API_PASSWORD", "change_me_not-4-real")
    assert initial._password("AZMSH_API_PASSWORD") == "change_me_not-4-real"


# --- the quoting -------------------------------------------------------


def test_a_quote_in_a_password_stays_a_character() -> None:
    """A password is a value in the statement, never grammar.

    An operator may choose any character. Doubling the quote is the
    whole of the escape while `standard_conforming_strings` is on,
    which is the PostgreSQL default.
    """
    assert initial._sql_literal("pa'ss") == "'pa''ss'"


def test_a_password_cannot_close_the_statement() -> None:
    """The classic shape, spelled out.

    Without the escape this would have ended the literal and left
    `; DROP ROLE azmsh_api; --` as statements in the DO block, running
    as the superuser that applies migrations.
    """
    literal = initial._sql_literal("'; DROP ROLE azmsh_api; --")
    assert literal == "'''; DROP ROLE azmsh_api; --'"
    # One opening quote, one closing quote, and every quote between
    # them doubled: the body cannot reach the parser as grammar.
    assert literal.startswith("'") and literal.endswith("'")
    assert literal[1:-1].count("'") % 2 == 0


def test_a_backslash_is_an_ordinary_character() -> None:
    """Not doubled. Doubling it would change the operator's password."""
    assert initial._sql_literal("back\\slash") == "'back\\slash'"


def test_a_password_holding_the_block_tag_is_refused() -> None:
    """The dollar-quoted block cannot be closed from inside a password.

    The tag is `$azmsh_roles$` rather than a bare `$$` so that an
    ordinary `$$` in a password is harmless. A password holding the tag
    itself is refused rather than escaped: there is no escape for a
    dollar-quote delimiter, and no operator needs that string.
    """
    with pytest.raises(initial.MissingRolePassword):
        initial._sql_literal(f"x{initial.ROLE_BLOCK_TAG}y")


def test_the_block_tag_is_not_the_bare_dollar_quote() -> None:
    """A bare `$$` block could be closed by a `$$` inside a password."""
    assert initial.ROLE_BLOCK_TAG != "$$"
    assert initial.ROLE_BLOCK_TAG.startswith("$") and initial.ROLE_BLOCK_TAG.endswith("$")


def test_a_null_byte_is_refused() -> None:
    """PostgreSQL cannot hold one, and it truncates the rest silently."""
    with pytest.raises(initial.MissingRolePassword):
        initial._sql_literal("null\x00byte")
