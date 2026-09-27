"""Sonoran's own USB reader decodes what firmware 2.8 sends (#263).

Fernando's report: a RAK on firmware 2.8.0.47db0e3, region US, LongTurbo,
with PKI keys, fails to read in cfgtest with ``invalid wire type 7 at offset
174``. That is cfgtest's hand-written descriptor, not ours -- Sonoran's USB
path decodes with ``meshtastic-serial-proto.js``, which is GENERATED from the
same Python protobufs the ingest uses. Those were regenerated from
meshtastic/protobufs v2.8.0 for #252, and the descriptor with them.

So this asks the question for Sonoran directly, without a board: the Python
side encodes the config messages a 2.8 node sends over serial -- with the
parts of Fernando's setup that are new or changed (the LONG_TURBO preset, a
public and private key, and a traffic-management section using the field
numbers 2.8 moved to) -- and protobuf.js, loading the generated descriptor
the page loads, must decode every one back to the same values.

It is not a hardware test and does not claim to be. It rules out a schema
gap on our side, which is the part that can be ruled out from here.

**What it is, precisely: a characterisation, not a regression test.** It was
run against the descriptor from BEFORE the v2.8.0 regeneration as well, and
that passed too -- the 2026-08-02 schema already knew LONG_TURBO, the PKI
key fields and the traffic-management field numbers. So this does not guard
the regeneration, and it would be wrong to read it as proof that the
regeneration fixed anything here. What it establishes is that Sonoran's USB
decoder was never exposed to Fernando's failure for these fields, which
points that failure at cfgtest's hand-written descriptor or at the bytes its
read path hands to its file decoder. It stays because it would catch a
future schema change that DID break a 2.8 config.
"""

import base64
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

READER = r"""
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = { console, Buffer, TextDecoder, TextEncoder, setTimeout };
sandbox.window = sandbox; sandbox.self = sandbox; sandbox.global = sandbox;
vm.createContext(sandbox);
const STATIC = 'src/sonoran/web/static';
const RUNTIME = `${STATIC}/vendor/config-checker/js/vendor/protobuf.min.js`;
vm.runInContext(readFileSync(RUNTIME, 'utf8'), sandbox);
vm.runInContext(readFileSync('src/sonoran/web/static/meshtastic-serial-proto.js', 'utf8'), sandbox);
const root = sandbox.protobuf.Root.fromJSON(sandbox.window.MeshtasticSerialProto);
const FromRadio = root.lookupType('meshtastic.FromRadio');
// protobuf.js compares `enums === String`; it must be the String of the realm
// it was loaded into, or it silently leaves enums as numbers and bytes as
// Buffers. Taken from the sandbox, as the page's own realm would provide it.
const S = vm.runInContext('String', sandbox);
const N = vm.runInContext('Number', sandbox);
const out = {};
for (const [name, b64] of Object.entries(JSON.parse(readFileSync(process.env.V, 'utf8')))) {
  const msg = FromRadio.decode(Buffer.from(b64, 'base64'));
  out[name] = FromRadio.toObject(msg, { enums: S, bytes: S, longs: N });
}
console.log(JSON.stringify(out));
"""


def _vectors(path: Path) -> dict[str, bytes]:
    from sonoran.meshtastic import config_pb2, mesh_pb2, module_config_pb2

    lora = mesh_pb2.FromRadio()  # type: ignore[attr-defined]
    lora.config.lora.region = config_pb2.Config.LoRaConfig.RegionCode.US
    lora.config.lora.modem_preset = config_pb2.Config.LoRaConfig.ModemPreset.LONG_TURBO
    lora.config.lora.use_preset = True

    security = mesh_pb2.FromRadio()  # type: ignore[attr-defined]
    security.config.security.public_key = bytes(range(32))
    security.config.security.private_key = bytes(range(32, 64))

    traffic = mesh_pb2.FromRadio()  # type: ignore[attr-defined]
    tm = traffic.moduleConfig.traffic_management
    tm.position_min_interval_secs = 900
    tm.rate_limit_window_secs = 60
    tm.unknown_packet_threshold = 5
    assert isinstance(tm, module_config_pb2.ModuleConfig.TrafficManagementConfig)

    vectors = {"lora": lora, "security": security, "traffic": traffic}
    path.write_text(
        json.dumps(
            {k: base64.b64encode(v.SerializeToString()).decode() for k, v in vectors.items()}
        )
    )
    return {k: v.SerializeToString() for k, v in vectors.items()}


def test_the_generated_descriptor_decodes_a_2_8_config(tmp_path: Path) -> None:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the descriptor went unchecked"
    vectors = tmp_path / "v.json"
    _vectors(vectors)
    script = tmp_path / "read.mjs"
    script.write_text(READER)
    done = subprocess.run(
        [node, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
        env={**os.environ, "V": str(vectors)},
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    got = json.loads(done.stdout.strip().splitlines()[-1])

    lora = got["lora"]["config"]["lora"]
    assert lora["modemPreset"] == "LONG_TURBO", lora
    assert lora["region"] == "US", lora

    security = got["security"]["config"]["security"]
    assert base64.b64decode(security["publicKey"]) == bytes(range(32)), security
    assert base64.b64decode(security["privateKey"]) == bytes(range(32, 64)), security

    tm = got["traffic"]["moduleConfig"]["trafficManagement"]
    assert tm == {
        "positionMinIntervalSecs": 900,
        "rateLimitWindowSecs": 60,
        "unknownPacketThreshold": 5,
    }, tm
