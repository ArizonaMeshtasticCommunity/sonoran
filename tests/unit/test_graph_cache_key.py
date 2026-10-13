"""The graph cache key covers every parameter that changes the answer.

A cache key that misses a parameter serves a different question's answer
— node A's graph for node B's request, or a 7-day window for a 6-hour
one. It is the worst thing a cache can do and the quietest: everything
still returns 200 with plausible-looking data.

So the key is not trusted to be right. These read `mesh_graph`'s
signature and require every parameter in it to reach the key, which
means a parameter added later fails here rather than being silently
ignored.

The cache was added because the endpoint is slow in ordinary use.
Measured against the deployed instance:

    hours=24  limit=2000    1.7 s   (the page default)
    hours=168 limit=2000    3.3 s
    hours=168 limit=10000   4.0 s   (the widest the selector can ask)

and the ceiling was lowered from 720 h to 168 h in the same change,
because the graph selector offers at most 7 days while 720 h cost
9.2-10.1 s.
"""

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import patch

from sonoran.api.routes import graph
from sonoran.api.routes.graph import (
    GRAPH_CEILING_HOURS,
    GRAPH_MAX_HOURS,
    clamp_hours,
    graph_cache_key,
    mesh_graph,
)

# Not part of the question the cache answers.
IGNORED = {"request", "session"}


def _parameters() -> set[str]:
    return {name for name in inspect.signature(mesh_graph).parameters if name not in IGNORED}


def test_the_key_function_takes_exactly_the_endpoint_parameters() -> None:
    """The check that keeps the ones below honest."""
    assert _parameters() == set(inspect.signature(graph_cache_key).parameters), (
        "mesh_graph and graph_cache_key no longer take the same parameters, "
        "so the cache is keyed on a different question than it answers"
    )


def test_changing_any_parameter_changes_the_key() -> None:
    """Built by varying each parameter in turn, so a new one is covered
    the moment it is added to the key function."""
    base = {"hours": 24, "limit": 2000, "channel": "LongFast"}
    other = {"hours": 168, "limit": 500, "channel": "MediumFast"}
    baseline = graph_cache_key(**base)
    for name in base:
        changed = graph_cache_key(**(base | {name: other[name]}))
        assert changed != baseline, (
            f"changing {name} does not change the cache key, so two "
            f"different requests share one answer"
        )


def test_no_channel_and_an_empty_channel_are_the_same_question() -> None:
    """They reach the same query, so they must reach the same key."""
    assert graph_cache_key(hours=24, limit=10, channel=None) == graph_cache_key(
        hours=24, limit=10, channel=""
    )


def test_a_channel_cannot_forge_another_key() -> None:
    """The separator matters: with no separator, `hours=241, limit=0`
    and `hours=24, limit=10` would both be "24110"."""
    assert graph_cache_key(hours=241, limit=0, channel=None) != graph_cache_key(
        hours=24, limit=10, channel=None
    )


def test_the_window_is_clamped_and_not_refused() -> None:
    """An existing caller with hours=720 must not start getting 422s.

    This is a public endpoint on a community deployment. Somebody's
    script with 720 in it was inside the documented range yesterday, and
    breaking it to protect our box is the wrong trade when clamping
    exists. 720 h measured 9.2-10.1 s against 3.3 s at 168 h.
    """
    assert GRAPH_MAX_HOURS == 168, "the working window moved"
    assert GRAPH_CEILING_HOURS >= 720, (
        "the parameter no longer ACCEPTS the old ceiling, so a caller "
        "that used to work now gets a 422 instead of a narrower answer"
    )
    assert clamp_hours(24) == (24, None), "a normal request was altered"
    assert clamp_hours(168) == (168, None), "the boundary was clamped"
    assert clamp_hours(720) == (168, 720), (
        "a 720 h request is not clamped to 168 while reporting what it asked for"
    )


def test_a_clamped_request_says_so_in_the_body() -> None:
    """Silently returning a different window would be worse than a 422.

    `window_hours` already carries what was used; `window_clamped`
    names what was asked for, so a caller can tell.
    """
    source = inspect.getsource(mesh_graph)
    assert "window_clamped" in source, (
        "a clamped window is not reported, so a caller asking for 720 h "
        "gets 168 h of data and no way to know"
    )


def test_the_clamp_reaches_the_response_body() -> None:
    """Exercised through the real wrapper, not just `clamp_hours`.

    The contract-preserving claim is that a caller asking for 720 h gets
    data and can tell it was narrowed. That is a property of the
    RESPONSE, so testing the helper alone would not have shown it.

        asked  24 h -> window_hours=24   window_clamped=None
        asked 168 h -> window_hours=168  window_clamped=None
        asked 720 h -> window_hours=168  window_clamped=720
    """

    async def fake(_session: object, hours: int, _limit: int, _channel: object) -> dict:
        return {"window_hours": hours, "links": []}

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace(stats_cache_seconds=0)))
    )

    async def run() -> None:
        with patch.object(graph, "_mesh_graph", fake):
            for asked, used, reported in ((24, 24, None), (168, 168, None), (720, 168, 720)):
                graph._graph_cache.clear()
                body = await graph.mesh_graph(
                    request, hours=asked, limit=100, channel=None, session=None
                )
                assert body["window_hours"] == used, f"{asked} h ran as {body['window_hours']}"
                assert body.get("window_clamped") == reported, (
                    f"{asked} h reported window_clamped={body.get('window_clamped')}"
                )

    asyncio.run(run())


def test_a_clamped_request_does_not_poison_the_cache() -> None:
    """A 720 h ask and a 168 h ask share a cache key, and must not
    share the `window_clamped` note.

    They run the same query and get the same rows. Only the caller who
    asked for more should be told it was cut — otherwise an honest 168 h
    request starts claiming it was clamped, which is a lie about its own
    data.
    """
    ran: list[int] = []

    async def fake(_session: object, hours: int, _limit: int, _channel: object) -> dict:
        ran.append(hours)
        return {"window_hours": hours, "links": []}

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(stats_cache_seconds=60, stats_cache_max_seconds=300)
            )
        )
    )

    async def run() -> None:
        with patch.object(graph, "_mesh_graph", fake):
            graph._graph_cache.clear()
            clamped = await graph.mesh_graph(
                request, hours=720, limit=100, channel=None, session=None
            )
            honest = await graph.mesh_graph(
                request, hours=168, limit=100, channel=None, session=None
            )
            assert clamped["window_clamped"] == 720
            assert honest.get("window_clamped") is None, (
                "the honest 168 h request inherited the clamp note from the cached 720 h answer"
            )
            assert len(ran) == 1, "the two requests did not share the cached work"

    asyncio.run(run())
