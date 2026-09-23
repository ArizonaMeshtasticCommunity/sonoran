"""A telemetry field the node did not send is not a reading of zero (#190).

Meshtastic marks its telemetry fields `optional`, so the protobuf
tracks presence per field. `store_telemetry` checked `HasField` for the
*message* and then copied every *field* without a check, so an absent
field's default landed in the database as a real number.

A node with a temperature-and-humidity sensor and nothing else was
stored as reporting a barometric pressure of 0 hPa. That is not a low
reading; it is not a pressure at all. The Weather panel drew it, a
missing battery read as 0%, and the node page averaged those zeros into
everyone else's figures.

Measured on the live database over seven days before the fix:

    environment rows            5,811
      barometric_pressure = 0   2,642  (45%)
      barometric_pressure NULL      0
    device rows                17,713
      voltage = 0               1,255
      voltage NULL                  0

**Not one NULL in either column.** With per-field presence working,
some node somewhere would have to be missing something.

This is the fourth instance of one pattern in this repository -- #157
(portnum 0 is both a real port and a sentinel), #149 (an unmeasured
link labelled weak), #197 (role 0 is CLIENT, stored as NULL), and now a
default read as a measurement. The shape each time: **a value that
means "absent" sharing storage with a value that means something.**
"""

from typing import Any

import pytest

from sonoran.ingest.handlers.telemetry import _reported
from sonoran.meshtastic import telemetry_pb2


def _environment(**fields: Any) -> Any:
    return telemetry_pb2.EnvironmentMetrics(**fields)  # type: ignore[attr-defined]


def _device(**fields: Any) -> Any:
    return telemetry_pb2.DeviceMetrics(**fields)  # type: ignore[attr-defined]


def test_a_sensor_the_node_does_not_have_is_none() -> None:
    """The reported bug, as the packet that produced it.

    Megaton [CoA] sends temperature and humidity. Everything else came
    back as zero and was drawn as a reading.
    """
    stored = _reported(
        _environment(temperature=37.1, relative_humidity=28.5),
        temperature="temperature",
        relative_humidity="relative_humidity",
        barometric_pressure="barometric_pressure",
        iaq="iaq",
        gas_resistance="gas_resistance",
    )
    assert stored["temperature"] == pytest.approx(37.1)
    assert stored["relative_humidity"] == pytest.approx(28.5)
    assert stored["barometric_pressure"] is None, "0 hPa is not a pressure"
    assert stored["iaq"] is None
    assert stored["gas_resistance"] is None


def test_a_real_zero_is_kept() -> None:
    """The half that keeps the fix honest.

    Zero is a legitimate reading for most of these. A node at freezing
    reports 0 °C, a flat battery reports 0%, and a dry hour reports 0
    rainfall. Turning every zero into None would be a different lie in
    place of the old one -- and it is the obvious wrong implementation,
    so it is tested first-class rather than assumed away.
    """
    stored = _reported(
        _environment(temperature=0.0, rainfall_1h=0.0),
        temperature="temperature",
        rainfall="rainfall_1h",
    )
    assert stored["temperature"] == 0.0, "a node at freezing reported a temperature"
    assert stored["rainfall"] == 0.0, "a dry hour is a measurement, not a silence"


def test_a_flat_battery_is_not_a_missing_battery() -> None:
    """`battery_level=0` explicitly set must survive."""
    assert _reported(_device(battery_level=0), battery_level="battery_level")["battery_level"] == 0
    assert _reported(_device(voltage=4.1), battery_level="battery_level")["battery_level"] is None


def test_the_column_name_may_differ_from_the_field_name() -> None:
    """`rainfall` is stored from `rainfall_1h`.

    The mapping exists precisely so this pair cannot drift, and getting
    it wrong would raise rather than silently store the wrong thing.
    """
    assert _reported(_environment(rainfall_1h=2.5), rainfall="rainfall_1h")["rainfall"] == (
        pytest.approx(2.5)
    )


def test_a_field_hasfield_refuses_keeps_its_value() -> None:
    """`HasField` raises for a repeated field, and that must not crash.

    `one_wire_temperature` is repeated in the vendored schema, and a
    repeated field has no presence to ask about -- empty already *is*
    its absent state, so there is nothing to tell apart. None of these
    are stored today; the branch exists so that adding one cannot take
    the ingest down with a ValueError.

    The first version of this case asserted `== 0.0`, assuming a field
    `HasField` refuses must be a scalar without presence. It is a list.
    The code was right and the expectation was wrong.
    """
    stored = _reported(_environment(temperature=1.0), one_wire_temperature="one_wire_temperature")
    assert list(stored["one_wire_temperature"]) == []


def test_the_field_that_refuses_really_does_refuse() -> None:
    """Positive control for the case above.

    If `one_wire_temperature` ever stopped raising, the test above
    would quietly stop exercising the `except ValueError` branch and
    start asserting something else entirely.
    """
    with pytest.raises(ValueError):
        _environment().HasField("one_wire_temperature")


def test_every_field_this_handler_stores_supports_presence() -> None:
    """The invariant the fix rests on, checked against the real schema.

    If a stored field ever loses presence tracking, it silently returns
    to storing false zeros. This names them rather than trusting the
    issue's claim that they are all `optional`.
    """
    stored_fields = {
        telemetry_pb2.EnvironmentMetrics: (  # type: ignore[attr-defined]
            "temperature",
            "relative_humidity",
            "barometric_pressure",
            "gas_resistance",
            "iaq",
            "lux",
            "uv_lux",
            "wind_direction",
            "wind_speed",
            "rainfall_1h",
        ),
        telemetry_pb2.DeviceMetrics: (  # type: ignore[attr-defined]
            "battery_level",
            "voltage",
            "channel_utilization",
            "air_util_tx",
            "uptime_seconds",
        ),
        telemetry_pb2.AirQualityMetrics: (  # type: ignore[attr-defined]
            "pm10_standard",
            "pm25_standard",
            "pm100_standard",
            "pm10_environmental",
            "pm25_environmental",
            "pm100_environmental",
        ),
        telemetry_pb2.PowerMetrics: (  # type: ignore[attr-defined]
            "ch1_voltage",
            "ch1_current",
            "ch2_voltage",
            "ch2_current",
            "ch3_voltage",
            "ch3_current",
        ),
    }
    for message_type, fields in stored_fields.items():
        instance = message_type()
        for name in fields:
            instance.HasField(name)  # raises if presence was lost
