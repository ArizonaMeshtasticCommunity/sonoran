"""Answer #157 from the packets already on disk.

    uv run python tools/portnum_zero_census.py --hours 168

Run it where the ingest's configuration lives, because it needs the
same `SONORAN_CHANNEL_KEYS` the ingest was given. That is the only
reason this could not be run from outside the deployment: the data has
been on disk all along.

What it prints and why it is the question #157 asks is in
`sonoran/ingest/census.py`. The short version: a stored `portnum` of 0
means four different things, and the fraction of them that a channel
key opens *with an empty payload* is the false-accept rate the issue is
about. The fraction it opens *with a payload* is what the proposed fix
would throw away.

Read-only, by construction and by role: it connects as the API's
database user, which cannot write, and it issues one SELECT. That role
really can read what this needs -- revision 0001 grants `azmsh_api`
SELECT on `packet` with no column restriction, so `raw_bytes` is
included, and the statement compiles to

    SELECT packet.raw_bytes FROM packet
    WHERE packet.portnum = 0 AND packet.first_seen_at >= ...

which is a time predicate on the hypertable's partitioning column, so
it reads the window's chunks and not the history.

Nothing it prints identifies a node, a packet or a person -- counts and
payload lengths only -- so the output can go straight into the issue.
"""

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from sonoran.config import get_settings
from sonoran.crypto.decrypt import decode_key
from sonoran.db.models import Packet
from sonoran.db.session import make_engine, make_session_factory
from sonoran.ingest.census import Census, classify, report
from sonoran.ingest.pipeline import UNKNOWN_PORTNUM

# Rows fetched per round trip. This bounds memory, not the answer: the
# whole window is counted either way. A cap on how many rows are
# *considered* would let the limit decide what the evidence was, which
# is the trap in AGENTS.md 9.19.
BATCH = 2000


async def run(hours: int) -> str:
    settings = get_settings()
    keys = [decode_key(key) for key in settings.channel_keys]
    if not keys:
        raise SystemExit(
            "No channel keys are configured, so every row would read as "
            "opaque and the census would measure the configuration "
            "rather than the mesh."
        )

    since = datetime.now(UTC) - timedelta(hours=hours)
    engine = make_engine(settings.database_url_api)
    census = Census()
    try:
        factory = make_session_factory(engine)
        async with factory() as session:
            statement = (
                select(Packet.raw_bytes)
                .where(Packet.portnum == UNKNOWN_PORTNUM)
                .where(Packet.first_seen_at >= since)
                .execution_options(yield_per=BATCH)
            )
            result = await session.stream(statement)
            async for (raw,) in result:
                census.add(classify(raw, keys))
    finally:
        await engine.dispose()
    return report(census, window_hours=hours, keys_tried=len(keys))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hours",
        type=int,
        default=168,
        help="how far back to count. A week by default, which is the window "
        "the 8,841-packets-a-week figure in #157 was measured over.",
    )
    args = parser.parse_args()
    if args.hours <= 0:
        raise SystemExit("--hours must be positive")
    print(asyncio.run(run(args.hours)))


if __name__ == "__main__":
    main()
