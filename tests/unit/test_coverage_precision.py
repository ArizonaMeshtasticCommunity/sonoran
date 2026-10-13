"""The coverage map predicts from precise positions only (#315).

Logan's #318 let a host predict from positions rounded to 13 bits, and
s.azmsh.dev did. Logan and Tyler then asked for that to stop: a
footprint drawn from a rounded point can sit in the wrong valley, and
the compute is spent on an answer nobody can use. Will decided on
2026-10-08 to follow them. See `docs/DECISIONS.md`.

So:

- Every published map predicts from precise positions. A setting below
  16 bits is raised to 16, because the stale value is still in a
  `.env` somewhere.
- An operator position in the overrides file makes a rounded router a
  site, at the operator's position.
- A host may also publish an approximate map, as its own site set,
  with `COVERAGE_INCLUDE_APPROXIMATE`. Off by default. The public embed
  never reads it.
"""

import logging
import re
from pathlib import Path

import pytest

from sonoran.config import Settings
from sonoran.db.models import Node
from sonoran.jobs import coverage
from sonoran.positions import (
    APPROXIMATE_SITE_PRECISION_BITS,
    MIN_SITE_PRECISION_BITS,
    SITE_PRECISION_APPROXIMATE,
    SITE_PRECISION_PRECISE,
    precise_minimum_bits,
    site_minimum_bits,
)
from sonoran.radio.overrides import parse_overrides
from sonoran.roles import (
    SITE_SET_EXTENDED,
    SITE_SET_INFRASTRUCTURE,
    SITE_SET_KEYS,
    approximate_site_set,
    is_approximate_site_set,
)


def _settings(tmp_path: Path, **extra: object) -> Settings:
    return Settings(
        _env_file=None,
        coverage_cache_dir=str(tmp_path / "coverage"),
        landcover_cache_dir=str(tmp_path / "landcover"),
        **extra,  # type: ignore[arg-type]
    )


def _node(node_num: int, bits: int | None, role: str = "ROUTER_LATE") -> Node:
    return Node(
        node_num=node_num,
        node_id=f"!{node_num:08x}",
        long_name=f"Node {node_num}",
        role=role,
        last_channel="MediumFast",
        last_lat=34.2098,
        last_lon=-112.3811,
        last_position_precision_bits=bits,
    )


# --- the rule ----------------------------------------------------------


def test_precise_is_sixteen_bits_and_cannot_be_lowered() -> None:
    """13 on the box was the opt-in #318 documented. It no longer works."""
    assert MIN_SITE_PRECISION_BITS == 16
    assert precise_minimum_bits(16) == 16
    assert precise_minimum_bits(13) == 16
    assert precise_minimum_bits(1) == 16


def test_precise_can_still_be_raised_or_turned_off() -> None:
    """Zero is the private broker case, which has its own test."""
    assert precise_minimum_bits(18) == 18
    assert precise_minimum_bits(0) == 0


def test_approximate_reaches_down_to_its_own_floor() -> None:
    assert APPROXIMATE_SITE_PRECISION_BITS == 13
    assert site_minimum_bits(SITE_PRECISION_PRECISE, 16, 13) == 16
    assert site_minimum_bits(SITE_PRECISION_APPROXIMATE, 16, 13) == 13
    # Never stricter than the precise map: it is the precise map and more.
    assert site_minimum_bits(SITE_PRECISION_APPROXIMATE, 16, 20) == 16
    assert site_minimum_bits(SITE_PRECISION_APPROXIMATE, 0, 13) == 0


def test_an_unknown_precision_is_refused() -> None:
    with pytest.raises(ValueError):
        site_minimum_bits("roughly", 16, 13)


# --- site selection ----------------------------------------------------


def test_a_rounded_router_is_not_a_site_even_where_the_setting_says_13(tmp_path: Path) -> None:
    """Towers 2, as s.azmsh.dev runs it today."""
    settings = _settings(tmp_path, coverage_min_precision_bits=13)
    rounded, exact = _node(1, 13), _node(2, None)
    groups, left_out, coarse = coverage.group_by_preset(
        settings, [rounded, exact], parse_overrides("")
    )
    assert [site.node_num for site in groups["MEDIUM_FAST"]] == [2]
    assert left_out["MEDIUM_FAST"][coverage.COARSE_POSITION] == 1
    assert [item["node_id"] for item in coarse] == ["!00000001"]


def test_the_approximate_rule_takes_the_rounded_router_and_says_so(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    rounded, exact, coarser = _node(1, 13), _node(2, None), _node(3, 12)
    groups, left_out, _ = coverage.group_by_preset(
        settings,
        [rounded, exact, coarser],
        parse_overrides(""),
        precision=SITE_PRECISION_APPROXIMATE,
    )
    by_num = {site.node_num: site for site in groups["MEDIUM_FAST"]}
    assert set(by_num) == {1, 2}
    assert by_num[1].position_deviation_m == 2900.0
    assert by_num[2].position_deviation_m is None
    # 12 bits is 5.8 km, past even the approximate floor.
    assert left_out["MEDIUM_FAST"][coverage.COARSE_POSITION] == 1


def test_an_operator_position_makes_a_rounded_router_a_precise_site(tmp_path: Path) -> None:
    overrides = parse_overrides(
        'nodes:\n  "!00000001":\n    latitude: 34.2\n    longitude: -112.4\n'
        "    antenna_height_m: 20.0\n"
    )
    groups, left_out, coarse = coverage.group_by_preset(
        _settings(tmp_path), [_node(1, 13)], overrides
    )
    (site,) = groups["MEDIUM_FAST"]
    assert (site.latitude, site.longitude) == (34.2, -112.4)
    assert site.profile.antenna_height_m == 20.0
    assert site.position_deviation_m is None
    assert site.position_source == coverage.POSITION_OPERATOR
    assert coverage.COARSE_POSITION not in left_out["MEDIUM_FAST"]
    assert coarse == []


def test_a_reported_position_says_it_was_reported(tmp_path: Path) -> None:
    groups, _, _ = coverage.group_by_preset(
        _settings(tmp_path), [_node(2, None)], parse_overrides("")
    )
    (site,) = groups["MEDIUM_FAST"]
    assert site.position_source == coverage.POSITION_REPORTED


@pytest.mark.parametrize("role", ["CLIENT", "CLIENT_MUTE", "CLIENT_BASE", None])
def test_an_operator_position_never_makes_a_client_a_public_site(
    tmp_path: Path, role: str | None
) -> None:
    """An override places a node. It never says what the node is.

    The infrastructure map is the only one the public embed serves, so
    a client given a position must still be left out of it, by role.
    """
    overrides = parse_overrides(
        'nodes:\n  "!00000001":\n    latitude: 34.2\n    longitude: -112.4\n'
    )
    node = _node(1, None, role=role)  # type: ignore[arg-type]
    plans = coverage._plans(
        _settings(tmp_path, coverage_include_approximate=True), [node], overrides, None
    )
    infrastructure = plans[0]
    assert infrastructure.key == SITE_SET_INFRASTRUCTURE
    assert infrastructure.groups == {}
    assert sum(infrastructure.left_out["MEDIUM_FAST"].values()) == 1
    assert coverage.COARSE_POSITION not in infrastructure.left_out["MEDIUM_FAST"]


# --- the plans a run builds -------------------------------------------


def test_with_the_flag_off_a_run_builds_exactly_what_it_built_before(tmp_path: Path) -> None:
    """The compute cost must not move for a host that does not ask."""
    nodes = [_node(1, 13), _node(2, None)]
    plans = coverage._plans(_settings(tmp_path), nodes, parse_overrides(""), None)
    assert [plan.key for plan in plans] == [SITE_SET_INFRASTRUCTURE]
    assert plans[0].precision == SITE_PRECISION_PRECISE

    with_clients = coverage._plans(
        _settings(tmp_path, coverage_include_clients=True), nodes, parse_overrides(""), None
    )
    assert [plan.key for plan in with_clients] == [SITE_SET_INFRASTRUCTURE, SITE_SET_EXTENDED]


def test_the_flag_adds_an_approximate_map_after_every_precise_one(tmp_path: Path) -> None:
    nodes = [_node(1, 13), _node(2, None)]
    plans = coverage._plans(
        _settings(tmp_path, coverage_include_approximate=True, coverage_include_clients=True),
        nodes,
        parse_overrides(""),
        None,
    )
    assert [plan.key for plan in plans] == [
        SITE_SET_INFRASTRUCTURE,
        SITE_SET_EXTENDED,
        "infrastructure_approximate",
        "extended_approximate",
    ]
    by_key = {plan.key: plan for plan in plans}
    # The first plan is what the manifest and the embed report. Precise.
    assert plans[0].precision == SITE_PRECISION_PRECISE
    assert [site.node_num for site in plans[0].groups["MEDIUM_FAST"]] == [2]
    approximate = by_key["infrastructure_approximate"]
    assert approximate.precision == SITE_PRECISION_APPROXIMATE
    assert {site.node_num for site in approximate.groups["MEDIUM_FAST"]} == {1, 2}


def test_the_manifest_marks_an_approximate_map(tmp_path: Path) -> None:
    plans = coverage._plans(
        _settings(tmp_path, coverage_include_approximate=True),
        [_node(1, 13)],
        parse_overrides(""),
        None,
    )
    precise, approximate = (coverage._site_set_summary(plan, []) for plan in plans)
    assert precise.site_precision == SITE_PRECISION_PRECISE
    assert precise.approximate is False
    assert approximate.site_precision == SITE_PRECISION_APPROXIMATE
    assert approximate.approximate is True
    assert approximate.label.startswith("Routers and repeaters")
    assert approximate.label != precise.label


def test_a_lowered_setting_is_named_in_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A host that set 13 must be told why its map shrank."""
    with caplog.at_level(logging.WARNING):
        coverage._plans(
            _settings(tmp_path, coverage_min_precision_bits=13), [], parse_overrides(""), None
        )
    assert "COVERAGE_MIN_PRECISION_BITS" in caplog.text
    assert "COVERAGE_INCLUDE_APPROXIMATE" in caplog.text


# --- the names ---------------------------------------------------------


def test_every_approximate_set_may_be_a_tile_path() -> None:
    """The dashboard tile route takes `^[a-z_]{1,32}$` and SITE_SET_KEYS."""
    for base in (SITE_SET_INFRASTRUCTURE, SITE_SET_EXTENDED, "diagnostic"):
        key = approximate_site_set(base)
        assert key in SITE_SET_KEYS
        assert re.fullmatch(r"[a-z_]{1,32}", key), key
        assert is_approximate_site_set(key)
        assert not is_approximate_site_set(base)


def test_an_approximate_set_is_never_called_infrastructure() -> None:
    """The public tile route reads `SITE_SET_INFRASTRUCTURE` off the path."""
    assert approximate_site_set(SITE_SET_INFRASTRUCTURE) != SITE_SET_INFRASTRUCTURE


def test_no_page_reads_an_operator_position() -> None:
    """An operator position places a coverage site and nothing else.

    The API and the embed read the overrides file for radio facts. If
    one of them read the position, the map or the node page would move
    the node, and the public markers could show where its owner's
    equipment really is.
    """
    source = Path(__file__).parents[2] / "src/sonoran"
    readers = [
        path.relative_to(source).as_posix()
        for folder in ("api", "embed", "web")
        for path in (source / folder).rglob("*.py")
        if "position_of(" in path.read_text(encoding="utf-8")
    ]
    assert readers == []
