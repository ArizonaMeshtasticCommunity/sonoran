"""Tests for the settings module."""

from sonoran.config import DEFAULT_CHANNEL_KEY, Settings


def test_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.mqtt_topics == ["msh/US/AZ/#"]
    assert settings.channel_keys == [DEFAULT_CHANNEL_KEY]
    assert settings.store_text_messages is False
    assert settings.retention_days_packet == 30


def test_csv_split_for_lists(monkeypatch: object) -> None:
    import os

    os.environ["MQTT_TOPICS"] = "msh/US/AZ/#, msh/US/#"
    os.environ["CHANNEL_KEYS"] = "a2V5MQ==, a2V5Mg=="
    try:
        settings = Settings(_env_file=None)
        assert settings.mqtt_topics == ["msh/US/AZ/#", "msh/US/#"]
        assert settings.channel_keys == ["a2V5MQ==", "a2V5Mg=="]
    finally:
        del os.environ["MQTT_TOPICS"]
        del os.environ["CHANNEL_KEYS"]
