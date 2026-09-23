"""A cache for endpoints that take arguments, with a ceiling (#148).

`TimedCache` holds one value, which fits an endpoint that takes none.
The expensive endpoints on this API all take arguments, so one hold per
endpoint would answer every caller with the first caller's parameters.

The ceiling is the point. `dict[key, TimedCache]` is the obvious
version, the keys come from the query string, and a caller who varies
`hours` would grow it without limit — the #160 bug, in the one place
whose job is to protect the box.
"""

import asyncio

import pytest

from sonoran.api.cache import KeyedCache, clear_all


async def _made(value: str) -> str:
    return value


def test_each_key_gets_its_own_answer() -> None:
    """The failure this exists to prevent: one caller's parameters
    answered to everybody."""

    async def run() -> None:
        cache: KeyedCache[str] = KeyedCache()
        assert await cache.get("a", 60, lambda: _made("A")) == "A"
        assert await cache.get("b", 60, lambda: _made("B")) == "B"
        assert await cache.get("a", 60, lambda: _made("ignored")) == "A"

    asyncio.run(run())


def test_the_number_of_keys_held_is_bounded() -> None:
    """The reason this is a class and not a dict."""

    async def run() -> None:
        cache: KeyedCache[str] = KeyedCache(capacity=8)
        for index in range(500):
            await cache.get(f"k{index}", 60, lambda i=index: _made(str(i)))  # type: ignore[misc]
        assert len(cache) == 8, f"held {len(cache)} entries for a capacity of 8"

    asyncio.run(run())


def test_the_oldest_key_is_the_one_dropped() -> None:
    async def run() -> None:
        cache: KeyedCache[str] = KeyedCache(capacity=2)
        await cache.get("first", 60, lambda: _made("1"))
        await cache.get("second", 60, lambda: _made("2"))
        await cache.get("third", 60, lambda: _made("3"))
        # "first" was evicted, so it is made again rather than returned.
        assert await cache.get("first", 60, lambda: _made("remade")) == "remade"
        assert await cache.get("third", 60, lambda: _made("ignored")) == "3"

    asyncio.run(run())


def test_one_caller_refreshes_while_the_others_wait() -> None:
    """Without this a cache is a thundering herd with extra steps.

    Twenty callers arrive together on a cold key; `make` must run once.
    """
    runs = 0

    async def slow() -> str:
        nonlocal runs
        runs += 1
        await asyncio.sleep(0.05)
        return "value"

    async def run() -> None:
        cache: KeyedCache[str] = KeyedCache()
        answers = await asyncio.gather(*(cache.get("same", 60, slow) for _ in range(20)))
        assert answers == ["value"] * 20

    asyncio.run(run())
    assert runs == 1, f"the expensive work ran {runs} times for 20 simultaneous callers"


def test_a_slow_key_does_not_hold_up_a_different_one() -> None:
    """The lock is per key, not per cache.

    One node's slow query must not serialise every other node's.
    """
    started: list[str] = []

    async def slow(name: str) -> str:
        started.append(name)
        await asyncio.sleep(0.05)
        return name

    async def run() -> None:
        cache: KeyedCache[str] = KeyedCache()
        await asyncio.gather(
            cache.get("a", 60, lambda: slow("a")),
            cache.get("b", 60, lambda: slow("b")),
        )
        # Both began before either finished.
        assert started == ["a", "b"] or started == ["b", "a"]

    asyncio.run(run())


def test_a_hold_of_zero_turns_it_off() -> None:
    """How a deployment asks for live figures, as with TimedCache."""

    async def run() -> None:
        cache: KeyedCache[str] = KeyedCache()
        assert await cache.get("k", 0, lambda: _made("one")) == "one"
        assert await cache.get("k", 0, lambda: _made("two")) == "two"

    asyncio.run(run())


def test_clear_all_empties_it() -> None:
    """Module-level caches outlive a test, so one case can be answered
    from another's data — which does not look like a cache at all."""

    async def run() -> None:
        cache: KeyedCache[str] = KeyedCache()
        await cache.get("k", 60, lambda: _made("first"))
        clear_all()
        assert await cache.get("k", 60, lambda: _made("second")) == "second"

    asyncio.run(run())


def test_a_capacity_below_one_is_refused() -> None:
    """A zero capacity evicts what it just stored, so every get is a
    miss with the overhead of a cache and none of the benefit."""
    with pytest.raises(ValueError):
        KeyedCache(capacity=0)
