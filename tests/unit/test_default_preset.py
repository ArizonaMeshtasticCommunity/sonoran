"""Every page opens on the deployment's own preset (#177).

> "MediumFast is our primary preset. So when you land on a page it
> should be set to MediumFast first for the toggle."

Before this, each page opened on whichever preset came first in the
data — busiest for the leaderboards, first-with-links for the graph,
whatever the run published for coverage. All three are defensible and
all three have the same flaw: **the landing view moved with the
traffic rather than with what the community runs.** A quiet week on
MediumFast and the page opened somewhere else.

It is a setting, not a constant, because the preference belongs to a
deployment. Another mesh running LongFast should not have to patch
Python or JavaScript to land on it.

**The fallback is the part worth guarding.** A preferred preset that
was never assessed, or that has no links in the window, must not put an
empty page in front of somebody. Where it is absent, the old behaviour
stands.
"""

import asyncio
from pathlib import Path

import pytest

from sonoran.api.routes import leaderboards
from sonoran.config import Settings
from tests.unit.job_outputs import JobOutputs

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"


def _settings(tmp: Path, preset: str = "MediumFast") -> Settings:
    return Settings(_env_file=None, coverage_cache_dir=str(tmp), default_preset=preset)


# The job outputs of the test in progress. See `tests/unit/job_outputs.py`.
_memory: JobOutputs


@pytest.fixture(autouse=True)
def _outputs(job_outputs: JobOutputs) -> None:
    global _memory
    _memory = job_outputs


def _assessed_presets(settings: Settings) -> list[str]:
    return asyncio.run(leaderboards._assessed_presets(None, settings))  # type: ignore[arg-type]


def _index(tmp: Path, presets: list[tuple[str, int]]) -> None:
    _memory.write_index(
        {"presets": [{"preset": name, "label": name, "node_count": n} for name, n in presets]},
    )


def test_the_default_is_the_meshs_primary_preset() -> None:
    assert Settings(_env_file=None).default_preset == "MediumFast"


def test_the_preferred_preset_leads_even_when_it_is_not_the_busiest(tmp_path: Path) -> None:
    """The whole point. Busiest-first is what moved under the reader."""
    _index(tmp_path, [("LongFast", 900), ("MediumFast", 40), ("ShortFast", 5)])
    assert _assessed_presets(_settings(tmp_path)) == ["MediumFast", "LongFast", "ShortFast"]


def test_the_rest_stay_in_busiest_order_behind_it(tmp_path: Path) -> None:
    """Only the first position changes; the old ordering still decides
    the rest, which is the useful half of it."""
    _index(tmp_path, [("ShortFast", 5), ("LongFast", 900), ("MediumFast", 40)])
    assert _assessed_presets(_settings(tmp_path)) == ["MediumFast", "LongFast", "ShortFast"]


def test_a_preset_nobody_assessed_does_not_lead(tmp_path: Path) -> None:
    """An empty board at the top is worse than the wrong preset.

    This is the control on the test above: without it, a rule that
    simply put `default_preset` first would pass that one and put a
    page with nothing on it in front of every reader here.
    """
    _index(tmp_path, [("LongFast", 900), ("ShortFast", 5)])
    assert _assessed_presets(_settings(tmp_path)) == ["LongFast", "ShortFast"]


def test_another_deployments_choice_is_honoured(tmp_path: Path) -> None:
    """It is a setting, so a mesh running LongFast lands on LongFast."""
    _index(tmp_path, [("MediumFast", 900), ("LongFast", 40)])
    assert _assessed_presets(_settings(tmp_path, "LongFast"))[0] == "LongFast"


def test_no_presets_at_all_is_not_an_error(tmp_path: Path) -> None:
    _index(tmp_path, [])
    assert _assessed_presets(_settings(tmp_path)) == []


# ------------------------------------------------------- the browser


def test_the_preference_reaches_the_browser() -> None:
    """A setting the frontend cannot see is a setting that does nothing."""
    source = (Path(__file__).resolve().parents[2] / "src" / "sonoran" / "api" / "app.py").read_text(
        encoding="utf-8"
    )
    assert '"defaultPreset": settings.default_preset' in source


def test_the_helper_falls_back_rather_than_returning_nothing() -> None:
    """The one behaviour every caller depends on.

    `preferredPreset` returning null or undefined when the wanted
    preset is absent would put every picker into its empty state, on
    exactly the deployments that do not run MediumFast.
    """
    body = (STATIC / "labels.js").read_text(encoding="utf-8")
    start = body.index("function preferredPreset(")
    helper = body[start : body.index("\n  }", start)]
    # The MATCH line specifically. Asserting that "return list[0]"
    # appears somewhere is not enough: the helper returns it early when
    # no preference is configured, so a version that drops the fallback
    # on the miss still contains that string. Mutation-checked — this
    # is the second version of this assertion for exactly that reason.
    assert "match === undefined ? list[0] : match" in helper, (
        "the helper no longer falls back to the first item when the "
        "preferred preset is ABSENT, so every picker on a deployment that "
        "does not run it lands on nothing"
    )
    assert "window.SONORAN" in helper, "the preset name is hard-coded rather than configured"


def test_the_pages_that_choose_a_preset_use_the_helper() -> None:
    for name in ("app.js", "coverage.js"):
        source = (STATIC / name).read_text(encoding="utf-8")
        assert "SonoranLabels.preferredPreset(" in source, (
            f"{name} picks a preset without asking for the deployment's "
            f"preference, so that page still opens wherever the data lands"
        )
