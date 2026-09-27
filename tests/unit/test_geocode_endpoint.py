"""The planner's address lookup, which is the one endpoint with a
security surface (§6.5 of the UX plan says so, and it is right).

Three things make it different from every other route on this API:

1. It **talks to a third party**, which nothing else on the server does
   except the terrain tile source.
2. It carries **words a reader typed**, which nothing else on this API
   does at all.
3. It is a **GET**, because `AGENTS.md` 4 forbids anything else, so those
   words are in the request line that uvicorn's access log writes out.

So the cases below are mostly refusals and limits. The happy path is one
of them; the rest are the reasons this can be turned on without it
becoming an open geocoding proxy, a way to spend the upstream's
politeness budget, or a log full of people's addresses.

The upstream is stubbed with `httpx.MockTransport`. That is deliberate:
the real geocoder must not be called by a test suite, both because the
suite would depend on somebody else's uptime and because doing so would
be exactly the impolite use its own policy forbids. One live lookup was
made by hand against the running instance and is recorded in the commit:
"Flagstaff" answered 35.1987522, -111.651822 and the access log line read
`GET /api/geocode?[removed]`.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from sonoran.api.app import create_app
from sonoran.api.routes import geocode as route
from sonoran.config import Settings
from sonoran.logging import RedactQueryFilter, quieten_http_client, redact_access_query

# One answer in Arizona, one well outside it, and three that are broken in
# the ways somebody else's JSON is broken.
NEAR = {"display_name": "Flagstaff, Coconino County, Arizona", "lat": "35.19875", "lon": "-111.65"}
FAR = {"display_name": "Flagstaff, Maine", "lat": "45.18", "lon": "-70.32"}
BROKEN = [
    {"display_name": "No coordinate at all"},
    {"display_name": "Empty coordinate", "lat": "", "lon": ""},
    {"display_name": "Null coordinate", "lat": None, "lon": None},
    {"lat": "34.0", "lon": "-112.0"},
    {"display_name": "   ", "lat": "34.0", "lon": "-112.0"},
    "not even an object",
]


@pytest.fixture(autouse=True)
def _cold_limits() -> None:
    """Each case gets its own rate budget and its own empty cache.

    The budget and the cache are module globals, so without this the
    eleventh request of the suite would be refused inside whichever test
    happened to make it — a failure that names rate limiting in a test
    that is about something else.
    """
    route.reset_limits()


def _settings(**over: object) -> Settings:
    held: dict[str, object] = {
        "geocode_url": "https://geocoder.example/search",
        # A box that contains Arizona and not Maine, so "inside the region"
        # is a real test rather than "inside the world".
        "map_home_south": 31.2,
        "map_home_west": -115.0,
        "map_home_north": 37.1,
        "map_home_east": -108.9,
    }
    held.update(over)
    return Settings(_env_file=None, **held)


def _client(
    answers: object = None, status: int = 200, settings: Settings | None = None
) -> tuple[TestClient, list[httpx.Request]]:
    """An app whose upstream is a stub, and the requests it received."""
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json=[NEAR] if answers is None else answers)

    transport = httpx.MockTransport(handle)
    real = httpx.AsyncClient

    def fake(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        return real(*args, transport=transport, **kwargs)  # type: ignore[arg-type]

    route.httpx.AsyncClient = fake  # type: ignore[assignment,misc]
    return TestClient(create_app(settings or _settings())), seen


@pytest.fixture(autouse=True)
def _restore_httpx() -> Iterator[None]:
    """Put the real client back, whatever a case did to it.

    `route.httpx` IS the httpx module, so the stub above is a global
    change and not a local one: without this, every later test in the
    whole suite that reaches an httpx client would get the geocoder's
    mock transport.
    """
    real = httpx.AsyncClient
    yield
    route.httpx.AsyncClient = real  # type: ignore[assignment,misc]


# --- it works ----------------------------------------------------------


def test_a_place_in_the_region_comes_back() -> None:
    client, _ = _client()
    body = client.get("/api/geocode", params={"q": "Flagstaff"}).json()
    assert body["places"] == [
        {"name": "Flagstaff, Coconino County, Arizona", "lat": 35.19875, "lon": -111.65}
    ]


def test_the_lookup_is_bounded_to_the_deployments_own_region() -> None:
    """Both halves: the upstream is asked to narrow, and the answer is
    narrowed again here.

    Asking is not enough — `bounded=1` is somebody else's promise. And
    filtering alone is not enough either, because without the viewbox the
    upstream ranks a place on the other side of the world first and the
    five answers we get back can all be dropped.
    """
    client, seen = _client(answers=[FAR, NEAR])
    body = client.get("/api/geocode", params={"q": "Flagstaff"}).json()
    assert [place["name"] for place in body["places"]] == ["Flagstaff, Coconino County, Arizona"], (
        "an answer outside the region was offered as a site"
    )
    asked = dict(seen[0].url.params)
    assert asked["bounded"] == "1", "the upstream was not asked to keep inside the box"
    assert asked["viewbox"] == "-115.0,31.2,-108.9,37.1", f"the box sent was {asked['viewbox']}"


def test_no_geography_is_written_into_the_endpoint() -> None:
    """Another mesh sets four numbers and this module does not change."""
    source = Path(route.__file__).read_text(encoding="utf-8")
    for bound in ("31.2", "37.1", "-115.0", "-108.9", "Arizona,"):
        assert bound not in source, f"{bound} is a home-region bound, hardcoded in geocode.py"


def test_the_upstream_is_told_who_is_asking_and_nothing_else() -> None:
    """The usage policy requires an identifying agent. It must not
    identify the reader."""
    client, seen = _client()
    client.get("/api/geocode", params={"q": "Flagstaff"})
    agent = seen[0].headers["user-agent"]
    assert "sonoran" in agent.lower(), f"the upstream was told {agent!r}"
    for leaked in ("cookie", "referer", "x-forwarded-for", "authorization"):
        assert leaked not in {name.lower() for name in seen[0].headers}, (
            f"{leaked} went to the upstream"
        )


# --- refusals ----------------------------------------------------------


def test_it_is_not_there_when_it_is_not_configured() -> None:
    """The off switch, and the whole reason the setting may be emptied."""
    client, seen = _client(settings=_settings(geocode_url=""))
    answer = client.get("/api/geocode", params={"q": "Flagstaff"})
    assert answer.status_code == 404
    assert not seen, "an unconfigured endpoint still called an upstream"


def test_the_dashboard_is_told_whether_to_draw_the_control() -> None:
    """A search box that answers 404 is worse than no search box.

    Said in the config the document already carries rather than
    discovered by asking, because a probe request would put an empty
    query in the log of a deployment that has this switched off.
    """
    on = TestClient(create_app(_settings())).get("/").text
    off = TestClient(create_app(_settings(geocode_url=""))).get("/").text
    assert '"geocode": {"enabled": true}' in on, "the page is not told the feature is on"
    assert '"geocode": {"enabled": false}' in off, "the page is not told the feature is off"


@pytest.mark.parametrize("query", ["", " ", "a", " x "])
def test_too_short_to_be_an_address(query: str) -> None:
    client, seen = _client()
    assert client.get("/api/geocode", params={"q": query}).status_code == 422
    assert not seen, f"{query!r} was forwarded to the upstream"


def test_too_long_to_be_an_address() -> None:
    client, seen = _client()
    answer = client.get("/api/geocode", params={"q": "x" * (route.QUERY_LIMIT + 1)})
    assert answer.status_code == 422
    assert not seen, "a pasted paragraph was forwarded to the upstream"


@pytest.mark.parametrize("query", ["Flag\nstaff", "Flag\x00staff", "Flag\rstaff", "Flag\x7fstaff"])
def test_a_control_character_is_refused_and_not_stripped(query: str) -> None:
    """Refused, because a query holding one is not a typed address.

    Quietly repairing input is how a validator ends up disagreeing with
    what it validated: the thing that was checked is not the thing that
    was sent.
    """
    client, seen = _client()
    assert client.get("/api/geocode", params={"q": query}).status_code == 422
    assert not seen


def test_somebody_elses_broken_json_does_not_reach_the_form() -> None:
    """`Number(undefined)` in the browser is NaN and `float(None)` raises.

    A name with no coordinate would put an empty latitude into the form
    and predict from nothing. The positive control is in the same
    response: the one good answer still comes through, so this cannot
    pass by dropping everything.
    """
    client, _ = _client(answers=[*BROKEN, NEAR])
    body = client.get("/api/geocode", params={"q": "Flagstaff"}).json()
    assert len(body["places"]) == 1, f"a broken entry became a place: {body['places']}"
    assert body["places"][0]["lat"] == 35.19875


@pytest.mark.parametrize("broken", BROKEN)
def test_a_broken_entry_is_refused_even_where_the_region_cannot_hide_it(broken: object) -> None:
    """The case above, with the region filter taken out of the way.

    A mutation test found this. Making `_place` fall back to `0.0, 0.0`
    when the coordinate cannot be read left the case above passing,
    because 0, 0 is in the Atlantic and Arizona's box drops it anyway. So
    the guard was untested and the other case was green for the wrong
    reason: two filters, one of them doing all the work.

    Here the box is the whole world, so only the guard can refuse it.
    """
    whole_world = (-90.0, -180.0, 90.0, 180.0)
    assert route._place(broken, whole_world) is None, f"{broken!r} became a place"
    # The positive control, in the same box: this cannot pass by refusing
    # everything.
    assert route._place(NEAR, whole_world) is not None


def test_an_answer_of_nothing_is_an_answer() -> None:
    """Not a 404. The reader typed something real and it is not here."""
    client, _ = _client(answers=[])
    answer = client.get("/api/geocode", params={"q": "Nowhere at all"})
    assert answer.status_code == 200
    assert answer.json() == {"places": []}


def test_an_upstream_that_fails_is_a_502_and_not_a_500() -> None:
    client, _ = _client(status=503)
    assert client.get("/api/geocode", params={"q": "Flagstaff"}).status_code == 502


def test_an_upstream_that_answers_with_the_wrong_shape_is_a_502() -> None:
    client, _ = _client(answers={"error": "nope"})
    assert client.get("/api/geocode", params={"q": "Flagstaff"}).status_code == 502


def test_no_more_than_a_handful_of_answers() -> None:
    """A geocoder will happily return fifty."""
    client, _ = _client(answers=[NEAR] * 50)
    body = client.get("/api/geocode", params={"q": "Flagstaff"}).json()
    assert len(body["places"]) == route.RESULT_LIMIT


# --- the limits --------------------------------------------------------


def test_one_client_cannot_have_the_whole_endpoint() -> None:
    """The budget, which is what stops this being an open geocoder.

    The window is a minute and the cases run in well under one, so the
    refusal arrives on the request after the budget.
    """
    client, _ = _client()
    codes = [
        client.get("/api/geocode", params={"q": f"place {index}"}).status_code
        for index in range(route.CLIENT_BUDGET + 2)
    ]
    assert codes[: route.CLIENT_BUDGET] == [200] * route.CLIENT_BUDGET, codes
    assert codes[route.CLIENT_BUDGET :] == [429, 429], codes


def test_the_table_of_clients_cannot_grow_without_limit() -> None:
    """A dict keyed on the caller's address is a memory leak with a
    network interface.

    #160 was this shape: an unbounded queue keyed on something a caller
    chooses. Oldest first, so the eviction cannot be used to dodge the
    limit by a client that keeps asking — `_spend` moves a refused client
    to the end too.
    """
    for index in range(route.CLIENT_TABLE_LIMIT + 50):
        route._spend(f"10.0.0.{index}", 0.0)
    assert len(route._spent) == route.CLIENT_TABLE_LIMIT


def test_the_same_query_twice_asks_the_upstream_once() -> None:
    """Its usage policy asks for caching rather than repeat queries, and a
    reader who mistypes and retypes a street makes exactly those."""
    client, seen = _client()
    client.get("/api/geocode", params={"q": "Flagstaff"})
    client.get("/api/geocode", params={"q": "FLAGSTAFF"})
    assert len(seen) == 1, f"the same query was sent {len(seen)} times"


def test_the_cache_is_bounded() -> None:
    """Held answers are keyed on what somebody typed, so the ceiling
    matters for the same reason the client table's does."""
    client, _ = _client()
    assert route.CACHE_ENTRIES <= 512
    assert len(route._answers) == 0
    for index in range(5):
        client.get("/api/geocode", params={"q": f"place {index}"})
    assert len(route._answers) == 5


# --- the log -----------------------------------------------------------


def _access_record(line: str) -> logging.LogRecord:
    """A record shaped the way uvicorn's access logger makes one."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1", "GET", line, "1.1", 200),
        exc_info=None,
    )


def test_the_address_is_taken_out_of_the_access_log() -> None:
    """A GET puts it in the request line, and uvicorn writes that out.

    The API is GET-only by architecture, so redaction is the answer
    rather than a POST body.
    """
    made = RedactQueryFilter(("/api/geocode",))
    record = _access_record("/api/geocode?q=1234+Camelback+Rd")
    assert made.filter(record) is True, "the record was dropped; a 502 would become invisible"
    assert "Camelback" not in record.getMessage(), record.getMessage()
    assert "/api/geocode?[removed]" in record.getMessage()


def test_every_other_path_keeps_its_query() -> None:
    """The negative control.

    Without it, a filter that emptied every query string would pass the
    case above and make the whole access log useless.
    """
    made = RedactQueryFilter(("/api/geocode",))
    record = _access_record("/api/nodes?limit=50")
    made.filter(record)
    assert "limit=50" in record.getMessage()


@pytest.mark.parametrize(
    "arguments",
    [(), ("only one",), "not a tuple", ("a", "b", 3), ("a", "b", None)],
)
def test_a_record_of_another_shape_is_left_alone(arguments: object) -> None:
    """uvicorn is not the only thing that may log on that logger.

    A filter that assumed the shape would throw inside `logging`, where
    the exception comes out as a mangled line rather than a traceback.
    """
    made = RedactQueryFilter(("/api/geocode",))
    record = _access_record("/x")
    record.args = arguments  # type: ignore[assignment]
    assert made.filter(record) is True


def test_the_filter_is_installed_once_however_many_apps_are_made() -> None:
    """The factory runs once per process in production and once per case
    here. A filter per case is a slow leak rather than a visible fault."""
    logger = logging.getLogger("uvicorn.access")
    before = len([f for f in logger.filters if isinstance(f, RedactQueryFilter)])
    redact_access_query("/api/geocode")
    redact_access_query("/api/geocode")
    after = len([f for f in logger.filters if isinstance(f, RedactQueryFilter)])
    assert after == max(before, 1), f"{after} copies of the filter are attached"


def test_the_http_client_does_not_log_the_url_it_fetched() -> None:
    """**Measured, not assumed.** httpx logs `HTTP Request: GET <url>` at
    INFO, not at DEBUG, and the first live lookup on the running instance
    printed the reader's address one line under the redacted access log.

    Raising the floor is the fix; every httpx caller in this repository
    logs its own outcome, so nothing that matters is lost.
    """
    quieten_http_client()
    assert logging.getLogger("httpx").level >= logging.WARNING, (
        "httpx will log the outbound URL, with the address in it"
    )
    # And the factory does it, not only this test.
    create_app(_settings())
    assert logging.getLogger("httpx").level >= logging.WARNING


def test_the_endpoint_never_logs_what_was_asked_for(caplog: pytest.LogCaptureFixture) -> None:
    """Its own warnings say the status, never the query."""
    client, _ = _client(status=500)
    with caplog.at_level(logging.DEBUG):
        client.get("/api/geocode", params={"q": "1234 Camelback Rd"})
    assert caplog.records, "the failure was not reported at all"
    for record in caplog.records:
        assert "Camelback" not in record.getMessage(), record.getMessage()


# --- the CSP -----------------------------------------------------------


def test_this_needed_no_new_connect_source() -> None:
    """The whole reason for a proxy rather than a browser call.

    §6.5 records that `connect-src 'self'` blocks a third-party geocoder
    from the page. If a geocoder origin ever appears in this header, the
    reader's IP address is going to it directly and this endpoint has
    stopped being the thing that protects them.
    """
    client = TestClient(create_app(_settings()))
    policy = client.get("/").headers["Content-Security-Policy"]
    connect = next(part for part in policy.split(";") if part.strip().startswith("connect-src"))
    assert "geocoder.example" not in connect, connect
    assert "nominatim" not in connect, connect
