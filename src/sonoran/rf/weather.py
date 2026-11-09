"""Weather readings from RF observations, in one set of units.

Two kinds of observation carry weather, and each names it differently:

- An APRS weather report (`aprs`). The agent decodes it and writes
  `temperature_f`, `wind_kn`, `gust_kn`, `rain_1h_in` and so on into
  `meta`. APRS sends wind in miles per hour (APRS Protocol Reference
  1.0.1, chapter 12, "Weather Data"); the agent turns it into knots.
- A 433 or 915 MHz sensor heard by rtl_433 (`ism`). The agent lifts some
  fields into `meta` (`temperature_c`, `humidity`, `rain_mm`) and keeps
  the whole rtl_433 line in `meta.raw`. The field names and units are
  rtl_433's (rtl_433 `docs/DATA_FORMAT.md`, "Common keys"; the WH24 in
  `src/devices/fineoffset.c`): `temperature_C`, `wind_avg_m_s`,
  `wind_max_m_s`, `rain_mm`, `uvi`, `light_lux`. The agent does not lift
  the wind, UV or light of a WH24, so they are read from `raw`.

`readings()` turns either into one dict in SI units, so the page
converts once, to the reader's units. A field that is absent stays
absent: a missing wind is never a calm.

A sensor's `rain_mm` is a running total since the sensor was powered,
not a day's rain (rtl_433 `docs/DATA_FORMAT.md`, `rain_mm`: "rain total
in mm"). `rain_since()` adds up its rises over a span, so the page can
say how much fell since midnight.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

# 1 knot = 1852 m per hour (the international nautical mile, BIPM SI
# Brochure, 9th edition, table 8).
MS_PER_KNOT = 1852 / 3600
MM_PER_INCH = 25.4

# The readings the page knows, in the order a card lists them.
FIELDS = (
    "temperature_c",
    "humidity",
    "pressure_hpa",
    "wind_dir_deg",
    "wind_ms",
    "gust_ms",
    "rain_total_mm",
    "rain_1h_mm",
    "rain_24h_mm",
    "rain_today_mm",
    "uvi",
    "light_lux",
    "solar_wm2",
)

# A reading the sensor sends but that says nothing about the weather.
# A thing that has only these is not a weather source.
NOT_WEATHER = frozenset({"battery_ok"})


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _raw(meta: Mapping[str, object]) -> Mapping[str, object]:
    """The rtl_433 line of an `ism` observation, or nothing."""
    raw = meta.get("raw")
    if not isinstance(raw, str) or not raw.startswith("{"):
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def readings(kind: str, meta: Mapping[str, object] | None) -> dict[str, float | bool]:
    """The weather in one observation, in SI units. Empty when there is none."""
    meta = meta or {}
    raw = _raw(meta) if kind == "ism" else {}
    out: dict[str, float | bool] = {}

    def first(*options: tuple[Mapping[str, object], str, float, float]) -> float | None:
        """The first present option, as `value * scale + offset`."""
        for source, key, scale, offset in options:
            value = _number(source.get(key))
            if value is not None:
                return value * scale + offset
        return None

    found = {
        "temperature_c": first(
            (meta, "temperature_c", 1, 0),
            (meta, "temperature_f", 5 / 9, -32 * 5 / 9),
            (raw, "temperature_C", 1, 0),
            (raw, "temperature_F", 5 / 9, -32 * 5 / 9),
        ),
        "humidity": first((meta, "humidity", 1, 0), (raw, "humidity", 1, 0)),
        "pressure_hpa": first((meta, "pressure_hpa", 1, 0), (raw, "pressure_hPa", 1, 0)),
        "wind_dir_deg": first((meta, "wind_dir_deg", 1, 0), (raw, "wind_dir_deg", 1, 0)),
        "wind_ms": first(
            (meta, "wind_kn", MS_PER_KNOT, 0),
            (meta, "wind_avg_kmh", 1 / 3.6, 0),
            (raw, "wind_avg_m_s", 1, 0),
            (raw, "wind_avg_km_h", 1 / 3.6, 0),
        ),
        "gust_ms": first(
            (meta, "gust_kn", MS_PER_KNOT, 0),
            (meta, "wind_max_kmh", 1 / 3.6, 0),
            (raw, "wind_max_m_s", 1, 0),
            (raw, "wind_max_km_h", 1 / 3.6, 0),
        ),
        "rain_total_mm": first(
            (meta, "rain_mm", 1, 0), (raw, "rain_mm", 1, 0), (raw, "rain_in", MM_PER_INCH, 0)
        ),
        "rain_1h_mm": first((meta, "rain_1h_in", MM_PER_INCH, 0)),
        "rain_24h_mm": first((meta, "rain_24h_in", MM_PER_INCH, 0)),
        "rain_today_mm": first((meta, "rain_today_in", MM_PER_INCH, 0)),
        "uvi": first((meta, "uvi", 1, 0), (raw, "uvi", 1, 0)),
        "light_lux": first((raw, "light_lux", 1, 0)),
        "solar_wm2": first((meta, "luminosity_wm2", 1, 0)),
    }
    # Values a sensor cannot mean. A relative humidity is 0 to 100 %,
    # a direction 0 to 360°, and no speed, rain, light or UV is negative.
    if found["humidity"] is not None and not 0 <= found["humidity"] <= 100:
        found["humidity"] = None
    if found["wind_dir_deg"] is not None and not 0 <= found["wind_dir_deg"] <= 360:
        found["wind_dir_deg"] = None
    for key in (
        "wind_ms",
        "gust_ms",
        "rain_total_mm",
        "rain_1h_mm",
        "rain_24h_mm",
        "rain_today_mm",
        "uvi",
        "light_lux",
        "solar_wm2",
    ):
        if found[key] is not None and found[key] < 0:  # type: ignore[operator]
            found[key] = None
    out.update({key: value for key, value in found.items() if value is not None})
    if not out:
        return {}
    battery = meta.get("battery_ok", raw.get("battery_ok"))
    if battery is not None and battery != "":
        out["battery_ok"] = battery not in (False, 0, "0")
    return out


def is_weather(values: Mapping[str, object]) -> bool:
    return any(key not in NOT_WEATHER for key in values)


def rain_since(totals: Iterable[float]) -> float | None:
    """The rain that fell over a run of a sensor's running totals, oldest first.

    The sum of every rise. A fall means the total started again (new
    batteries), so that step adds nothing: the rain in it is unknown,
    and adding the new total would count rain from before the span.
    None when there are fewer than two readings, because one reading
    says nothing about how much fell.
    """
    total = 0.0
    previous: float | None = None
    count = 0
    for value in totals:
        count += 1
        if previous is not None and value > previous:
            total += value - previous
        previous = value
    return total if count >= 2 else None


@dataclass
class _Bucket:
    sums: dict[str, float]
    counts: dict[str, int]
    gust: float | None = None
    rain_today: float | None = None
    east: float = 0.0
    north: float = 0.0
    winds: int = 0


def bucket_minutes(hours: int) -> int:
    """How long one chart point is. About 300 points for any window.

    A sensor can send every 16 s, which is 10,800 points over 48 hours:
    more than a phone draws smoothly, and far more than the chart's width
    in pixels. Five minutes for a day and ten for two keep each window
    near 300 points.
    """
    return 5 if hours <= 24 else 10


AVERAGED = ("temperature_c", "humidity", "pressure_hpa", "wind_ms", "uvi", "light_lux", "solar_wm2")


def series(
    points: Iterable[tuple[datetime, Mapping[str, float | bool]]],
    start: datetime,
    minutes: int,
) -> list[dict[str, object]]:
    """Readings, oldest first, as one point per bucket of `minutes`.

    Each bucket holds the mean of every averaged reading in it, the
    highest gust, the wind direction as a mean of vectors (so 350° and
    10° make north, not south), and two kinds of rain: `rain_mm`, the
    rain since the start of the window from a sensor's running total,
    and `rain_today_mm`, the last total an APRS station sent.
    A bucket with nothing in it is left out, so a gap stays a gap.
    """
    width = timedelta(minutes=minutes)
    buckets: dict[datetime, _Bucket] = {}
    rain = 0.0
    previous_total: float | None = None
    rain_at: dict[datetime, float] = {}
    for when, values in points:
        key = start + width * ((when - start) // width)
        bucket = buckets.setdefault(key, _Bucket(sums={}, counts={}))
        for field in AVERAGED:
            value = values.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                bucket.sums[field] = bucket.sums.get(field, 0.0) + value
                bucket.counts[field] = bucket.counts.get(field, 0) + 1
        gust = values.get("gust_ms")
        if isinstance(gust, (int, float)) and not isinstance(gust, bool):
            bucket.gust = gust if bucket.gust is None else max(bucket.gust, gust)
        direction = values.get("wind_dir_deg")
        if isinstance(direction, (int, float)) and not isinstance(direction, bool):
            speed = values.get("wind_ms")
            # Weighted by speed, so a calm's meaningless vane does not
            # pull the mean; a sensor that sends no speed counts each
            # reading once.
            weight = speed if isinstance(speed, (int, float)) and speed > 0 else 1.0
            bucket.east += weight * math.sin(math.radians(direction))
            bucket.north += weight * math.cos(math.radians(direction))
            bucket.winds += 1
        today = values.get("rain_today_mm")
        if isinstance(today, (int, float)) and not isinstance(today, bool):
            bucket.rain_today = today
        total = values.get("rain_total_mm")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            if previous_total is not None and total > previous_total:
                rain += total - previous_total
            previous_total = total
            rain_at[key] = rain
    out: list[dict[str, object]] = []
    for key in sorted(buckets):
        bucket = buckets[key]
        point: dict[str, object] = {"t": key}
        for field in AVERAGED:
            if bucket.counts.get(field):
                point[field] = round(bucket.sums[field] / bucket.counts[field], 3)
        if bucket.gust is not None:
            point["gust_ms"] = round(bucket.gust, 3)
        if bucket.winds:
            point["wind_dir_deg"] = round(
                math.degrees(math.atan2(bucket.east, bucket.north)) % 360, 1
            )
        if key in rain_at:
            point["rain_mm"] = round(rain_at[key], 3)
        if bucket.rain_today is not None:
            point["rain_today_mm"] = round(bucket.rain_today, 3)
        out.append(point)
    return out
