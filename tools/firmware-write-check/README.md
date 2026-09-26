# Firmware write check (#117, #201)

Drives Sonoran's **shipped** USB write path against real Meshtastic
firmware, then lets an independent tool say what actually changed.

This exists because of one bug. The USB write zeroed every setting it
did not change: the firmware *replaces* a config section with what it
is sent (`config.lora = validatedLora` in `AdminModule.cpp`), and the
page sent only the changed fields. A "change hopLimit" write would have
set `region` UNSET and `txEnabled` false, stopping the radio.

**A meshtasticd test had already passed on that code.** It re-read
`hopLimit` and the protected fields — the field that changed, and the
fields explicitly guarded. Every field it looked at was a field
somebody was already thinking about. So the rule this directory
enforces:

> After a write, re-read the **whole** section and diff it, not the
> field you changed.

## Why it uses the real module

`apply.mjs` imports `serial-write.js` and `serial-frames.js` from
`src/`, as the page does. It does not restate the admin sequence. A
harness that reimplements the thing it is testing can only prove that
two of your own descriptions agree.

`diff_config.py` is deliberately not selective: it flattens both
exports and reports the union, so a field that *vanishes* is caught.
Vanishing is the bug's signature.

## Running it

Needs Docker and the `meshtastic` CLI. No radio.

```sh
docker run -d --name meshd-check -p 14403:4403 meshd-test:latest
meshtastic --host 127.0.0.1:14403 --export-config > before.yaml
# build current.json / fixed.json from before.yaml, changing ONE field
node apply.mjs <myNodeNum>
# commit reboots the node; in a container meshtasticd cannot re-exec
# itself, so the container exits. Its config persists in the volume.
docker start meshd-check
meshtastic --host 127.0.0.1:14403 --export-config > after.yaml
python3 diff_config.py before.yaml after.yaml config.lora.hopLimit
```

## What a real run looked like

`meshtasticd` 2.7.26, changing `lora.hopLimit` 3 → 5 and nothing else.
43 fields compared, 3 changed:

| field | before → after | |
|---|---|---|
| `config.lora.hopLimit` | 3 → 5 | the intended change |
| `channel_url` | re-encoded | the URL encodes LoRa settings |
| `config.lora.codingRate` | absent → 5 | firmware normalised it from `usePreset` |

No field was lost. `txEnabled` stayed true and `region` stayed UNSET —
the two that the pre-#201 code destroyed.

`codingRate` is worth naming rather than waving away: we sent the lora
section as read, which had no `codingRate`, so the firmware received
zero and wrote 5 by recomputing it from the preset. That is the
firmware normalising, not Sonoran overwriting. It is reported by the
diff rather than filtered out, because a field that moves without being
ticked should have to be explained each time.

## What this does NOT cover

The USB **transport**. `meshtasticd` speaks the same client API over
TCP, which is why it catches protocol and payload bugs, but it is not a
serial port. Web Serial against an ESP32 and an nRF52 is still what
closes #117 — see `docs/USB-HARDWARE-TEST.md`.
