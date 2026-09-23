"""The integration suite must run, or say loudly that it did not.

Every database-backed test in this repository skipped on a Mac running
Colima for months, because testcontainers' reaper sidecar bind-mounts
the Docker socket and Colima's socket cannot be bind-mounted. pytest
prints a skip and a pass on the same summary line, so 167 silent skips
read as a green run, and a real failure in `/api/chat/overview` reached
CI behind them.

Two guards came out of that, and this module holds both of them to
their behaviour rather than to their text:

* `_disable_ryuk` turns the reaper off, so the container starts.
* `_no_container` turns "no container" into a failure wherever the
  result is going to be trusted.

These are unit tests on purpose. They must run on the machine where the
integration suite is skipping, which is exactly the machine where an
integration test cannot report anything.
"""

import os

import pytest

from tests.integration.conftest import (
    REQUIRE_INTEGRATION,
    RYUK_DISABLED,
    _disable_ryuk,
    _no_container,
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each case from an environment that has said nothing."""
    monkeypatch.delenv(RYUK_DISABLED, raising=False)
    monkeypatch.delenv(REQUIRE_INTEGRATION, raising=False)


def test_the_reaper_is_off_by_default(clean_env: None) -> None:
    """Unset means off, which is what makes the container start."""
    _disable_ryuk()
    assert os.environ[RYUK_DISABLED] == "true"


def test_an_explicit_choice_is_not_overridden(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Somebody who asked for the reaper keeps it.

    The negative half of the test above. Without this, `_disable_ryuk`
    could be written as a plain assignment and still pass -- and a
    developer debugging a leaked container could not turn the reaper
    back on.
    """
    monkeypatch.setenv(RYUK_DISABLED, "false")
    _disable_ryuk()
    assert os.environ[RYUK_DISABLED] == "false"


def test_a_missing_container_skips_when_nobody_asked(clean_env: None) -> None:
    """The default stays a skip, so `pytest` still works without Docker."""
    with pytest.raises(pytest.skip.Exception) as caught:
        _no_container(RuntimeError("no docker here"))
    assert "no docker here" in str(caught.value)


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " true "])
def test_a_missing_container_fails_where_it_is_trusted(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    """With the variable set, a container that will not start is red.

    Parametrised over the spellings a CI file is likely to use. A guard
    that only recognised `1` would be silently off in a workflow that
    wrote `true`, which is the same false green in a new place.
    """
    monkeypatch.setenv(REQUIRE_INTEGRATION, value)
    with pytest.raises(pytest.fail.Exception) as caught:
        _no_container(RuntimeError("no docker here"))
    assert REQUIRE_INTEGRATION in str(caught.value)
    assert "no docker here" in str(caught.value)


def test_an_unrecognised_value_does_not_silently_arm_it(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`0` means no, and must not be read as "the variable is present"."""
    monkeypatch.setenv(REQUIRE_INTEGRATION, "0")
    with pytest.raises(pytest.skip.Exception):
        _no_container(RuntimeError("no docker here"))
