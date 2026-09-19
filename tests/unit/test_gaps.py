"""The coverage gap signals, and the rules they must never break.

Every test here builds its evidence by hand and asserts **the rule**,
not the number. A test that pins a threshold would pass for ever and
prove nothing: the thresholds are starting points that
`docs/design/coverage-gaps.md` 11.1 says to measure on live data.
"""

import inspect
from pathlib import Path

from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.config import Settings
from sonoran.gaps import signals
from sonoran.gaps.signals import BAD, OK, UNKNOWN, CoverageLevels, NodeEvidence
from sonoran.radio.presets import PRESETS, noise_floor_dbm, preset_by_key, required_snr_db

LONG_FAST = preset_by_key("LONG_FAST")
assert LONG_FAST is not None

STATIC = Path(__file__).parent.parent.parent / "src" / "sonoran" / "web" / "static"


def _routes(app: object) -> list[tuple[str, set[str]]]:
    """Return every (path, methods) pair an app really serves.

    `include_router` does not flatten its routes into `app.routes` in
    this version of FastAPI: it appends one `_IncludedRouter` wrapper
    whose `path` is None and whose `original_router` holds the real
    routes. A test that walks `app.routes` and reads `path` therefore
    sees nothing at all and passes without asserting anything. Anything
    that must enumerate the API has to recurse.
    """
    found: list[tuple[str, set[str]]] = []
    stack = list(getattr(app, "routes", []))
    while stack:
        route = stack.pop()
        included = getattr(route, "original_router", None)
        if included is not None:
            stack.extend(getattr(included, "routes", []))
            continue
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if isinstance(path, str) and methods:
            found.append((path, set(methods)))
    return found


def _settings(**extra: object) -> Settings:
    return Settings(_env_file=None, **extra)  # type: ignore[arg-type]


# --------------------------------------------------------------- 4.5


def test_required_snr_is_derived_from_the_one_preset_table() -> None:
    """Every preset's required SNR is sensitivity minus its noise floor.

    It is derived and never tabulated a second time. A second table of
    the same nine figures would drift from the first, which is why
    `radio/presets.py` is the only preset table in the Python code.
    """
    for preset in PRESETS:
        assert required_snr_db(preset) == preset.sensitivity_dbm - noise_floor_dbm(preset)


def test_long_fast_demodulates_well_below_the_noise() -> None:
    """Long fast needs about -25 dB, which is why -20 dB is a real link.

    This is the number the whole margin rests on. A reader who does not
    know it reads a reported SNR of -20 dB as a broken radio, when in
    fact it has about 5 dB to spare.
    """
    assert -25.5 < required_snr_db(LONG_FAST) < -24.5


def test_a_weak_margin_is_measured_against_the_preset_not_the_raw_snr() -> None:
    """The same SNR is a different answer on two presets."""
    settings = _settings()
    weak = signals.weak_best_link(
        NodeEvidence(node_num=1, best_neighbour_snr=-20.0), settings, LONG_FAST
    )
    assert weak.state == BAD
    # It works, and it has little room. Both halves are true.
    assert weak.value is not None and 4.0 < weak.value < 5.0

    strong = signals.weak_best_link(
        NodeEvidence(node_num=1, best_neighbour_snr=-5.0), settings, LONG_FAST
    )
    assert strong.state == OK


def test_no_measured_reading_is_unknown_and_never_ok() -> None:
    """An ordinary packet carries no reading that belongs to its sender."""
    found = signals.weak_best_link(NodeEvidence(node_num=1, packets=500), _settings(), LONG_FAST)
    assert found.state == UNKNOWN
    assert found.reason == "no_measured_snr"
    assert found.value is None


def test_a_self_upload_reading_never_becomes_a_margin() -> None:
    """`best_snr_db` reads only the three measured sources.

    A self upload is the node's own voice and a relayed observation
    belongs to the last hop. Neither is in `NodeEvidence` at all, because
    the query excludes them, and this asserts the shape that keeps it so:
    the only SNR fields are a neighbour report, a traceroute hop, and a
    direct observation by another node. See `AGENTS.md` 9.5 and 9.5.1.
    """
    fields = {name for name in NodeEvidence.__dataclass_fields__ if "snr" in name}
    assert fields == {"best_direct_snr", "best_neighbour_snr", "best_trace_snr"}
    assert NodeEvidence(node_num=1).best_snr_db is None


# --------------------------------------------------------------- 4.1


def test_a_node_that_is_not_a_gateway_can_never_be_radio_isolated() -> None:
    """Its packets could only have reached us because a radio heard them.

    This is the load-bearing fact read backwards, and it removes most of
    the mesh from the signal at no cost.
    """
    found = signals.radio_isolated(
        NodeEvidence(node_num=1, packets=400, is_mqtt_gateway=False), _settings(), 31
    )
    assert found.state == OK
    assert found.reason == "not_an_mqtt_gateway"


def test_a_gateway_no_radio_heard_is_bad_and_names_the_gateway_count() -> None:
    """The claim scales with how many gateways the mesh has.

    "None of the 31 gateways active this week heard it" is a fact a
    reader can weigh. "It is isolated" is a judgement. The evidence
    object carries the number so the page can say the first one.
    """
    found = signals.radio_isolated(
        NodeEvidence(node_num=1, packets=400, rf_packets=0, is_mqtt_gateway=True), _settings(), 31
    )
    assert found.state == BAD
    assert found.reason == "no_gateway_heard_it"
    assert found.evidence["gateways_active"] == 31
    said = found.as_dict()["sentence"]
    assert isinstance(said, str)
    assert "31" in said
    # The words matter. This is a measurement, not an accusation.
    assert "isolated" not in said.lower()


def test_one_packet_heard_by_another_node_clears_the_signal() -> None:
    """An upload by a different node is positive radio evidence."""
    found = signals.radio_isolated(
        NodeEvidence(node_num=1, packets=400, rf_packets=1, is_mqtt_gateway=True), _settings(), 31
    )
    assert found.state == OK


def test_a_neighbour_report_naming_the_node_clears_the_signal() -> None:
    """A real radio closed a link from it, which beats any upload."""
    found = signals.radio_isolated(
        NodeEvidence(node_num=1, packets=400, is_mqtt_gateway=True, named_as_neighbour=1),
        _settings(),
        31,
    )
    assert found.state == OK


def test_a_node_below_the_packet_floor_is_unknown_and_names_the_floor() -> None:
    """Nineteen packets against a floor of twenty is not a finding."""
    found = signals.radio_isolated(
        NodeEvidence(node_num=1, packets=19, is_mqtt_gateway=True), _settings(), 31
    )
    assert found.state == UNKNOWN
    assert found.reason == "too_few_packets"
    assert found.evidence["min_packets"] == 20
    said = found.as_dict()["sentence"]
    assert isinstance(said, str) and "20" in said


def test_a_node_with_no_packets_is_unknown_never_bad() -> None:
    """A node that reports nothing is usually switched off."""
    found = signals.radio_isolated(
        NodeEvidence(node_num=1, packets=0, is_mqtt_gateway=True), _settings(), 31
    )
    assert found.state == UNKNOWN


def test_every_packet_ambiguous_is_unknown_not_bad() -> None:
    """An MQTT rebroadcast is neither evidence nor a fault.

    Until the `via_mqtt` semantics can be quoted from the vendored proto
    and the hole measured on live data, such a packet counts for nothing
    in either direction. See the module docstring.
    """
    found = signals.radio_isolated(
        NodeEvidence(
            node_num=1, packets=40, rf_packets=0, ambiguous_packets=40, is_mqtt_gateway=True
        ),
        _settings(),
        31,
    )
    assert found.state == UNKNOWN
    assert found.reason == "every_packet_ambiguous"


# --------------------------------------------------------------- 4.2


def test_the_asymmetry_needs_both_halves_proven() -> None:
    """A working receiver and a transmitter no gateway hears.

    This is the only case in which this project will say a node cannot
    be heard, and both halves must be measured.
    """
    settings = _settings()
    evidence = NodeEvidence(
        node_num=1, packets=400, rf_packets=0, is_mqtt_gateway=True, neighbour_reports=4
    )
    isolated = signals.radio_isolated(evidence, settings, 31)
    found = signals.hears_but_is_not_heard(evidence, settings, 31, isolated)
    assert found.state == BAD
    said = found.as_dict()["sentence"]
    assert isinstance(said, str)
    # Both halves of the claim are named, which is what makes it honest.
    assert "receiver works" in said
    assert "31" in said


def test_without_neighbour_reports_the_asymmetry_is_unknown_never_ok() -> None:
    """Absence of neighbour reports is the NeighborInfo module being off.

    It says nothing at all about the radio, so this signal has no `ok`
    state to fall into.
    """
    settings = _settings()
    evidence = NodeEvidence(
        node_num=1, packets=400, rf_packets=0, is_mqtt_gateway=True, neighbour_reports=0
    )
    isolated = signals.radio_isolated(evidence, settings, 31)
    found = signals.hears_but_is_not_heard(evidence, settings, 31, isolated)
    assert found.state == UNKNOWN


def test_a_healthy_node_never_reads_ok_on_the_asymmetry() -> None:
    """The signal has exactly two states, and `ok` is not one of them."""
    settings = _settings()
    evidence = NodeEvidence(
        node_num=1, packets=400, rf_packets=400, is_mqtt_gateway=True, neighbour_reports=9
    )
    isolated = signals.radio_isolated(evidence, settings, 31)
    found = signals.hears_but_is_not_heard(evidence, settings, 31, isolated)
    assert found.state == UNKNOWN
    assert found.state != OK


# --------------------------------------------------------------- 4.3


def test_intermittency_counts_hours_and_not_packets() -> None:
    """One chatty hour must not decide the answer.

    Both nodes below sent the same 1000 packets. The first got out in a
    quarter of its hours and the second in nearly all of them. A ratio of
    packets would not tell them apart.
    """
    settings = _settings()
    flaky = signals.rf_intermittent(
        NodeEvidence(node_num=1, packets=1000, active_hours=100, rf_hours=25), settings
    )
    steady = signals.rf_intermittent(
        NodeEvidence(node_num=2, packets=1000, active_hours=100, rf_hours=95), settings
    )
    assert flaky.state == BAD
    assert steady.state == OK
    assert flaky.value == 0.25


def test_too_few_active_hours_is_unknown() -> None:
    """A ratio over three hours says nothing about a week."""
    found = signals.rf_intermittent(
        NodeEvidence(node_num=1, packets=60, active_hours=3, rf_hours=0), _settings()
    )
    assert found.state == UNKNOWN
    assert found.reason == "too_few_active_hours"


def test_a_node_with_no_hours_at_all_is_unknown() -> None:
    """No division by zero, and no `bad` from an empty record."""
    found = signals.rf_intermittent(NodeEvidence(node_num=1), _settings())
    assert found.state == UNKNOWN


# --------------------------------------------------------------- 4.4


def test_no_direct_observer_is_unknown_not_bad() -> None:
    """A well connected node three hops deep is heard directly by nobody.

    That is normal, and calling it a fault would flag most of the mesh.
    """
    found = signals.sole_observer(
        NodeEvidence(node_num=1, packets=400, direct_gateways=0), _settings()
    )
    assert found.state == UNKNOWN
    assert found.reason == "no_direct_observation"


def test_one_direct_gateway_is_named_as_instrumentation_not_redundancy() -> None:
    """The observer set is gateways, so this is a fact about our reach."""
    found = signals.sole_observer(
        NodeEvidence(node_num=1, packets=400, direct_gateways=1), _settings()
    )
    assert found.state == BAD
    said = found.as_dict()["sentence"]
    assert isinstance(said, str)
    assert "gateway" in said
    # It must not be sold as a single point of failure.
    assert "redundan" not in said.lower()
    assert "point of failure" not in said.lower()


def test_two_direct_gateways_is_ok() -> None:
    found = signals.sole_observer(
        NodeEvidence(node_num=1, packets=400, direct_gateways=2), _settings()
    )
    assert found.state == OK


def test_sole_observer_respects_the_packet_floor() -> None:
    found = signals.sole_observer(
        NodeEvidence(node_num=1, packets=5, direct_gateways=1), _settings()
    )
    assert found.state == UNKNOWN


# --------------------------------------------------------------- 4.6


def test_no_published_run_makes_the_prediction_unknown() -> None:
    """Missing is not outside. The page says why."""
    found = signals.outside_predicted_usable(1, CoverageLevels(), "exact", 0.0)
    assert found.state == UNKNOWN
    assert found.reason == "no_coverage_run"


def test_a_diagnostic_run_cannot_answer_the_prediction_signal() -> None:
    """A diagnostic predicts from client nodes that move.

    See `AGENTS.md` 9.25 and 9.27.
    """
    coverage = CoverageLevels(
        stamp="20260918T060000Z", available=True, is_diagnostic=True, threshold_level=61
    )
    found = signals.outside_predicted_usable(1, coverage, "exact", 0.0)
    assert found.state == UNKNOWN
    assert found.reason == "diagnostic_run"


def test_a_coarse_position_cannot_be_placed_on_a_ninety_metre_grid() -> None:
    """Thirteen bits is 2.9 km of doubt. Never inside, never outside."""
    coverage = CoverageLevels(stamp="s", available=True, threshold_level=61, levels={})
    found = signals.outside_predicted_usable(1, coverage, "coarse", 2900.0)
    assert found.state == UNKNOWN
    assert found.reason == "position_too_coarse"
    assert found.value == 2900.0


def test_a_node_absent_from_the_artefact_is_unknown_and_not_zero() -> None:
    """A node outside the region grid is simply not in the run."""
    coverage = CoverageLevels(stamp="s", available=True, threshold_level=61, levels={})
    found = signals.outside_predicted_usable(999, coverage, "exact", 0.0)
    assert found.state == UNKNOWN
    assert found.reason == "outside_run_region"


def test_a_stored_zero_is_bad_because_the_run_reached_that_cell() -> None:
    """Zero is `grid.NO_COVERAGE`: reached, and nothing found.

    This is the one place where zero and absent must not be confused.
    Absent means unknown; zero means the model looked and there was
    nothing there.
    """
    coverage = CoverageLevels(
        stamp="s", available=True, threshold_level=61, levels={"7": {"usable": 0}}
    )
    found = signals.outside_predicted_usable(7, coverage, "exact", 0.0)
    assert found.state == BAD
    assert found.reason == "outside_usable"


def test_a_level_above_the_threshold_is_inside() -> None:
    coverage = CoverageLevels(
        stamp="s", available=True, threshold_level=61, levels={"7": {"usable": 90}}
    )
    assert signals.outside_predicted_usable(7, coverage, "exact", 0.0).state == OK


def test_a_node_with_no_position_cannot_be_sampled() -> None:
    coverage = CoverageLevels(stamp="s", available=True, threshold_level=61)
    found = signals.outside_predicted_usable(7, coverage, "none", None)
    assert found.state == UNKNOWN
    assert found.reason == "no_usable_position"


def test_reached_but_unpredicted_is_a_finding_about_the_map() -> None:
    """A node the air reached, standing where the model predicts nothing.

    It says the prediction is pessimistic there. It is not a fault of
    the node, and it is counted separately for that reason.
    """
    coverage = CoverageLevels(
        stamp="s", available=True, threshold_level=61, levels={"7": {"usable": 10}}
    )
    evidence = NodeEvidence(node_num=7, packets=400, rf_packets=400)
    assessed = signals.assess(evidence, _settings(), LONG_FAST, 31, coverage, "exact", 0.0)
    assert signals.reached_but_unpredicted(assessed, evidence) is True

    silent = NodeEvidence(node_num=7, packets=400, rf_packets=0)
    assert signals.reached_but_unpredicted(assessed, silent) is False


# --------------------------------------------------------------- 4.8


def test_mobile_is_decided_by_how_far_the_positions_spread() -> None:
    settings = _settings()
    assert signals.is_mobile(NodeEvidence(node_num=1, position_spread_km=8.0), settings) is True
    assert signals.is_mobile(NodeEvidence(node_num=1, position_spread_km=0.05), settings) is False


def test_a_node_that_reported_one_position_is_not_mobile() -> None:
    """No spread is not a spread of zero, and neither is mobile."""
    assert (
        signals.is_mobile(NodeEvidence(node_num=1, position_spread_km=None), _settings()) is False
    )


# ---------------------------------------------------------- positions


def test_position_confidence_reads_the_three_cases() -> None:
    """A missing precision is exact, which is the ordinary radio case."""
    assert signals.position_confidence(33.4, -112.0, None, 16) == ("exact", None)
    assert signals.position_confidence(33.4, -112.0, 32, 16) == ("exact", 0.0)
    assert signals.position_confidence(33.4, -112.0, 13, 16) == ("coarse", 2900.0)
    assert signals.position_confidence(None, None, 32, 16) == ("none", None)
    # Null Island is not a place a node can be.
    assert signals.position_confidence(0.0, 0.0, 32, 16) == ("none", None)


# ------------------------------------------------------------ ranking


def test_the_worst_state_is_what_colours_a_row() -> None:
    """Bad beats unknown, and unknown beats ok. Never an average."""

    def sig(state: str) -> signals.Signal:
        return signals.Signal(state, "r")

    assert signals.worst_state({"a": sig(OK), "b": sig(UNKNOWN)}) == UNKNOWN
    assert signals.worst_state({"a": sig(BAD), "b": sig(UNKNOWN)}) == BAD
    assert signals.worst_state({"a": sig(OK), "b": sig(OK)}) == OK


def test_a_node_with_one_unknown_is_not_listed_as_healthy() -> None:
    """Unmeasured is a different answer from well connected."""
    assert signals.worst_state({"a": signals.Signal(UNKNOWN, "r")}) != OK


def test_the_ranking_is_counts_then_severity_then_evidence() -> None:
    """Three terms, no score.

    The second term is why: two nodes with one finding each sort by
    which finding it is, and the asymmetry outranks everything because it
    is the strongest thing this feature can prove.
    """
    asymmetric = {
        "node_id": "!a",
        "bad_count": 1,
        "packets": 10,
        "signals": {"hears_but_is_not_heard": {"state": BAD}},
    }
    thin = {
        "node_id": "!b",
        "bad_count": 1,
        "packets": 900,
        "signals": {"weak_best_link": {"state": BAD}},
    }
    two = {
        "node_id": "!c",
        "bad_count": 2,
        "packets": 5,
        "signals": {"sole_observer": {"state": BAD}, "weak_best_link": {"state": BAD}},
    }
    ordered = sorted([thin, asymmetric, two], key=signals.rank_key)
    assert [row["node_id"] for row in ordered] == ["!c", "!a", "!b"]


def test_a_node_we_know_more_about_sorts_above_one_we_barely_know() -> None:
    loud = {"node_id": "!a", "bad_count": 1, "packets": 900, "signals": {}}
    quiet = {"node_id": "!b", "bad_count": 1, "packets": 30, "signals": {}}
    assert [row["node_id"] for row in sorted([quiet, loud], key=signals.rank_key)] == ["!a", "!b"]


# --------------------------------------------------------- no scoring


def test_there_is_no_health_score_anywhere_in_the_feature() -> None:
    """A source guard, because a score is the easy thing to add later.

    A 0 to 100 number would let two `unknown` signals and one `bad`
    average into amber, and amber reads as "a bit broken" when the truth
    is "we cannot tell". The colour comes from `worst_state`.
    """
    import re

    from sonoran.api.routes import gaps as route
    from sonoran.jobs import gaps as job

    # A score would show up as a name that is read or written, not as
    # the word in a comment that denies it. These are the shapes it
    # would take: a dict key, an attribute, or an assignment.
    shapes = re.compile(r"""["']\w*score\w*["']\s*:|\.\w*score\w*\b|\b\w*score\w*\s*=""")
    for module in (signals, job, route):
        source = inspect.getsource(module)
        assert not shapes.search(source), f"{module.__name__} computes a score"

    page = (STATIC / "gaps.js").read_text(encoding="utf-8")
    assert not shapes.search(page)
    # The row's class comes from worst_state and from nothing else.
    assert "row.worst_state" in page


def test_the_unknown_state_is_never_drawn_as_a_warning() -> None:
    """Amber is the one colour `unknown` must not be.

    Amber is a severity between good and bad. `unknown` is not a
    severity at all, so the stylesheet gives it its own colour rather
    than reusing `--warn`.
    """
    sheet = (STATIC / "gaps.css").read_text(encoding="utf-8")
    assert "--gap-unknown" in sheet
    unknown_rules = [line for line in sheet.splitlines() if "gap-unknown" in line]
    assert unknown_rules
    assert not any("--warn" in line for line in unknown_rules)


# ------------------------------------------------------------ the API


def _client(cache: str) -> TestClient:
    return TestClient(create_app(Settings(_env_file=None, coverage_cache_dir=cache)))


def test_a_missing_assessment_is_a_working_state(tmp_path: Path) -> None:
    """`available: false` is not an error. The page says "not yet"."""
    with _client(str(tmp_path)) as client:
        for path in ("/api/gaps", "/api/gaps/nodes"):
            body = client.get(path).json()
            assert body["available"] is False
            assert body["reason"] == "no_assessment"
            assert body["nodes"] == []


def test_a_channel_that_names_no_preset_is_refused_not_guessed(tmp_path: Path) -> None:
    """Weather rides on top of a preset and does not name one.

    Assigning such traffic to a preset would describe a radio setting
    nobody is using. See `AGENTS.md` 9.7.
    """
    with _client(str(tmp_path)) as client:
        body = client.get("/api/gaps?channel=AZ-Weather").json()
        assert body["available"] is False
        assert body["reason"] == "not_a_preset"


def test_the_gaps_routes_are_get_only(tmp_path: Path) -> None:
    """The public API is read-only."""
    app = create_app(Settings(_env_file=None, coverage_cache_dir=str(tmp_path)))
    found = [(path, methods) for path, methods in _routes(app) if "gaps" in path]
    assert {path for path, _ in found} == {"/api/gaps", "/api/gaps/nodes"}
    for path, methods in found:
        assert methods <= {"GET"}, path


def test_the_gaps_route_opens_no_database_session() -> None:
    """The endpoint reads the written artefact and computes nothing.

    `docs/ISSUES.md` 2.9 is an open warning about a public endpoint doing
    per-row work while the map refreshes it every 15 seconds, and the gap
    queries are heavier than the one that warning is about.
    """
    from sonoran.api.routes import gaps as route

    source = inspect.getsource(route)
    assert "get_session" not in source
    assert "AsyncSession" not in source
    assert "select(" not in source


# ------------------------------------------------------------ the leak


def test_the_embed_can_never_see_the_gaps_feature() -> None:
    """A list of weak nodes with positions is a list of houses.

    It is a worse leak than the one `AGENTS.md` 9.25 already guards
    against, so the embed router is enumerated here and must hold no path
    that mentions this feature. This is the shape of
    `test_a_diagnostic_run_can_never_widen_the_public_map`.
    """
    from sonoran.api.routes.embed import router as embed_router

    for route in embed_router.routes:
        path = getattr(route, "path", "")
        assert "gap" not in path.lower(), f"the embed exposes {path}"

    # And the public sanitiser knows nothing about any of it.
    from sonoran.embed import sanitise

    source = inspect.getsource(sanitise)
    assert "gaps" not in source
    assert "gap_" not in source


def test_the_embed_page_loads_no_gaps_script() -> None:
    """The public document is its own document and stays that way."""
    page = (STATIC / "embed-coverage.html").read_text(encoding="utf-8")
    assert "gaps" not in page.lower()


def test_no_gaps_route_is_registered_under_the_embed_prefix() -> None:
    """Enumerated over the whole app, not only over one router."""
    app = create_app(Settings(_env_file=None, embed_enabled=True))
    served = _routes(app)
    embedded = [path for path, _ in served if path.startswith(("/api/embed", "/embed"))]
    # The walk must actually find the embed routes, or this asserts
    # nothing at all and passes for the wrong reason.
    assert embedded, "the embed routes were not enumerated"
    for path in embedded:
        assert "gap" not in path.lower()


# ----------------------------------------------------- the front end


def test_the_gaps_script_loads_before_the_router() -> None:
    """gaps.js must come before app.js.

    app.js runs the router as its last act. If gaps.js has not
    registered `window.SonoranGaps` by then, a reload straight onto
    #gaps quietly shows the dashboard. See `AGENTS.md` 9.14.2.
    """
    text = (STATIC / "index.html").read_text(encoding="utf-8")
    assert text.index("static/gaps.js") < text.index("static/app.js")


def test_the_gaps_page_is_registered_and_reachable() -> None:
    """A nav entry, a page section, and a router registration."""
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'data-nav="gaps"' in index
    assert 'data-page="gaps"' in index
    assert 'href="#gaps"' in index
    # The nav icon must exist, or the entry shows an empty box.
    assert 'id="i-gaps"' in index
    assert (STATIC / "app.js").read_text(encoding="utf-8").count("PAGES.gaps") == 1


def test_the_gaps_page_exports_the_global_the_router_needs() -> None:
    page = (STATIC / "gaps.js").read_text(encoding="utf-8")
    assert "window.SonoranGaps" in page


def test_the_page_uses_base_relative_api_paths() -> None:
    """The dashboard can be served under a base path."""
    page = (STATIC / "gaps.js").read_text(encoding="utf-8")
    assert "document.baseURI" in page
    assert "'/api/" not in page


def test_the_page_names_the_unknown_bucket_and_the_limits() -> None:
    """Neither may be cut, and neither may be hidden behind a toggle."""
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "data-gaps-unknown-table" in index
    assert "data-gaps-limits" in index
    # The limits list carries no `hidden` attribute of its own.
    assert "data-gaps-limits hidden" not in index
    assert "data-gaps-unknown-table hidden" not in index


def test_the_page_draws_no_link_between_two_nodes() -> None:
    """No signal here names both ends of one link.

    A line would claim a radio path that nothing on this page measured.
    See `AGENTS.md` 9.5 and 9.20.
    """
    page = (STATIC / "gaps.js").read_text(encoding="utf-8")
    for drawing in ("L.polyline", "L.polygon", "arrowHead"):
        assert drawing not in page


def test_an_unplaceable_node_is_not_drawn_on_the_map() -> None:
    """A marker is a claim about where something is.

    A coarse or missing position cannot support one, so such a node
    stays in the table where its confidence is named. The page also says
    how many it left off, because a map that silently drops nodes is
    worse than one that admits it.
    """
    page = (STATIC / "gaps.js").read_text(encoding="utf-8")
    assert "position_confidence !== 'exact'" in page
    assert "data-gaps-map-note" in page


# ---------------------------------------------------------- the sentences


def test_every_reason_a_signal_can_return_has_a_sentence() -> None:
    """A reason with no sentence would render as a machine name.

    Collected out of the source rather than listed by hand, so a new
    reason cannot be added without a sentence for it.
    """
    source = inspect.getsource(signals)
    used = set()
    for name in signals.REASON_SENTENCES:
        used.add(name)
    # Every `Signal(STATE, "reason"` literal in the module.
    import re

    for match in re.finditer(r'Signal\(\s*(?:BAD|OK|UNKNOWN),\s*"([a-z_]+)"', source):
        assert match.group(1) in used, f"no sentence for {match.group(1)}"


def test_an_unknown_placeholder_never_renders_as_empty() -> None:
    """A missing count must be visible, not invisible."""
    said = signals.sentence_for("no_gateway_heard_it", None, {})
    assert "unknown" in said


def test_an_unnamed_reason_falls_back_to_its_own_name() -> None:
    assert signals.sentence_for("something_new", None, {}) == "something_new"


def test_the_caveats_name_what_cannot_be_answered_at_all() -> None:
    """Section 2.5 and the preset rule, in plain words, always visible."""
    keys = {key for key, _ in signals.CAVEATS}
    assert "observers_are_gateways_only" in keys
    assert "receiving_is_not_observable" in keys
    assert "one_preset_only" in keys
    for _, text in signals.CAVEATS:
        assert text.endswith(".")
