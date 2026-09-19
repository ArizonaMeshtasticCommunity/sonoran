"""An answer held for a while, and refreshed by one caller at a time.

Two separate things, and the second one is what kept being left out.

The hold is obvious. An endpoint that a page loads on every view must
not ask the database on every view.

The lock is not obvious, and without it a hold is a thundering herd
with extra steps. The moment it expires, every request already in
flight finds it expired, and every one of them runs the expensive work.
The cost of the endpoint is then its cost multiplied by however many
people loaded the page in that same second — which is precisely the
moment the box is busy. One caller refreshes; the rest wait for that
answer and pay nothing.

This is shared rather than written out at each call site because there
were already three hand-rolled holds in `routes/embed.py`, none of them
locked, and the next one would have been a fourth.

Nothing here decides what a value means. It holds one and hands it back.
"""

import asyncio
import time
import weakref
from collections.abc import Awaitable, Callable

# Every cache that has been made, so they can all be emptied at once.
#
# The caches are module globals in the route files, which means one test
# can be answered from the value another test put there. The hold is
# tens of seconds and a suite runs faster than that, so a stale answer
# does not look like a cache at all: it looks like the endpoint
# returning another test's data.
#
# Weak references, so holding one here never keeps a cache alive.
_ALL: weakref.WeakSet["TimedCache[object]"] = weakref.WeakSet()


def clear_all() -> None:
    """Empty every cache. For tests, between cases."""
    for cache in list(_ALL):
        cache.clear()


class TimedCache[T]:
    """One value, held for a while, refreshed by at most one caller.

    The hold is passed to `get` rather than fixed here, so the length
    can come from settings and there is no second copy of it to drift.
    """

    __slots__ = ("__weakref__", "_held", "_lock", "_lock_loop")

    def __init__(self) -> None:
        self._held: tuple[float, T] | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop: asyncio.AbstractEventLoop | None = None
        _ALL.add(self)  # type: ignore[arg-type]

    def _fresh(self, seconds: float) -> tuple[bool, T | None]:
        """Return whether the held value is still young enough, and it.

        The flag is separate from the value because a held value may
        legitimately be None, empty, or False. A cache that read its own
        answer to decide whether it had one would refuse to hold exactly
        the answers that are cheapest to hold and most worth holding:
        `/api/embed/coverage` returning "there is no map".
        """
        held = self._held
        if held is None:
            return (False, None)
        if seconds <= 0.0:
            return (False, None)
        if time.monotonic() - held[0] >= seconds:
            return (False, None)
        return (True, held[1])

    def _loop_lock(self) -> asyncio.Lock:
        """Return a lock belonging to the event loop that is running now.

        An `asyncio.Lock` binds itself to the loop it is first awaited
        in and raises if it is later awaited in another. A module-level
        cache outlives any one loop: the tests run each case in its own
        `asyncio.run`, and a process that restarts its loop would hit
        the same thing in production, where it would appear long after
        the deploy and look like nothing to do with caching.

        A new loop gets a new lock. Nothing is in flight in a loop that
        is gone, so there is nothing to hand over.
        """
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop is not loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def get(self, seconds: float, make: Callable[[], Awaitable[T]]) -> T:
        """Return the held value, or make one.

        `make` runs at most once across however many callers arrive
        together. A second caller that arrives while the first is
        working waits, and then finds the answer already there: the
        check is made again inside the lock, which is the half that
        makes the lock worth having.

        A hold of zero or less turns the cache off and always calls
        `make`, which is how a deployment asks for live figures.
        """
        fresh, value = self._fresh(seconds)
        if fresh:
            return value  # type: ignore[return-value]

        async with self._loop_lock():
            # Another caller may have refreshed it while this one
            # waited. Without this the lock would serialise the herd
            # instead of collapsing it.
            fresh, value = self._fresh(seconds)
            if fresh:
                return value  # type: ignore[return-value]

            made = await make()
            self._held = (time.monotonic(), made)
            return made

    def clear(self) -> None:
        """Forget the held value.

        For tests, and for anything that knows the answer has changed.
        """
        self._held = None
