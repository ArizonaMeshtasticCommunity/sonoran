"""The per-bin summary of the 900 MHz band, shared by the API and the jobs.

A waterfall row covers one or more minutes. Each bin keeps the median of
its minute medians (the noise floor), the highest 95th percentile, so a
burst is never averaged away, and the mean busy share. The API builds
rows this way from minutes for windows up to a day, and the hourly
rollup job (`jobs/rf_rollup.py`) builds hours the same way, so a row
means the same thing in every window.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, Select, func, select, true
from sqlalchemy.dialects.postgresql import aggregate_order_by

from sonoran.db.models import RfSpectrum


def bin_rows(bucket: ColumnElement[Any], *where: ColumnElement[bool]) -> Select[Any]:
    """Return (bucket, p50[], p95[], busy[], minutes) per bucket, oldest first.

    `bucket` groups minutes, such as `time_bucket('1 hour', t)`. `where`
    picks the minutes: one station, one bin layout, a time range.
    """
    bins_of = (
        func.unnest(RfSpectrum.p50, RfSpectrum.p95, RfSpectrum.busy)
        .table_valued("p50", "p95", "busy", with_ordinality="i")
        .render_derived()
    )
    labelled = bucket.label("bucket")
    per_bin = (
        select(
            labelled,
            bins_of.c.i,
            func.percentile_disc(0.5).within_group(bins_of.c.p50).label("p50"),
            func.max(bins_of.c.p95).label("p95"),
            func.round(func.avg(bins_of.c.busy)).label("busy"),
            func.count().label("minutes"),
        )
        .select_from(RfSpectrum)
        .join(bins_of, true())
        .where(*where)
        .group_by(labelled, bins_of.c.i)
        .subquery()
    )
    return (
        select(
            per_bin.c.bucket,
            func.array_agg(aggregate_order_by(per_bin.c.p50, per_bin.c.i)),
            func.array_agg(aggregate_order_by(per_bin.c.p95, per_bin.c.i)),
            func.array_agg(aggregate_order_by(per_bin.c.busy, per_bin.c.i)),
            func.max(per_bin.c.minutes),
        )
        .group_by(per_bin.c.bucket)
        .order_by(per_bin.c.bucket)
    )
