"""Each API caller has a request budget, and a reader never meets it.

See `sonoran/api/limits.py`.
"""

from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.api.limits import Buckets, Budget
from sonoran.config import Settings


def _client(**overrides: object) -> TestClient:
    settings = Settings(_env_file=None, **overrides)  # type: ignore[arg-type]
    return TestClient(create_app(settings))


def test_a_bucket_gives_its_burst_then_refills_at_its_rate() -> None:
    buckets = Buckets(Budget(burst=3, per_second=1.0))
    assert [buckets.take("a", 0.0) for _ in range(3)] == [0.0, 0.0, 0.0]
    assert buckets.take("a", 0.0) == 1.0
    # Half a second refills half a token: still half a second to wait.
    assert buckets.take("a", 0.5) == 0.5
    assert buckets.take("a", 1.0) == 0.0


def test_a_refill_never_passes_the_burst() -> None:
    buckets = Buckets(Budget(burst=2, per_second=1.0))
    buckets.take("a", 0.0)
    assert [buckets.take("a", 1000.0) for _ in range(2)] == [0.0, 0.0]
    assert buckets.take("a", 1000.0) > 0


def test_callers_do_not_share_a_bucket() -> None:
    buckets = Buckets(Budget(burst=1, per_second=1.0))
    assert buckets.take("a", 0.0) == 0.0
    assert buckets.take("a", 0.0) > 0
    assert buckets.take("b", 0.0) == 0.0


def test_the_table_of_callers_is_bounded() -> None:
    buckets = Buckets(Budget(burst=1, per_second=1.0), limit=2)
    for who in ("a", "b", "c"):
        buckets.take(who, 0.0)
    assert len(buckets._held) == 2


def test_the_defaults_leave_a_reader_well_clear() -> None:
    """A dozen dashboard pages at once, at 25 answers each, fit the burst."""
    settings = Settings(_env_file=None)
    assert settings.api_rate_limit_enabled
    assert settings.api_rate_burst >= 12 * 25
    # The live views poll once in 15 seconds. Far below the refill.
    assert settings.api_rate_per_second >= 1.0
    assert settings.api_tile_rate_burst >= 1000


def test_an_api_caller_over_its_budget_is_told_when_to_come_back() -> None:
    client = _client(api_rate_burst=2, api_rate_per_second=0.01)
    assert client.get("/api/version").status_code == 200
    assert client.get("/api/version").status_code == 200
    refused = client.get("/api/version")
    assert refused.status_code == 429
    assert int(refused.headers["Retry-After"]) >= 1
    # Inside the security headers, so a refusal carries them too.
    assert refused.headers["X-Content-Type-Options"] == "nosniff"


def test_the_page_static_files_and_health_are_never_limited() -> None:
    client = _client(api_rate_burst=1, api_rate_per_second=0.01)
    client.get("/api/version")
    assert client.get("/api/version").status_code == 429
    for path in ("/health", "/health", "/", "/static/app.js"):
        assert client.get(path).status_code == 200, path


def test_each_portal_user_has_a_budget_of_their_own() -> None:
    """Caddy passes the signed-in user in `Remote-User`."""
    client = _client(api_rate_burst=1, api_rate_per_second=0.01)
    assert client.get("/api/version", headers={"Remote-User": "will"}).status_code == 200
    assert client.get("/api/version", headers={"Remote-User": "will"}).status_code == 429
    assert client.get("/api/version", headers={"Remote-User": "tyler"}).status_code == 200


def test_tiles_spend_their_own_budget() -> None:
    """A map pan must not use up the budget of the rest of the page."""
    client = _client(
        api_rate_burst=1,
        api_rate_per_second=0.01,
        api_tile_rate_burst=1,
        api_tile_rate_per_second=0.01,
    )
    assert client.get("/api/version").status_code == 200
    tile = "/api/terrain/page/N33W113"
    assert client.get(tile).status_code != 429
    assert client.get(tile).status_code == 429


def test_a_base_path_does_not_hide_the_api_from_the_budget() -> None:
    """The routed path decides, as for the headers (AGENTS.md 9.9.2)."""
    app = create_app(
        Settings(
            _env_file=None,
            web_base_path="/sonoran",
            api_rate_burst=1,
            api_rate_per_second=0.01,
        )
    )
    client = TestClient(app, root_path="/sonoran")
    assert client.get("/sonoran/api/version").status_code == 200
    assert client.get("/sonoran/api/version").status_code == 429


def test_the_budget_can_be_turned_off() -> None:
    client = _client(api_rate_limit_enabled=False, api_rate_burst=1, api_rate_per_second=0.01)
    assert all(client.get("/api/version").status_code == 200 for _ in range(5))
