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
