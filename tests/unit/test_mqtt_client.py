"""Tests for MQTT client configuration."""

from unittest.mock import Mock, patch

import aiomqtt

from sonoran.config import Settings
from sonoran.mqtt.client import create_client


def test_create_client_uses_explicit_broker_protocol() -> None:
    """The client uses MQTT 3.1.1 with a clean, unique session."""
    settings = Settings(_env_file=None, mqtt_host="broker.example", mqtt_port=1883)
    client_class = Mock()

    with patch("sonoran.mqtt.client.aiomqtt.Client", client_class):
        create_client(settings)

    kwargs = client_class.call_args.kwargs
    assert kwargs["hostname"] == "broker.example"
    assert kwargs["port"] == 1883
    assert kwargs["protocol"] is aiomqtt.ProtocolVersion.V311
    assert kwargs["clean_session"] is True
    assert kwargs["identifier"].startswith("sonoran-")
    assert kwargs["tls_context"] is None
