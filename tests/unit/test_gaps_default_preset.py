"""The gaps page opens on the preset this mesh runs (#177).

Reported by Will: the gaps page defaulted to LongFast, when #177 decided
`default_preset` — `MediumFast` here — should be what every page lands
on.

The cause was not a wrong default. `_resolve` took `listed[0]` from the
gaps index, and the index is written in **channel-name order**, so
"LongFast" sorted above "MediumFast" and the first entry was an
alphabetical accident. The coverage page had already hit this exact bug
and fixed it, and the leaderboards route had the preference logic; the
gaps page had neither.

So the ordering now lives once, in `gaps.store.assessed_presets`, and
both routes read it. A second copy of that sort is precisely how the two
drifted apart in the first place.
"""

from pathlib import Path

from sonoran.api.routes.gaps import _presets, _resolve
from sonoran.api.routes.leaderboards import _assessed_presets
from sonoran.config import Settings
from sonoran.gaps import store


def _settings(tmp: Path, preset: str = "MediumFast") -> Settings:
    return Settings(_env_file=None, coverage_cache_dir=str(tmp), default_preset=preset)


def _index(tmp: Path, presets: list[tuple[str, int]], preset: str = "MediumFast") -> Settings:
    """Write an index in the order the JOB writes it: channel-name order.

    Written sorted on purpose. A fixture in the convenient order would
    pass while the real file, which is alphabetical, still failed — the
    bug was entirely about that order.
    """
    settings = _settings(tmp, preset)
    store.write_index(
        settings,
        {
            "presets": [
                {"preset": name, "label": name, "node_count": count}
                for name, count in sorted(presets)
            ]
        },
    )
    return settings


def test_the_fixture_really_is_in_alphabetical_order(tmp_path: Path) -> None:
    """Control: without this the cases below prove nothing.

    If the fixture ever stopped being alphabetical, every case here would
    pass on an ordering the job never produces.
    """
    settings = _index(tmp_path, [("MediumFast", 40), ("LongFast", 900)])
    written = store.read_index(settings)
    assert written is not None
    names = [item["preset"] for item in written["presets"]]
    assert names == ["LongFast", "MediumFast"], names
    assert names[0] != settings.default_preset, "the fixture does not reproduce the bug"


def test_the_gaps_page_opens_on_the_deployments_preset(tmp_path: Path) -> None:
    """The reported bug, as the reader met it.

    LongFast is both alphabetically first AND the busiest here, so this
    fails for the original reason and for the busiest-first reasoning
    that preceded it.
    """
    settings = _index(tmp_path, [("LongFast", 900), ("MediumFast", 40)])
    preset, reason = _resolve(None, settings)
    assert reason is None
    assert preset == "MediumFast", f"the gaps page opened on {preset}"


def test_the_picker_offers_it_first_too(tmp_path: Path) -> None:
    """Selected and first are different things, and both matter.

    A picker that selects MediumFast while listing LongFast at the top
    reads as though the page had overridden the reader's mesh.
    """
    settings = _index(tmp_path, [("LongFast", 900), ("MediumFast", 40), ("ShortFast", 5)])
    offered = [item["preset"] for item in _presets(settings)]
    assert offered[0] == "MediumFast", offered


def test_the_rest_follow_by_node_count(tmp_path: Path) -> None:
    """After the preferred one, busiest first — the old behaviour kept.

    Only the lead changed. Dropping the node-count sort would have put
    the remaining presets in alphabetical order, which is the accident
    this fix removes.
    """
    # Counts chosen so by-count and alphabetical DISAGREE. The first
    # version of this case used 900/40/300, where both orderings give the
    # same answer -- so deleting the node-count sort left it passing. The
    # mutation check found that, not the test.
    settings = _index(tmp_path, [("LongFast", 5), ("MediumFast", 40), ("ShortFast", 900)])
    offered = [item["preset"] for item in _presets(settings)]
    assert offered == ["MediumFast", "ShortFast", "LongFast"], offered


def test_a_preferred_preset_nobody_assessed_does_not_win(tmp_path: Path) -> None:
    """#177's fallback, and it matters more than the preference.

    A preferred preset absent from the index would put an EMPTY page in
    front of somebody. Falling back to the busiest is the old behaviour
    and a real answer.
    """
    # Again chosen so busiest and alphabetically-first differ: ShortFast
    # is the busiest, LongFast sorts first. Getting LongFast here would
    # mean the fallback is the old accident rather than a real choice.
    settings = _index(tmp_path, [("LongFast", 5), ("ShortFast", 900)], preset="MediumFast")
    preset, reason = _resolve(None, settings)
    assert reason is None
    assert preset == "ShortFast", f"fell back to {preset} rather than the busiest"


def test_another_deployment_gets_its_own_preset(tmp_path: Path) -> None:
    """The reason #177 made this a setting and not a constant.

    A mesh running LongFast must not have to patch code, which is also
    why the dead `DEFAULT_PRESET_KEY = "LONG_FAST"` constant was removed
    rather than corrected: a constant beside a setting is a second
    answer to one question.
    """
    settings = _index(tmp_path, [("LongFast", 10), ("MediumFast", 900)], preset="LongFast")
    preset, _ = _resolve(None, settings)
    assert preset == "LongFast"


def test_an_explicit_channel_still_wins(tmp_path: Path) -> None:
    """The preference is a default, not an override.

    A reader who picked a preset, or opened a link naming one, must get
    that one. This is the non-regression half: a fix that always
    returned the preferred preset would satisfy every case above.
    """
    settings = _index(tmp_path, [("LongFast", 900), ("MediumFast", 40)])
    preset, reason = _resolve("LongFast", settings)
    assert reason is None
    assert preset == "LongFast"


def test_a_channel_that_names_no_preset_is_still_refused(tmp_path: Path) -> None:
    """Weather rides on top of a preset and names none (AGENTS.md 9.7).

    Guarding this because the change touched the same function: falling
    back to the default here would describe a radio setting nobody is
    using.
    """
    settings = _index(tmp_path, [("MediumFast", 40)])
    preset, reason = _resolve("Weather", settings)
    assert preset is None
    assert reason == "not_a_preset"


def test_no_assessment_at_all_is_reported_not_guessed(tmp_path: Path) -> None:
    settings = _index(tmp_path, [])
    preset, reason = _resolve(None, settings)
    assert preset is None
    assert reason == "no_assessment"


def test_both_routes_agree_because_they_share_one_sort(tmp_path: Path) -> None:
    """The durable half of this fix.

    The gaps page and the leaderboards disagreed because each had its own
    ordering and only one had been fixed. Holding them to the same answer
    is what stops that recurring.
    """
    settings = _index(tmp_path, [("LongFast", 900), ("MediumFast", 40), ("ShortFast", 5)])
    assert _assessed_presets(settings) == [item["preset"] for item in _presets(settings)]
