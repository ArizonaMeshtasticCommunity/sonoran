"""The per-bin summary of the 900 MHz band, shared by the API and the jobs.

A waterfall row covers one or more minutes. Each bin keeps the median of
its minute medians (the noise floor), the highest 95th percentile, so a
burst is never averaged away, the mean busy share, and the loudest
single moment (`peak`) with how many minutes into the row it happened,
so a short transmission is never lost and can be found again. The API
builds rows this way from minutes for windows up to a day, and the
hourly rollup job (`jobs/rf_rollup.py`) builds hours the same way, so a
row means the same thing in every window.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, DateTime, Integer, Select, case, cast, func, select, true
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by

from sonoran.db.models import RfSpectrum


def bin_rows(bucket: ColumnElement[Any], *where: ColumnElement[bool]) -> Select[Any]:
    """Return one row per bucket, oldest first:

    (bucket, p50[], p95[], busy[], minutes, peak[], peak_min[])

    `bucket` groups minutes, such as `time_bucket('1 hour', t)`. `where`
    picks the minutes: one station, one bin layout, a time range.
    `peak_min` is the minute, counted from the start of the row, in which
    each bin was loudest; None where the bin was never swept.
    """
    bins_of = (
        func.unnest(RfSpectrum.p50, RfSpectrum.p95, RfSpectrum.busy, RfSpectrum.peak)
        .table_valued("p50", "p95", "busy", "peak", with_ordinality="i")
        .render_derived()
    )
    labelled = bucket.label("bucket")
    # When each bin was loudest: the time of its highest peak. Ties go to
    # the earliest minute.
    peak_at = func.array_agg(
        aggregate_order_by(RfSpectrum.t, bins_of.c.peak.desc().nulls_last(), RfSpectrum.t),
        type_=ARRAY(DateTime(timezone=True)),
    )[1]
    per_bin = (
        select(
            labelled,
            bins_of.c.i,
            func.percentile_disc(0.5).within_group(bins_of.c.p50).label("p50"),
            func.max(bins_of.c.p95).label("p95"),
            func.round(func.avg(bins_of.c.busy)).label("busy"),
            func.count().label("minutes"),
            func.max(bins_of.c.peak).label("peak"),
            peak_at.label("peak_at"),
        )
        .select_from(RfSpectrum)
        .join(bins_of, true())
        .where(*where)
        .group_by(labelled, bins_of.c.i)
        .subquery()
    )
    # Worked out here, where the row's start is a plain column: repeating
    # the bucket expression inside the grouped query would not match it.
    peak_min = case(
        (per_bin.c.peak.is_(None), None),
        else_=cast(
            func.floor(func.extract("epoch", per_bin.c.peak_at - per_bin.c.bucket) / 60), Integer
        ),
    )
    return (
        select(
            per_bin.c.bucket,
            func.array_agg(aggregate_order_by(per_bin.c.p50, per_bin.c.i)),
            func.array_agg(aggregate_order_by(per_bin.c.p95, per_bin.c.i)),
            func.array_agg(aggregate_order_by(per_bin.c.busy, per_bin.c.i)),
            func.max(per_bin.c.minutes),
            func.array_agg(aggregate_order_by(per_bin.c.peak, per_bin.c.i)),
            func.array_agg(aggregate_order_by(peak_min, per_bin.c.i)),
        )
        .group_by(per_bin.c.bucket)
        .order_by(per_bin.c.bucket)
    )
