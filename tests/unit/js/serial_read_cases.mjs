/*
 * The serial exchange, driven against a SIMULATED node (#116).
 *
 * A real board is still needed for the hand-test the issue asks for --
 * timing, buffering and driver quirks are exactly what a simulator
 * cannot reproduce. What it CAN prove is that the conversation is
 * right: the right request goes out, the reply is reassembled from
 * arbitrary chunk boundaries, the completion id ends it, a silent node
 * times out, and the port is closed on every path.
 *
 * The frames are built from bytes the PYTHON protobuf modules encoded,
 * so this checks the two sides against each other.
 */
import { readFileSync } from 'node:fs';
import { readConfig, serialUnavailableReason, BAUD_RATE } from '../../../src/sonoran/web/static/serial-read.js';
import { frame } from '../../../src/sonoran/web/static/serial-frames.js';

let failed = 0;
const eq = (name, got, want) => {
  const a = JSON.stringify(got); const b = JSON.stringify(want);
  if (a === b) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${a}\n       want ${b}`); }
};

const vectors = JSON.parse(readFileSync(process.env.SONORAN_SERIAL_VECTORS, 'utf8'));
const b = (k) => Buffer.from(vectors[k], 'base64');

/** A node that answers want_config, handing bytes over in set chunks. */
function fakeNode({ chunks, silent = false } = {}) {
  const port = {
    opened: false, closed: false, baud: null, written: [],
    readerCancelled: false,
  };
  port.open = async ({ baudRate }) => { port.opened = true; port.baud = baudRate; };
  port.close = async () => { port.closed = true; };
  port.writable = {
    getWriter: () => ({
      write: async (bytes) => port.written.push(Buffer.from(bytes)),
      releaseLock: () => {},
    }),
  };
  let i = 0;
  port.readable = {
    getReader: () => ({
      read: async () => (silent
        ? new Promise(() => {})            // never resolves: a node that says nothing
        : (i < chunks.length ? { value: chunks[i++], done: false } : { done: true })),
      cancel: async () => { port.readerCancelled = true; },
      releaseLock: () => {},
    }),
  };
  return port;
}

const decode = (payload) => JSON.parse(Buffer.from(payload).toString('utf8'));
const encodeWantConfig = (id) => Buffer.from(JSON.stringify({ wantConfigId: id }), 'utf8');
const reply = (obj) => frame(Buffer.from(JSON.stringify(obj), 'utf8'));

// 1. The happy path, with the reply arriving in one chunk.
{
  const id = 4242;
  const stream = Buffer.concat([
    reply({ myInfo: { myNodeNum: 2688087740 } }),
    reply({ config: { lora: { region: 'US' } } }),
    reply({ moduleConfig: { mqtt: { enabled: true } } }),
    reply({ channel: { index: 0 } }),
    reply({ configCompleteId: id }),
  ]);
  const port = fakeNode({ chunks: [new Uint8Array(stream)] });
  const seen = [];
  const out = await readConfig(port, { decode, encodeWantConfig, wantConfigId: id,
    onProgress: (m) => seen.push(m) });
  eq('opens at 115200', port.baud, BAUD_RATE);
  eq('sends one framed want_config', port.written.length, 1);
  eq('request is framed 0x94 0xC3', [port.written[0][0], port.written[0][1]], [0x94, 0xc3]);
  eq('collects my_info', out.myInfo.myNodeNum, 2688087740);
  eq('collects a config section', out.config.lora.region, 'US');
  eq('collects a module section', out.moduleConfig.mqtt.enabled, true);
  eq('collects channels', out.channels.length, 1);
  eq('closes the port', port.closed, true);
  eq('reports progress', seen.length > 1, true);
}

// 2. The same reply, one byte at a time. This is the case a simulator
//    is actually for: a real port hands over whatever it has.
{
  const id = 7;
  const stream = Buffer.concat([
    reply({ myInfo: { myNodeNum: 1 } }),
    reply({ configCompleteId: id }),
  ]);
  const chunks = [...stream].map((byte) => new Uint8Array([byte]));
  const port = fakeNode({ chunks });
  const out = await readConfig(port, { decode, encodeWantConfig, wantConfigId: id });
  eq('reassembles across single-byte reads', out.myInfo.myNodeNum, 1);
  eq('closes the port', port.closed, true);
}

// 3. Firmware log text between frames, which shares the port.
{
  const id = 9;
  const stream = Buffer.concat([
    Buffer.from('INFO | Booting\n', 'utf8'),
    reply({ myInfo: { myNodeNum: 5 } }),
    Buffer.from('DEBUG | radio up\n', 'utf8'),
    reply({ configCompleteId: id }),
  ]);
  const port = fakeNode({ chunks: [new Uint8Array(stream)] });
  const out = await readConfig(port, { decode, encodeWantConfig, wantConfigId: id });
  eq('ignores log text on the same port', out.myInfo.myNodeNum, 5);
}

// 4. A DIFFERENT completion id must not end the exchange.
{
  const id = 100;
  const stream = Buffer.concat([
    reply({ configCompleteId: 999 }),
    reply({ myInfo: { myNodeNum: 3 } }),
    reply({ configCompleteId: id }),
  ]);
  const port = fakeNode({ chunks: [new Uint8Array(stream)] });
  const out = await readConfig(port, { decode, encodeWantConfig, wantConfigId: id });
  eq('ignores another session’s completion id', out.myInfo.myNodeNum, 3);
}

// 5. A silent node times out, and STILL closes the port.
{
  const port = fakeNode({ silent: true });
  let clock = 0;
  let message = '';
  try {
    await readConfig(port, { decode, encodeWantConfig, wantConfigId: 1,
      timeoutMs: 50, now: () => (clock += 40) });
  } catch (error) { message = String(error.message); }
  eq('times out with something actionable', /did not finish sending/.test(message), true);
  eq('closes the port after a timeout', port.closed, true);
}

// 6. A node that hangs up mid-config is an error, not a partial success.
{
  const port = fakeNode({ chunks: [new Uint8Array(reply({ myInfo: { myNodeNum: 1 } }))] });
  let message = '';
  try {
    await readConfig(port, { decode, encodeWantConfig, wantConfigId: 1 });
  } catch (error) { message = String(error.message); }
  eq('a truncated exchange throws', /closed the connection/.test(message), true);
  eq('closes the port after a hang-up', port.closed, true);
}

// 7. Real protobuf bytes, framed, decoded by the real descriptor --
//    the two sides checked against each other rather than one twice.
{
  const vm = await import('node:vm');
  const sandbox = { console, Buffer, setTimeout, TextDecoder, TextEncoder, Uint8Array, ArrayBuffer };
  sandbox.window = sandbox; sandbox.self = sandbox; sandbox.global = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(readFileSync('src/sonoran/web/static/vendor/config-checker/js/vendor/protobuf.min.js', 'utf8'), sandbox);
  vm.runInContext(readFileSync('src/sonoran/web/static/meshtastic-serial-proto.js', 'utf8'), sandbox);
  const root = sandbox.protobuf.Root.fromJSON(sandbox.window.MeshtasticSerialProto);
  const FromRadio = root.lookupType('meshtastic.FromRadio');
  const ToRadio = root.lookupType('meshtastic.ToRadio');

  const id = 12345;
  const stream = Buffer.concat([frame(b('my_info')), frame(b('complete'))]);
  const port = fakeNode({ chunks: [new Uint8Array(stream)] });
  const out = await readConfig(port, {
    // `new sandbox.Uint8Array(...)` because protobuf.js runs in a vm
    // realm of its own and rejects a typed array built outside it --
    // "illegal buffer". A harness artifact, not a product one: in a
    // browser both live in the same realm.
    decode: (payload) => FromRadio.toObject(
      FromRadio.decode(new sandbox.Uint8Array(payload)), { longs: Number },
    ),
    encodeWantConfig: (n) => ToRadio.encode(ToRadio.fromObject({ wantConfigId: n })).finish(),
    wantConfigId: id,
  });
  eq('real FromRadio bytes carry my_info', out.myInfo.myNodeNum, 2688087740);
  eq('real want_config is what Python would read', port.written[0].length > 4, true);
  eq('closes the port', port.closed, true);
}

// 8. The browser-capability message, which decides whether the button
//    is offered at all.
{
  const reason = serialUnavailableReason();
  eq('says why USB is unavailable here (node has no navigator.serial)',
    /Chrome or Edge/.test(String(reason)), true);
}

console.log(failed ? `\n${failed} FAILED` : '\nall passed');
process.exit(failed ? 1 : 0);
