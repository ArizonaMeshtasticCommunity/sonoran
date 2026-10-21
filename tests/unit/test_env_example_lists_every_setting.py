"""`.env.example` names every setting the application reads.

README says the file "lists them all", and an operator reads it, not
`sonoran/config.py`. It once missed 33 settings, among them the
`MAP_HOME_*` box that clips address search, so a deployment outside
Arizona got Arizona's answers with nothing to say why.

A setting counts as listed when a line starts with `NAME=`, or with
`# NAME=` for a setting that is shown commented out on purpose.
"""

import re
from pathlib import Path

from sonoran.config import Settings

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / ".env.example"

# Settings that are deliberately not in `.env.example`. Each entry needs
# a reason here. Keep this empty unless a setting is for tests or
# internal use only.
NOT_FOR_OPERATORS: dict[str, str] = {}

LISTED = re.compile(r"^(?:#\s*)?([A-Z][A-Z0-9_]*)=", re.MULTILINE)


def _listed(text: str) -> set[str]:
    return set(LISTED.findall(text))


def _missing(text: str) -> list[str]:
    listed = _listed(text)
    return [
        name.upper()
        for name in Settings.model_fields
        if name.upper() not in listed and name.upper() not in NOT_FOR_OPERATORS
    ]


def test_every_setting_is_in_the_example_file() -> None:
    missing = _missing(EXAMPLE.read_text(encoding="utf-8"))
    assert not missing, (
        "these settings are in sonoran/config.py but not in .env.example; "
        f"add each one with a comment and its default: {missing}"
    )


def test_the_exclusions_name_real_settings() -> None:
    """A stale exclusion would hide nothing and say something false."""
    fields = {name.upper() for name in Settings.model_fields}
    assert set(NOT_FOR_OPERATORS) <= fields


def test_a_missing_setting_is_caught() -> None:
    """The check fails on a file that leaves one setting out."""
    text = EXAMPLE.read_text(encoding="utf-8")
    without = re.sub(r"^MAP_HOME_WEST=.*$", "", text, flags=re.MULTILINE)
    assert _missing(without) == ["MAP_HOME_WEST"]


def test_a_mention_in_prose_does_not_count() -> None:
    """Only a `NAME=` line lists a setting, not a name inside a sentence."""
    assert _listed("# Set MAP_HOME_WEST to your own value.\n") == set()
    assert _listed("# MAP_HOME_WEST=-115.0\n") == {"MAP_HOME_WEST"}


def test_the_example_file_loads() -> None:
    """Every value in the file is one the settings accept."""
    Settings(_env_file=EXAMPLE)  # type: ignore[call-arg]
