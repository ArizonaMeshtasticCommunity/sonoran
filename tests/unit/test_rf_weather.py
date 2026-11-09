"""Weather from RF observations: one set of units, from two kinds of sender.

The samples are real: a Fine Offset WH24 heard by rtl_433 at station
kiwa, and the APRS weather station KC9UHI-13, both as main stored them
on 2026-11-08.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from sonoran.rf.weather import bucket_minutes, is_weather, rain_since, readings, series

WH24_RAW = (
    '{"time":"2026-11-08T14:17:24.174687-0700","model":"Fineoffset-WH24","id":200,'
    '"battery_ok":1,"temperature_C":27.2,"humidity":33,"wind_dir_deg":86,'
    '"wind_avg_m_s":3.92,"wind_max_m_s":5.6,"rain_mm":781.20001,"uv":1084,"uvi":2.0,'
    '"light_lux":41775.0,"mic":"CRC"}'
)
# What the agent lifted into meta beside `raw`: no wind speed, UV or light.
WH24_META = {
    "id": 200,
    "raw": WH24_RAW,
    "model": "Fineoffset-WH24",
    "rain_mm": 781.20001,
    "humidity": 33,
    "battery_ok": 1,
    "wind_dir_deg": 86,
    "temperature_c": 27.2,
}
APRS_META = {
    "raw": "KC9UHI-13>APWEE5,TCPIP,N7GEE-10*:@301728z3208.88N/11055.31W_263/003g007t073"
    "r000p021P002h58b10068 wx.kc9uhi.net",
    "symbol": "/_",
    "gust_kn": 6.08,
    "wind_kn": 2.6,
    "humidity": 58,
    "rain_1h_in": 0.0,
    "rain_24h_in": 0.21,
    "pressure_hpa": 1006.8,
    "wind_dir_deg": 263,
    "rain_today_in": 0.02,
    "temperature_f": 73,
}


def test_a_wh24_gives_its_wind_uv_and_light_from_the_raw_line() -> None:
    """The agent lifts only some fields. The rest are in rtl_433's own line."""
    got = readings("ism", WH24_META)
    assert got["temperature_c"] == 27.2
    assert got["humidity"] == 33
    assert got["wind_dir_deg"] == 86
    assert got["wind_ms"] == 3.92, "wind_avg_m_s is already metres per second"
    assert got["gust_ms"] == 5.6
    assert got["rain_total_mm"] == pytest.approx(781.2)
    assert got["uvi"] == 2.0
    assert got["light_lux"] == 41775.0
    assert got["battery_ok"] is True


def test_an_aprs_report_is_converted_from_its_own_units() -> None:
    got = readings("aprs", APRS_META)
    assert got["temperature_c"] == pytest.approx((73 - 32) * 5 / 9)
    # 2.6 kn is 3 mph on the air (APRS sends mph; the agent sent knots).
    assert got["wind_ms"] == pytest.approx(2.6 * 1852 / 3600)
    assert got["gust_ms"] == pytest.approx(6.08 * 1852 / 3600)
    assert got["pressure_hpa"] == 1006.8
    assert got["rain_today_mm"] == pytest.approx(0.02 * 25.4)
    assert got["rain_24h_mm"] == pytest.approx(0.21 * 25.4)
    assert "rain_total_mm" not in got, "APRS sends no running total"


def test_an_aprs_raw_line_is_never_read_as_rtl_433() -> None:
    """Only an `ism` observation has an rtl_433 line in `raw`."""
    meta = {"raw": json.dumps({"temperature_C": 99, "wind_avg_m_s": 50})}
    assert readings("aprs", meta) == {}
    assert readings("ism", meta)["temperature_c"] == 99


def test_a_missing_reading_stays_missing_and_zero_stays_zero() -> None:
    got = readings("aprs", {"wind_kn": 0, "temperature_f": None, "humidity": ""})
    assert got == {"wind_ms": 0.0}, "a calm is 0; no temperature is no temperature"


def test_a_reading_a_sensor_cannot_mean_is_dropped() -> None:
    got = readings(
        "ism", {"humidity": 140, "wind_dir_deg": 400, "rain_mm": -3, "temperature_c": 20}
    )
    assert got == {"temperature_c": 20}


def test_a_broken_raw_line_is_ignored_not_fatal() -> None:
    assert readings("ism", {"raw": "{not json", "temperature_c": 5}) == {"temperature_c": 5}
    assert readings("ism", {"raw": "[1, 2]"}) == {}


def test_an_aprs_position_with_no_weather_is_not_a_weather_source() -> None:
    plain = readings("aprs", {"symbol": "/>", "comment": "mobile", "battery_ok": True})
    assert not is_weather(plain)
    assert is_weather(readings("aprs", APRS_META))


def test_rain_since_adds_the_rises_of_a_running_total() -> None:
    assert rain_since([781.2, 781.2, 781.5, 782.0]) == pytest.approx(0.8)


def test_new_batteries_do_not_count_as_rain() -> None:
    """A total that starts again from 0 is not 781 mm of rain."""
    assert rain_since([781.2, 781.5, 0.0, 0.3]) == pytest.approx(0.6)


def test_one_reading_says_nothing_about_rain() -> None:
    assert rain_since([781.2]) is None
    assert rain_since([]) is None
    assert rain_since([781.2, 781.2]) == 0.0


def test_a_naive_difference_of_last_and_first_would_be_caught() -> None:
    """Last minus first is wrong across a battery change: here it is -780.9."""
    totals = [781.2, 781.5, 0.0, 0.3]
    assert totals[-1] - totals[0] < 0
    assert rain_since(totals) == pytest.approx(0.6)


START = datetime(2026, 11, 8, 0, 0, tzinfo=UTC)


def test_series_averages_each_bucket_and_keeps_the_highest_gust() -> None:
    points = [
        (START + timedelta(minutes=1), {"temperature_c": 20.0, "wind_ms": 1.0, "gust_ms": 3.0}),
        (START + timedelta(minutes=3), {"temperature_c": 22.0, "wind_ms": 3.0, "gust_ms": 7.0}),
        (START + timedelta(minutes=6), {"temperature_c": 25.0, "gust_ms": 2.0}),
    ]
    out = series(points, START, 5)
    assert [p["t"] for p in out] == [START, START + timedelta(minutes=5)]
    assert out[0]["temperature_c"] == 21.0
    assert out[0]["wind_ms"] == 2.0
    assert out[0]["gust_ms"] == 7.0, "a gust is the highest, never the mean"
    assert out[1] == {"t": START + timedelta(minutes=5), "temperature_c": 25.0, "gust_ms": 2.0}


def test_series_leaves_an_empty_bucket_out() -> None:
    points = [
        (START, {"temperature_c": 20.0}),
        (START + timedelta(minutes=30), {"temperature_c": 21.0}),
    ]
    assert len(series(points, START, 5)) == 2, "a gap in reception stays a gap"


def test_wind_direction_is_a_mean_of_vectors() -> None:
    """350° and 10° average to north. A plain mean says 180°, the opposite."""
    points = [
        (START, {"wind_dir_deg": 350.0, "wind_ms": 2.0}),
        (START + timedelta(minutes=1), {"wind_dir_deg": 10.0, "wind_ms": 2.0}),
    ]
    (point,) = series(points, START, 5)
    assert point["wind_dir_deg"] in (0.0, 360.0)


def test_series_rain_is_the_rain_since_the_window_began() -> None:
    points = [
        (START, {"rain_total_mm": 781.2}),
        (START + timedelta(minutes=6), {"rain_total_mm": 781.5}),
        (START + timedelta(minutes=11), {"rain_total_mm": 0.0}),
        (START + timedelta(minutes=16), {"rain_total_mm": 0.4}),
    ]
    assert [round(p["rain_mm"], 3) for p in series(points, START, 5)] == [0.0, 0.3, 0.3, 0.7]


def test_an_aprs_days_rain_is_the_last_one_it_sent() -> None:
    points = [
        (START, {"rain_today_mm": 0.5}),
        (START + timedelta(minutes=2), {"rain_today_mm": 0.8}),
    ]
    (point,) = series(points, START, 5)
    assert point["rain_today_mm"] == 0.8
    assert "rain_mm" not in point


def test_a_window_is_about_300_points() -> None:
    assert 24 * 60 // bucket_minutes(24) == 288
    assert 48 * 60 // bucket_minutes(48) == 288
