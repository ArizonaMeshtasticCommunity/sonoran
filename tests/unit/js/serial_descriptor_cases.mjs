/*
 * Does protobuf.js actually accept our generated descriptor, and does
 * it decode real bytes with it? (#116)
 *
 * Run by `tests/unit/test_serial_descriptor.py`. A generated file that
 * merely EXISTS proves nothing -- the question is whether
 * `Root.fromJSON` accepts it and whether a message the Python side
 * encoded comes back out the same.
 *
 * The vectors are produced by the Python protobuf modules the ingest
 * uses, so this checks the two sides against each other rather than
 * against one implementation twice.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const sandbox = { window: {}, self: {}, global: {}, console, Buffer, setTimeout, TextDecoder, TextEncoder };
sandbox.global = sandbox; sandbox.self = sandbox; sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(readFileSync('src/sonoran/web/static/vendor/config-checker/js/vendor/protobuf.min.js', 'utf8'), sandbox);
vm.runInContext(readFileSync('src/sonoran/web/static/meshtastic-serial-proto.js', 'utf8'), sandbox);
const protobuf = sandbox.protobuf || sandbox.window.protobuf;
if (!protobuf) { console.log('protobuf.js did not load'); process.exit(1); }
const root = protobuf.Root.fromJSON(sandbox.window.MeshtasticSerialProto);
console.log('descriptor loaded via Root.fromJSON: ok');
const vectors = readFileSync(process.env.SONORAN_VECTORS, 'utf8').trim().split('\n')
  .map((l) => l.split(': ').map((s) => s.trim()));
let bad = 0;
for (const [name, b64] of vectors) {
  const bytes = Buffer.from(b64, 'base64');
  const T = root.lookupType(name.startsWith('toradio') ? 'meshtastic.ToRadio' : 'meshtastic.FromRadio');
  const obj = T.toObject(T.decode(bytes), { longs: Number });
  const again = Buffer.from(T.encode(T.fromObject(obj)).finish());
  const same = again.equals(bytes);
  if (!same) bad += 1;
  console.log(`  ${name.padEnd(9)} -> ${JSON.stringify(obj)}  byte-identical re-encode: ${same}`);
}
// Negative control: the VENDORED descriptor must NOT be able to do this.
vm.runInContext(readFileSync('src/sonoran/web/static/vendor/config-checker/js/protobuf/meshtastic-proto.js', 'utf8'), sandbox);
const vendored = protobuf.Root.fromJSON(sandbox.window.MeshtasticProto);
let vendoredHas = true;
try { vendored.lookupType('meshtastic.ToRadio'); } catch { vendoredHas = false; }
console.log(`  CONTROL: vendored descriptor has ToRadio: ${vendoredHas}  (expected false)`);
process.exit(bad === 0 && !vendoredHas ? 0 : 1);
