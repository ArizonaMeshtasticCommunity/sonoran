"""Where our presets sit in the band, as the firmware computes it (design 7.4)."""

from sonoran.radio.channels import all_channels, channel_for, djb2
from sonoran.radio.presets import preset_by_key


def test_the_hash_is_the_firmware_djb2() -> None:
    assert djb2("") == 5381
    assert djb2("a") == 5381 * 33 + ord("a")


def test_the_published_us_frequencies_come_out() -> None:
    """LongFast 906.875 MHz and MediumFast 913.125 MHz are the known US defaults."""
    long_fast = channel_for(preset_by_key("LONG_FAST"))  # type: ignore[arg-type]
    medium_fast = channel_for(preset_by_key("MEDIUM_FAST"))  # type: ignore[arg-type]
    assert (long_fast.slot, long_fast.slots, long_fast.centre_hz) == (19, 104, 906_875_000)
    assert medium_fast.centre_hz == 913_125_000
    assert long_fast.low_hz == 906_750_000 and long_fast.high_hz == 907_000_000


def test_every_channel_is_inside_the_us_band() -> None:
    for channel in all_channels():
        assert 902_000_000 <= channel.low_hz < channel.high_hz <= 928_000_000, channel.name


def test_a_custom_slot_is_numbered_from_one_as_the_app_numbers_it() -> None:
    """`MediumFast:18` is channel_num 18, slot index 17, as the frequency
    slot calculator (heypete/meshtastic_frequency_slot_calculator) has it."""
    from sonoran.radio.channels import custom_channel

    slot18 = custom_channel("MediumFast:18")
    assert slot18.centre_hz == 906_375_000
    assert (slot18.low_hz, slot18.high_hz) == (906_250_000, 906_500_000)
    assert slot18.custom and slot18.name == "MediumFast slot 18"
    # Slot 45 is MediumFast's own default: the two rules agree.
    assert custom_channel("mediumfast:45").centre_hz == 913_125_000
    assert custom_channel("LongFast:20").centre_hz == 906_875_000


def test_a_bad_custom_slot_is_refused() -> None:
    import pytest

    from sonoran.radio.channels import custom_channel

    for bad in ("MediumFast", "Nope:3", "MediumFast:0", "MediumFast:105", "MediumFast:x"):
        with pytest.raises(ValueError):
            custom_channel(bad)


def test_a_bad_custom_channel_setting_stops_the_api_at_start() -> None:
    import pytest
    from pydantic import ValidationError

    from sonoran.config import Settings

    assert Settings(_env_file=None, rf_custom_channels="MediumFast:18").rf_custom_channels == [
        "MediumFast:18"
    ]
    with pytest.raises(ValidationError, match="slots 1 to 104"):
        Settings(_env_file=None, rf_custom_channels="MediumFast:200")


def test_the_channels_api_lists_custom_slots_beside_the_defaults() -> None:
    from fastapi.testclient import TestClient

    from sonoran.api.app import create_app
    from sonoran.config import Settings

    settings = Settings(_env_file=None, rf_custom_channels="MediumFast:18")
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/rf/channels").json()
    by_name = {c["name"]: c for c in body["channels"]}
    assert by_name["MediumFast slot 18"]["centre_hz"] == 906_375_000
    assert by_name["MediumFast slot 18"]["custom"] is True
    assert by_name["MediumFast"]["custom"] is False
    centres = [c["centre_hz"] for c in body["channels"]]
    assert centres == sorted(centres), "lowest frequency first"
