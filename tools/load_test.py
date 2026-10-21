"""Simulate many viewers with several tabs each, against a running API (#371).

**Run it on the box under test, never on the small production box.** It
is built to load a server. On the 3 GB host it would push production
into swap, the way the test suite did on 2026-09-22. It asks for
`--i-am-not-on-production` before it sends anything.

Each tab opens one page: it loads the page's requests once, then repeats
the page's live requests every 15 s, as the browser does while the tab is
visible. A tab sends `If-None-Match` with the tag it last got, as a
browser does, so the 304s of #371 show in the result.

    python tools/load_test.py http://127.0.0.1:8000 --viewers 100 --tabs 2 \\
        --minutes 5 --i-am-not-on-production

Behind a login, pass the session cookie or header the proxy expects with
`--header 'Cookie: ...'`. It prints, per request, how many were sent,
how many failed, the share of 304s and the 50th, 95th and 99th
percentile times, and exits 1 when anything failed.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

import httpx

LIVE_SECONDS = 15.0

# What each page asks for: (on open, again every 15 s while visible).
# The paths mirror `web/static/app.js`. They need not be exact to load the
# server realistically; keep the long views and the live ones both in.
PAGES: dict[str, tuple[list[str], list[str]]] = {
    "dashboard": (
        ["/api/stats?hours=24", "/api/stats/portnums?hours=24&preset=MediumFast"],
        ["/api/chat?limit=20&preset=MediumFast"],
    ),
    "map": (
        ["/api/graph/channels?hours=24", "/api/map/nodes?channel=MediumFast&hours=32"],
        ["/api/map/traffic?minutes=15&limit=2000&channel=MediumFast"],
    ),
    "graph": (["/api/graph/channels?hours=168", "/api/graph?hours=168&channel=MediumFast"], []),
    "stats": (
        [
            "/api/stats?hours=720",
            "/api/stats/top?hours=720&limit=15",
            "/api/stats/leaderboards?channel=MediumFast&hours=720",
            "/api/stats/daily?hours=720",
            "/api/stats/hardware?hours=720",
            "/api/stats/activity?hours=720",
            "/api/stats/broadcast?hours=720&limit=40",
        ],
        [],
    ),
    "coverage": (["/api/coverage", "/api/map/nodes?channel=MediumFast&hours=168"], []),
    "firehose": ([], ["/api/packets?limit=150&summary=true&preset=MediumFast"]),
    "nodes": ([], ["/api/nodes?limit=100&sort=last_heard&order=desc&active_hours=24"]),
}


@dataclass
class Results:
    """Times and outcomes per request path, without its query string."""

    times: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    failed: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    not_modified: dict[str, int] = field(default_factory=lambda: defaultdict(int))


async def _get(client: httpx.AsyncClient, url: str, tags: dict[str, str], out: Results) -> None:
    name = url.split("?")[0]
    headers = {"If-None-Match": tags[url]} if url in tags else {}
    started = time.perf_counter()
    try:
        response = await client.get(url, headers=headers)
    except httpx.HTTPError:
        out.failed[name] += 1
        return
    out.times[name].append(time.perf_counter() - started)
    if response.status_code == 304:
        out.not_modified[name] += 1
    elif response.status_code >= 400:
        out.failed[name] += 1
    if "etag" in response.headers:
        tags[url] = response.headers["etag"]


async def _tab(client: httpx.AsyncClient, page: str, until: float, out: Results) -> None:
    opened, live = PAGES[page]
    tags: dict[str, str] = {}
    # Tabs do not open in step; spread them over the first live interval.
    await asyncio.sleep(random.uniform(0, LIVE_SECONDS))
    await asyncio.gather(*(_get(client, url, tags, out) for url in opened + live))
    while live and time.monotonic() < until:
        await asyncio.sleep(LIVE_SECONDS)
        await asyncio.gather(*(_get(client, url, tags, out) for url in live))


def _report(out: Results) -> bool:
    failed = False
    print(f"{'request':45} {'sent':>6} {'fail':>5} {'304':>5} {'p50':>7} {'p95':>7} {'p99':>7}")
    for name in sorted(set(out.times) | set(out.failed)):
        times = sorted(out.times.get(name, []))
        sent = len(times) + out.failed.get(name, 0)
        failed = failed or out.failed.get(name, 0) > 0

        def pct(q: float, times: list[float] = times) -> str:
            return f"{times[min(len(times) - 1, int(q * len(times)))]:.2f}s" if times else "-"

        share = out.not_modified.get(name, 0) / len(times) if times else 0.0
        print(
            f"{name:45} {sent:6d} {out.failed.get(name, 0):5d} {share:5.0%} "
            f"{pct(0.5):>7} {pct(0.95):>7} {pct(0.99):>7}"
        )
    every = [value for times in out.times.values() for value in times]
    if every:
        print(f"all: {len(every)} answered, median {statistics.median(every):.2f}s")
    return not failed


async def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("base", help="the API's base URL, such as http://127.0.0.1:8000")
    parser.add_argument("--viewers", type=int, default=100)
    parser.add_argument("--tabs", type=int, default=2, help="tabs each viewer keeps open")
    parser.add_argument("--minutes", type=float, default=5.0)
    parser.add_argument("--header", action="append", default=[], help="'Name: value', repeatable")
    parser.add_argument("--i-am-not-on-production", action="store_true", dest="confirmed")
    args = parser.parse_args(argv)
    if not args.confirmed:
        print("Refused: pass --i-am-not-on-production. Never load the small production box.")
        return 2
    headers = dict(item.split(":", 1) for item in args.header)
    headers = {name.strip(): value.strip() for name, value in headers.items()}
    until = time.monotonic() + args.minutes * 60
    out = Results()
    pages = list(PAGES)
    limits = httpx.Limits(max_connections=args.viewers * args.tabs)
    async with httpx.AsyncClient(
        base_url=args.base, headers=headers, timeout=60.0, limits=limits
    ) as client:
        await asyncio.gather(
            *(
                _tab(client, random.choice(pages), until, out)
                for _ in range(args.viewers * args.tabs)
            )
        )
    return 0 if _report(out) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
