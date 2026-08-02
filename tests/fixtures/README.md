# MQTT fixtures

Each fixture is one JSON object.
It has `topic` and `payload_base64` fields.
It must contain an encrypted protobuf MQTT message.

Use this command to record one fixture:

```bash
.venv/bin/python tools/record_fixture.py tests/fixtures/name.json
```

Set MQTT credentials in `.env` before you run the command.
Use `--portnum POSITION_APP` to record one selected packet family.

The `recorded_azmsh_*.json` fixtures come from the sonoran.net broker. Use these
fixtures for ingest integration tests. The other recorded fixtures came from
the main Meshtastic broker before sonoran.net credentials were available.
Use only messages encrypted with the default public channel key.
Do not store channel keys in fixtures.
