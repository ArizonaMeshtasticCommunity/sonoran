"""The shared hold, and the half of it that was missing.

Every hand-rolled cache in the API read the clock, found the hold
expired, and did the work. All of them, in every request that arrived
in that instant. So a hold made an endpoint cheap while it was warm and
left it at its full cost multiplied by the number of concurrent readers
at the one moment the page was busy.

`test_one_caller_refreshes_an_expired_hold` is the test that fails
against that shape and passes against this one.
"""

import asyncio

from sonoran.api.cache import TimedCache


def test_a_made_value_is_returned() -> None:
    """The plain case."""

    async def go() -> int:
        cache: TimedCache[int] = TimedCache()
        return await cache.get(60.0, _counter([1]))

    assert asyncio.run(go()) == 1


def test_a_held_value_is_not_made_twice() -> None:
    """The hold itself."""

    async def go() -> tuple[int, int, int]:
        cache: TimedCache[int] = TimedCache()
        calls = [0]
        make = _counting(calls)
        first = await cache.get(60.0, make)
        second = await cache.get(60.0, make)
        return (first, second, calls[0])

    first, second, calls = asyncio.run(go())
    assert first == second == 1
    assert calls == 1


def test_a_hold_of_zero_makes_the_value_every_time() -> None:
    """Zero turns the cache off, which a deployment may ask for."""

    async def go() -> int:
        cache: TimedCache[int] = TimedCache()
        calls = [0]
        make = _counting(calls)
        await cache.get(0.0, make)
        await cache.get(0.0, make)
        return calls[0]

    assert asyncio.run(go()) == 2


def test_an_expired_hold_is_made_again() -> None:
    """A hold that has run out is a hold that has run out."""

    async def go() -> int:
        cache: TimedCache[int] = TimedCache()
        calls = [0]
        make = _counting(calls)
        await cache.get(60.0, make)
        # Let real time pass, then ask with a hold shorter than it. The
        # clock is `time.monotonic`, so the sleep has to be real: two
        # statements in a row can read the same instant.
        await asyncio.sleep(0.02)
        await cache.get(0.005, make)
        return calls[0]

    assert asyncio.run(go()) == 2


def test_one_caller_refreshes_an_expired_hold() -> None:
    """The stampede. This is the finding.

    Ten callers arrive together on a cold cache. Exactly one of them
    does the work and the other nine read its answer.

    Without the lock every one of them runs `make`, because every one
    of them checks the clock before any of them has finished. That is
    the shape `/api/embed/nodes` had, where the work is a full read of
    the node table, and the moment it happens is the moment a public
    page is being loaded by several people at once.
    """

    async def go() -> tuple[int, list[int]]:
        cache: TimedCache[int] = TimedCache()
        calls = [0]

        async def make() -> int:
            calls[0] += 1
            # Yield, so every waiting caller gets a turn to check the
            # clock before this one stores its answer. Without the lock
            # they all find it empty and all call `make`.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return calls[0]

        answers = await asyncio.gather(*(cache.get(60.0, make) for _ in range(10)))
        return (calls[0], list(answers))

    calls, answers = asyncio.run(go())
    assert calls == 1, f"{calls} callers ran the work; one should have"
    assert answers == [1] * 10


def test_a_falsy_value_is_still_held() -> None:
    """An empty answer is an answer.

    `/api/embed/coverage` returns "there is no map" as a perfectly
    ordinary dict, and an empty node list is what a fresh deployment
    has. A cache that tested its own held value for truth would refuse
    to hold exactly the answers that are cheapest to hold.
    """

    async def go() -> int:
        cache: TimedCache[list[int]] = TimedCache()
        calls = [0]

        async def make() -> list[int]:
            calls[0] += 1
            return []

        assert await cache.get(60.0, make) == []
        assert await cache.get(60.0, make) == []
        return calls[0]

    assert asyncio.run(go()) == 1


def test_clear_forgets_the_value() -> None:
    """For tests, and for anything that knows the answer has moved."""

    async def go() -> int:
        cache: TimedCache[int] = TimedCache()
        calls = [0]
        make = _counting(calls)
        await cache.get(60.0, make)
        cache.clear()
        await cache.get(60.0, make)
        return calls[0]

    assert asyncio.run(go()) == 2


def test_a_cache_survives_a_new_event_loop() -> None:
    """A module-level cache outlives any one loop.

    An `asyncio.Lock` binds to the loop it is first awaited in and
    raises in any other. These caches are module globals in the route
    files, and the tests run each case in its own `asyncio.run`. A
    process that restarted its loop would meet the same thing in
    production, long after the deploy, looking like nothing to do with
    caching.
    """
    cache: TimedCache[int] = TimedCache()
    calls = [0]
    make = _counting(calls)

    async def go() -> int:
        return await cache.get(0.0, make)

    # Three separate loops, one after another.
    assert asyncio.run(go()) == 1
    assert asyncio.run(go()) == 2
    assert asyncio.run(go()) == 3


# --- helpers -----------------------------------------------------------


def _counter(values: list[int]):  # type: ignore[no-untyped-def]
    """Return a maker that answers with the next listed value."""

    async def make() -> int:
        return values.pop(0)

    return make


def _counting(calls: list[int]):  # type: ignore[no-untyped-def]
    """Return a maker that counts how many times it ran."""

    async def make() -> int:
        calls[0] += 1
        return calls[0]

    return make
