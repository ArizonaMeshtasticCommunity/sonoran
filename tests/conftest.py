"""Fixtures shared by every test.

One job so far: stop a cached answer crossing from one test to the next.
"""

from collections.abc import Iterator

import pytest

from sonoran.api.cache import clear_all


@pytest.fixture(autouse=True)
def _empty_the_api_caches() -> Iterator[None]:
    """Give each test its own cold cache.

    `/api/stats` and the embed endpoints hold their answers in module
    globals, which live for the whole process. The holds are tens of
    seconds and a suite runs faster than that, so without this a test
    can be answered from the value an earlier test put there — and a
    stale answer does not look like a cache. It looks like the endpoint
    returning another test's data, in a test that never mentions
    caching.

    Cleared before and after, so a test that fails leaves nothing
    behind for the next one either.
    """
    clear_all()
    yield
    clear_all()
