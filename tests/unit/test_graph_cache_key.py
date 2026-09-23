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

import inspect

from sonoran.api.routes.graph import GRAPH_MAX_HOURS, graph_cache_key, mesh_graph

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


def test_the_window_ceiling_matches_what_the_pages_offer() -> None:
    """720 h bought nothing any page could ask for and cost ten seconds."""
    assert GRAPH_MAX_HOURS == 168, (
        "the graph window ceiling moved; the selector offers 6 h, 24 h, "
        "3 days and 7 days, and 720 h measured 9.2-10.1 s"
    )
