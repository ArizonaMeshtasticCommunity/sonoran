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

The `recorded_azmsh_*.json` fixtures come from the azmsh.net broker. Use these
fixtures for ingest integration tests. The other recorded fixtures came from
the main Meshtastic broker before azmsh.net credentials were available.
Use only messages encrypted with the default public channel key.
Do not store channel keys in fixtures.

## Values replaced for privacy

Two recorded fixtures had private values. They were changed in place,
and nothing else in them was changed:

- `recorded_azmsh_position.json`: the position was the exact position
  of a real node. It is now 33.5 N, 112.0 W, a round point.
- `recorded_azmsh_nodeinfo.json`: the long name and the short name
  named a real station. They are now `Sonoran Test Station` and `TST1`.

The topic, the envelope, the packet header and every other field are
as recorded. The changed plaintext was encrypted again with the same
public key, packet ID and sender, so the packet still decrypts as a
packet from the air does.

Before you record a new fixture, check what it holds. A position is a
precise location of somebody's equipment. A name can be a call sign,
and a call sign names a person. Replace such values the same way.
