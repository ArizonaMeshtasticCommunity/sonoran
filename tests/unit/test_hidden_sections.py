"""An operator can hide unfinished parts of the site (`HIDDEN_SECTIONS`).

Logan asked for this on 2026-10-21, for the test roll-out to main: "If we
feel it's ready we can add the ability to hide ui sections and do a test
roll out to main." So a deployment must be able to keep a part of the
site out of view without a code change.

What these cases hold, one claim each:

- The setting is a comma list of section ids. Empty is the default, and
  the default is today's site exactly: nothing hidden, the same asset
  version, the same manifest.
- An id that is not a section is reported once at start and ignored. A
  typo must not stop the API, and it must not pass in silence either.
- A hidden section is hidden on the server too. Its API routes answer
  404, so the feature is not only out of sight.
- A route that another visible part of the site uses stays open. The
  rule is: a route closes only when EVERY section that uses it is
  hidden. `/health` and the page itself never close.
- Every registered route is classified, so a route added later is a
  decision and not an accident (the same idea as
  `test_embed_policy_is_explicit.py`).
- The page learns the list from the config already written into
  `index.html`. No extra request.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from sonoran.api import sections
from sonoran.api.app import STATIC_DIR, _asset_version, create_app
from sonoran.config import Settings

MANIFEST = json.loads((STATIC_DIR / "manifest.webmanifest").read_text(encoding="utf-8"))


def _client(hidden: str = "") -> TestClient:
    app = create_app(Settings(_env_file=None, hidden_sections=hidden))
    # A data route reaches for the database, and there is none here. A
    # 500 is the answer "the route is open"; only a 404 means closed.
    return TestClient(app, raise_server_exceptions=False)


def _page_config(client: TestClient) -> dict[str, object]:
    html = client.get("/").text
    start = html.index("window.SONORAN = ") + len("window.SONORAN = ")
    end = html.index(";</script>", start)
    return json.loads(html[start:end])


def _all_routes() -> set[str]:
    """Every registered path, inside included routers too.

    The same walk as `test_embed_policy_is_explicit.py`: `app.routes` alone
    finds four paths out of more than seventy.
    """
    app = create_app(Settings(_env_file=None, hidden_sections=",".join(sections.SECTIONS)))

    def walk(routes: object) -> list[str]:
        out: list[str] = []
        for route in routes or []:  # type: ignore[attr-defined]
            path = getattr(route, "path", None)
            if path:
                out.append(path)
            inner = getattr(route, "original_router", None)
            if inner is not None:
                out.extend(walk(getattr(inner, "routes", [])))
            out.extend(walk(getattr(route, "routes", [])))
        return out

    return set(walk(app.routes))


# ---- The setting -----------------------------------------------------


def test_the_default_hides_nothing() -> None:
    assert Settings(_env_file=None).hidden_sections == []


def test_the_setting_is_a_comma_list() -> None:
    settings = Settings(_env_file=None, hidden_sections=" rf, Planner ,,")
    assert settings.hidden_sections == ["rf", "Planner"]


def test_ids_are_read_without_case_and_space() -> None:
    hidden, unknown = sections.resolve(["rf", " Planner "])
    assert hidden == frozenset({"rf", "planner"})
    assert unknown == []


def test_an_unknown_id_is_ignored_and_returned() -> None:
    hidden, unknown = sections.resolve(["rf", "nope"])
    assert hidden == frozenset({"rf"})
    assert unknown == ["nope"]


def test_the_home_page_and_settings_cannot_be_hidden() -> None:
    """The "not available" page links to the dashboard, so it must exist."""
    hidden, unknown = sections.resolve(["dashboard", "settings"])
    assert hidden == frozenset()
    assert unknown == ["dashboard", "settings"]


def test_hiding_a_page_hides_what_is_part_of_it() -> None:
    """The leaderboards are a panel on the Statistics page."""
    hidden, _ = sections.resolve(["stats"])
    assert hidden == frozenset({"stats", "leaderboards"})


def test_a_part_can_be_hidden_alone() -> None:
    hidden, _ = sections.resolve(["leaderboards"])
    assert hidden == frozenset({"leaderboards"})


def test_an_unknown_id_is_logged_at_start(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="sonoran.api.app"):
        _client("rf,bogus,dashboard")
    messages = [record.getMessage() for record in caplog.records]
    lines = [message for message in messages if "HIDDEN_SECTIONS" in message]
    assert len(lines) == 1, lines
    assert "bogus" in lines[0]
    assert "dashboard" in lines[0]
    assert "'rf'" not in lines[0]


def test_nothing_is_logged_for_a_good_list(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="sonoran.api.app"):
        _client("rf,planner")
    assert not [r for r in caplog.records if "HIDDEN_SECTIONS" in r.getMessage()]


# ---- Routes ----------------------------------------------------------


def test_a_hidden_section_answers_404() -> None:
    """The positive control first: the same routes answer when shown."""
    shown = _client()
    assert shown.get("/api/rf/kinds").status_code == 200
    assert shown.get("/api/radio/antennas").status_code == 200

    hidden = _client("rf,planner")
    assert hidden.get("/api/rf/kinds").status_code == 404
    assert hidden.get("/api/radio/antennas").status_code == 404
    assert hidden.get("/api/terrain/region").status_code == 404


def test_a_section_left_visible_keeps_its_routes() -> None:
    client = _client("rf")
    assert client.get("/api/radio/antennas").status_code == 200


def test_a_route_parameter_does_not_escape_the_gate() -> None:
    """The rule reads the route's template, not the path a caller sent."""
    client = _client("rf")
    assert client.get("/api/rf/track/adsb/abc123").status_code == 404
    assert client.get("/api/rf/spectrum/station-1/ranges").status_code == 404


def test_the_page_and_health_never_close() -> None:
    client = _client(",".join(sections.SECTIONS))
    for path in ("/health", "/api/version", "/", "/sw.js"):
        assert client.get(path).status_code == 200, path


def test_a_shared_route_stays_open_while_one_user_is_visible() -> None:
    """`/api/map/nodes` draws the live map, coverage and the planner."""
    assert sections.ROUTES["/api/map/nodes"] == frozenset({"map", "coverage", "planner"})
    assert _client("map").get("/api/map/nodes").status_code != 404
    assert _client("map,coverage,planner").get("/api/map/nodes").status_code == 404


def test_a_route_with_one_user_closes_with_it() -> None:
    """The plausible wrong rule, "close when ANY user is hidden", fails here."""
    assert sections.is_closed("/api/map/nodes", frozenset({"map"})) is False
    assert sections.is_closed("/api/map/traffic", frozenset({"map"})) is True


def test_shared_routes_never_close() -> None:
    every = frozenset(sections.SECTIONS)
    for path in sections.SHARED:
        assert not sections.is_closed(path, every), path


def test_the_leaderboards_close_alone() -> None:
    client = _client("leaderboards")
    assert client.get("/api/stats/leaderboards").status_code == 404
    assert client.get("/api/stats/top").status_code != 404


def test_the_embed_goes_with_coverage() -> None:
    """The embed is the coverage map on another site."""
    app = create_app(Settings(_env_file=None, hidden_sections="coverage", embed_enabled=True))
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/embed/coverage").status_code == 404
    assert client.get("/api/embed/nodes").status_code == 404


def test_the_route_walk_finds_routes() -> None:
    """The control for the next test, which an empty walk would pass."""
    routes = _all_routes()
    assert len(routes) > 70, len(routes)
    assert "/api/rf/kinds" in routes


def test_every_route_is_classified() -> None:
    """A new route must be put in a section, or named as shared."""
    known = set(sections.ROUTES) | sections.SHARED
    unclassified = sorted(path for path in _all_routes() if path not in known)
    assert not unclassified, (
        "add each of these to sections.ROUTES (the sections that use it) "
        f"or to sections.SHARED (a route that never closes): {unclassified}"
    )


def test_the_classification_names_real_routes_and_sections() -> None:
    routes = _all_routes()
    stale = sorted((set(sections.ROUTES) | sections.SHARED) - routes)
    assert not stale, f"these are classified but not registered: {stale}"
    assert not set(sections.ROUTES) & sections.SHARED
    for path, users in sections.ROUTES.items():
        assert users, path
        assert users <= set(sections.SECTIONS), path


# ---- The page --------------------------------------------------------


def test_the_page_is_told_what_is_hidden() -> None:
    assert _page_config(_client())["hiddenSections"] == []
    assert _page_config(_client("stats,rf"))["hiddenSections"] == ["leaderboards", "rf", "stats"]


def test_the_page_is_not_told_an_unknown_id() -> None:
    assert _page_config(_client("rf,bogus"))["hiddenSections"] == ["rf"]


def test_the_default_asset_version_is_unchanged() -> None:
    assert create_app(Settings(_env_file=None)).state.asset_version == _asset_version()


def test_a_change_to_the_list_is_a_new_version() -> None:
    """The manifest below is kept a year under its `?v=`, so the list is in it."""
    default = create_app(Settings(_env_file=None)).state.asset_version
    rf = create_app(Settings(_env_file=None, hidden_sections="rf")).state.asset_version
    again = create_app(Settings(_env_file=None, hidden_sections="RF, bogus")).state.asset_version
    planner = create_app(Settings(_env_file=None, hidden_sections="planner")).state.asset_version
    assert rf != default
    assert rf == again
    assert planner not in (rf, default)
    assert f"'{rf}'" in _client("rf").get("/sw.js").text


def test_the_default_manifest_is_the_file() -> None:
    client = _client()
    version = client.app.state.asset_version  # type: ignore[attr-defined]
    response = client.get(f"/static/manifest.webmanifest?v={version}")
    assert response.status_code == 200
    assert response.content == (STATIC_DIR / "manifest.webmanifest").read_bytes()


def test_the_install_shortcuts_leave_out_a_hidden_page() -> None:
    """Touch and hold the app icon: "RF map" must not be offered."""
    assert "../#rf" in [item["url"] for item in MANIFEST["shortcuts"]]
    client = _client("rf")
    version = client.app.state.asset_version  # type: ignore[attr-defined]
    response = client.get(f"/static/manifest.webmanifest?v={version}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    assert response.headers["Cache-Control"] == "public, max-age=31536000, immutable"
    body = response.json()
    assert [item["url"] for item in body["shortcuts"]] == ["../#map", "../#nodes"]
    assert {key: value for key, value in body.items() if key != "shortcuts"} == {
        key: value for key, value in MANIFEST.items() if key != "shortcuts"
    }
