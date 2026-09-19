"""Tests for the coverage site sets.

A run publishes the infrastructure map always, and a wider map that
includes the nodes which repeat traffic when a deployment turns it on.

Each guard here is tested in the state it exists to refuse, not only in
the state where it passes. See `AGENTS.md` 9.
"""

import inspect

import pytest

from sonoran.radio.overrides import EMPTY as EMPTY_OVERRIDES
from sonoran.roles import (
    EXTENDED_ROLES,
    INFRASTRUCTURE_ROLES,
    REPEATING_CLIENT_ROLES,
    SITE_SET_DIAGNOSTIC,
    SITE_SET_EXTENDED,
    SITE_SET_INFRASTRUCTURE,
    SITE_SET_KEYS,
    SITE_SET_LABELS,
    SITE_SET_ROLES,
    is_diagnostic_role_set,
    is_site_role,
    site_set_roles,
)


class TestWhichRolesRepeat:
    """Membership is quoted from the firmware, never inferred."""

    def test_the_infrastructure_set_is_unchanged(self) -> None:
        assert SITE_SET_ROLES[SITE_SET_INFRASTRUCTURE] == INFRASTRUCTURE_ROLES
        assert INFRASTRUCTURE_ROLES == {"ROUTER", "ROUTER_LATE", "REPEATER"}

    def test_the_extended_set_adds_the_roles_that_repeat(self) -> None:
        assert REPEATING_CLIENT_ROLES == {"CLIENT", "CLIENT_BASE", "ROUTER_CLIENT"}
        assert EXTENDED_ROLES == INFRASTRUCTURE_ROLES | REPEATING_CLIENT_ROLES

    def test_client_mute_is_never_a_site(self) -> None:
        """The proto: "Device that does not forward packets from other devices"."""
        assert "CLIENT_MUTE" not in EXTENDED_ROLES
        assert not is_site_role("CLIENT_MUTE", EXTENDED_ROLES)

    @pytest.mark.parametrize(
        "role",
        [
            "CLIENT_MUTE",  # states outright that it does not forward
            "CLIENT_HIDDEN",  # rebroadcasts local-only, and its point is not being seen
            "TRACKER",  # mobile by definition
            "TAK_TRACKER",  # mobile by definition
            "SENSOR",  # the proto never says it forwards for others
            "TAK",  # the proto never says it forwards for others
            "LOST_AND_FOUND",  # the proto never says it forwards for others
        ],
    )
    def test_a_role_that_does_not_carry_coverage_is_left_out(self, role: str) -> None:
        assert role not in EXTENDED_ROLES
        assert not is_site_role(role, EXTENDED_ROLES)

    @pytest.mark.parametrize("role", ["CLIENT", "CLIENT_BASE", "ROUTER_CLIENT"])
    def test_a_repeating_client_is_a_site_only_in_the_extended_set(self, role: str) -> None:
        assert is_site_role(role, EXTENDED_ROLES)
        assert not is_site_role(role, INFRASTRUCTURE_ROLES)

    def test_a_null_role_is_never_a_site_in_either_set(self) -> None:
        """AGENTS.md 9.22: NULL is a client or an unintroduced node."""
        assert not is_site_role(None, INFRASTRUCTURE_ROLES)
        assert not is_site_role(None, EXTENDED_ROLES)


class TestSiteSetLookup:
    def test_each_set_has_a_label(self) -> None:
        for key in SITE_SET_ROLES:
            assert SITE_SET_LABELS.get(key)

    def test_a_known_set_gives_its_roles(self) -> None:
        assert site_set_roles(SITE_SET_EXTENDED) == EXTENDED_ROLES

    @pytest.mark.parametrize("name", ["", "ALL", "clients", "Infrastructure", "../etc"])
    def test_an_unknown_set_fails_to_the_narrow_answer(self, name: str) -> None:
        """A typo must never widen a map. `parse_site_roles` fails the same way."""
        assert site_set_roles(name) == INFRASTRUCTURE_ROLES


class TestTheEmbedCanNeverWiden:
    """AGENTS.md 9.25. A client node is usually somebody's house."""

    def test_the_extended_set_is_diagnostic(self) -> None:
        """Which is what stops `/api/embed/coverage` serving it."""
        assert is_diagnostic_role_set(EXTENDED_ROLES) is True
        assert is_diagnostic_role_set(INFRASTRUCTURE_ROLES) is False

    def test_the_public_page_asks_for_the_infrastructure_tiles_only(self) -> None:
        """The site set is not in the public tile URL at all.

        It used to be a constant in this file, on the dashboard's tile
        route. That constrained an honest browser and nothing else: the
        route took the set from the path, carried no `EMBED_ENABLED`
        dependency, and answered for `extended` to anybody who typed
        it. The lock is now the route, which serves the infrastructure
        map and has nowhere to be told otherwise, and this is the
        strictly stronger property.

        `tests/unit/test_embed.py` pins the route itself.
        """
        from pathlib import Path

        source = Path("src/sonoran/web/static/embed-coverage.js").read_text(encoding="utf-8")
        assert "/api/embed/tiles/" in source
        # Not the dashboard's route, which serves every site set.
        assert "/api/coverage/tiles/" not in source
        # And no site set named anywhere in the URL it builds.
        assert "${SITE_SET}" not in source
        # It must not take the set from the summary it was given either.
        assert "summary.site_sets" not in source
        assert "state.siteSet" not in source


class TestTilePathsKeepTheSetsApart:
    def test_the_site_set_is_part_of_the_path(self) -> None:
        from pathlib import Path as FsPath

        from sonoran.coverage.store import tile_path

        root = FsPath("/tmp/run")
        infra = tile_path(root, "LongFast", "infrastructure", "usable", 6, 12, 25)
        wide = tile_path(root, "LongFast", "extended", "usable", 6, 12, 25)
        assert infra != wide
        assert infra.parts[-5] == "infrastructure"
        assert wide.parts[-5] == "extended"

    def test_two_sets_cannot_share_a_tile(self) -> None:
        """The whole point: they are different answers to different questions."""
        from pathlib import Path as FsPath

        from sonoran.coverage.store import tile_path

        seen = {
            tile_path(FsPath("/r"), "LongFast", key, "usable", 6, 12, 25) for key in SITE_SET_ROLES
        }
        assert len(seen) == len(SITE_SET_ROLES)


class TestThePlan:
    """What a run decides to build, before it builds anything."""

    def _settings(self, **kwargs: object) -> object:
        from sonoran.config import Settings

        return Settings(**kwargs)  # type: ignore[arg-type]

    def test_one_map_by_default(self) -> None:
        from sonoran.jobs.coverage import _plans

        settings = self._settings()
        assert settings.coverage_include_clients is False  # type: ignore[attr-defined]
        plans = _plans(settings, [], EMPTY_OVERRIDES, None)  # type: ignore[arg-type]
        assert [plan.key for plan in plans] == [SITE_SET_INFRASTRUCTURE]

    def test_both_maps_when_clients_are_included(self) -> None:
        from sonoran.jobs.coverage import _plans

        settings = self._settings(coverage_include_clients=True)
        plans = _plans(settings, [], EMPTY_OVERRIDES, None)  # type: ignore[arg-type]
        assert [plan.key for plan in plans] == [SITE_SET_INFRASTRUCTURE, SITE_SET_EXTENDED]

    def test_the_infrastructure_plan_is_always_first(self) -> None:
        """`_build` reports the first plan at the top level of the manifest.

        A reader who takes `presets` without asking for a site set must
        get the narrow answer, and the embed is that reader.
        """
        from sonoran.jobs import coverage

        source = inspect.getsource(coverage._build)
        assert "plans[0]" in source
        assert "presets=summaries" in source

    def test_a_deployment_role_set_still_drives_the_first_plan(self) -> None:
        """COVERAGE_SITE_ROLES=ALL must behave exactly as it did."""
        from sonoran.jobs.coverage import _plans

        settings = self._settings(coverage_site_roles="ALL")
        plans = _plans(settings, [], EMPTY_OVERRIDES, None)  # type: ignore[arg-type]
        assert plans[0].allowed is None
        assert is_diagnostic_role_set(plans[0].allowed) is True

    def test_a_diagnostic_run_is_not_written_under_the_infrastructure_name(self) -> None:
        """The site set is part of the tile path, so the path must not lie.

        `COVERAGE_SITE_ROLES=ALL` used to be keyed `infrastructure`
        whatever it predicted from, so a directory named for routers and
        repeaters held a footprint around every client node in region.
        The manifest said `is_diagnostic`, and the tiles are what a
        reader fetches. See `AGENTS.md` 9.25.
        """
        from sonoran.jobs.coverage import _plans

        settings = self._settings(coverage_site_roles="ALL", coverage_include_clients=True)
        plans = _plans(settings, [], EMPTY_OVERRIDES, None)  # type: ignore[arg-type]
        assert [plan.key for plan in plans] == [SITE_SET_DIAGNOSTIC, SITE_SET_EXTENDED]
        assert plans[0].label

    @pytest.mark.parametrize("roles", ["", "ROUTER", "ROUTER,REPEATER,ROUTER_LATE"])
    def test_a_set_that_cannot_add_a_personal_node_keeps_the_name(self, roles: str) -> None:
        """A subset of the infrastructure roles is still the public map."""
        from sonoran.jobs.coverage import _plans

        settings = self._settings(coverage_site_roles=roles)
        plans = _plans(settings, [], EMPTY_OVERRIDES, None)  # type: ignore[arg-type]
        assert plans[0].key == SITE_SET_INFRASTRUCTURE

    def test_the_diagnostic_name_is_servable_without_being_a_role_set(self) -> None:
        """The dashboard has to be able to fetch a diagnostic tile.

        `SITE_SET_ROLES` answers which roles a set predicts from, and
        the diagnostic set has no fixed answer: it is whatever
        `COVERAGE_SITE_ROLES` said. So the path allowlist is its own
        name, and serving a tile is never a reason to widen the roles.
        """
        assert SITE_SET_DIAGNOSTIC in SITE_SET_KEYS
        assert SITE_SET_DIAGNOSTIC not in SITE_SET_ROLES
        assert SITE_SET_KEYS >= set(SITE_SET_ROLES)
        assert SITE_SET_LABELS.get(SITE_SET_DIAGNOSTIC)


class TestTheDashboardLabelsWhatItShows:
    """A map drawn from client nodes must never say it came from routers."""

    def _source(self) -> str:
        from pathlib import Path

        return Path("src/sonoran/web/static/coverage.js").read_text(encoding="utf-8")

    def test_the_notice_follows_the_chosen_site_set(self) -> None:
        source = self._source()
        assert "function shownIsDiagnostic()" in source
        # It must consider the chosen set, not only the whole run. The
        # run stays non-diagnostic while the wider view inside it is
        # diagnostic, so reading the run alone would label nothing.
        assert "set && set.is_diagnostic" in source
        assert "shownIsDiagnostic()" in source.split("function diagnosticNotice()")[1]

    def test_the_subtitle_follows_the_chosen_site_set(self) -> None:
        source = self._source()
        banner = source.split("function drawDiagnosticBanner(")[1].split("function ")[0]
        assert "shownIsDiagnostic()" in banner
        assert "shownRoles()" in banner
        # The old code read the run's flag straight off the summary.
        assert "summary.is_diagnostic\n" not in banner

    def test_the_tile_url_carries_the_chosen_site_set(self) -> None:
        assert "${currentSiteSet()}" in self._source()

    def test_the_picker_hides_itself_when_there_is_one_set(self) -> None:
        """A control that cannot change anything is worse than none."""
        source = self._source()
        block = source.split("function drawSiteSets(")[1].split("function ")[0]
        assert "sets.length < 2" in block
        assert "wrap.hidden = true" in block


class TestTheNavIcon:
    """Every page in the sidebar shows an icon."""

    def _html(self) -> str:
        from pathlib import Path

        return Path("src/sonoran/web/static/index.html").read_text(encoding="utf-8")

    def _nav(self) -> str:
        """The nav element, found by its tag rather than by one attribute.

        This used to split on the literal `<nav aria-label=`, so adding
        an `id` to the element for the phone menu button to point
        `aria-controls` at broke both tests below with an IndexError
        rather than with anything about icons.
        """
        import re

        match = re.search(r"<nav\b[^>]*>(.*?)</nav>", self._html(), re.S)
        assert match, "no nav element found"
        return match.group(1)

    def test_every_nav_link_uses_the_icon_class(self) -> None:
        """`.sprite` is `display: none`. It hides the sprite sheet, and it
        hid the coverage icon for as long as the link carried it."""
        import re

        links = re.findall(r"<a href=\"#[^\"]+\"[^>]*>(.*?)</a>", self._nav(), re.S)
        assert links, "no nav links found"
        for link in links:
            assert 'class="icon"' in link, link.strip()[:80]
            assert 'class="sprite"' not in link, link.strip()[:80]

    def test_every_nav_icon_names_a_symbol_that_exists(self) -> None:
        import re

        html = self._html()
        defined = set(re.findall(r'<symbol id="(i-[a-z-]+)"', html))
        used = set(re.findall(r'<use href="#(i-[a-z-]+)"', self._nav()))
        assert used, "no nav icons found"
        assert used <= defined, f"missing symbols: {sorted(used - defined)}"

    def test_the_menu_button_names_symbols_that_exist(self) -> None:
        """The phone nav button swaps its own icon in JavaScript.

        `wireNav` writes `#i-menu` and `#i-menu-close` straight into the
        `use` element, so neither name appears in the markup beside the
        other icons and the test above cannot see them. A symbol that is
        only ever named from a script is exactly the one that goes
        missing quietly: the button simply draws nothing.
        """
        import re
        from pathlib import Path

        defined = set(re.findall(r'<symbol id="(i-[a-z-]+)"', self._html()))
        script = Path("src/sonoran/web/static/app.js").read_text(encoding="utf-8")
        block = script.split("function wireNav(")[1].split("\n}\n")[0]
        used = set(re.findall(r"'#(i-[a-z-]+)'", block))
        assert used, "the menu button names no icon"
        assert used <= defined, f"missing symbols: {sorted(used - defined)}"


class TestTheDefaultPreset:
    """The page opens on the preset the mesh actually runs."""

    def _source(self) -> str:
        from pathlib import Path

        return Path("src/sonoran/web/static/coverage.js").read_text(encoding="utf-8")

    def test_the_default_is_the_busiest_preset_not_the_first(self) -> None:
        """The manifest lists presets in name order.

        Taking the first gave "Long fast" on a mesh whose backbone is
        all on "Medium fast", so the page opened on a nearly empty map
        of a preset nobody uses. Seen on the live preview: Long fast (1)
        was chosen over Medium fast (3).
        """
        source = self._source()
        assert "function busiestPreset(" in source
        assert "state.preset = busiestPreset(summary);" in source
        # And not the old behaviour at the call site. `busiestPreset`
        # itself ends in `presets[0].preset`, after it has sorted them,
        # so the string alone is not the thing to test for.
        assert "presets.length ? presets[0].preset : null" not in source

    def test_it_ranks_by_sites_then_candidates_then_name(self) -> None:
        source = self._source()
        block = source.split("function busiestPreset(")[1].split("\n  }")[0]
        assert "site_count" in block
        # A tie on sites falls to candidates, so a preset with nodes and
        # no usable site still beats one with nothing at all.
        assert "candidate_count" in block
        # And the last tie-break keeps the choice stable between redraws.
        assert "localeCompare" in block
