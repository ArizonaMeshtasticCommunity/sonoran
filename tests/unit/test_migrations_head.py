"""The migrations form one line, with one head (#348).

Two branches that each add a migration on the same parent both pass
their own CI, and main then has two heads: `alembic upgrade head`
refuses to run, and so does the next deploy. This fails the second
branch instead, until its author rebases on main and sets
`down_revision` to the current head (`alembic heads`).

No database: Alembic reads the revision files only.
"""

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]


def _scripts() -> ScriptDirectory:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "src" / "sonoran" / "db" / "migrations"))
    return ScriptDirectory.from_config(config)


def test_the_migrations_have_one_head() -> None:
    heads = _scripts().get_heads()
    assert len(heads) == 1, (
        f"the migrations have {len(heads)} heads: {sorted(heads)}. Two branches added a "
        "migration on the same parent. Rebase on main and set `down_revision` of the "
        "newer one to the head of main (`alembic heads`)."
    )
