/*
 * Drive the SHIPPED write path against real firmware, then let an
 * independent tool say what changed (#117, #201).
 *
 * Imports serial-write.js and serial-frames.js as the page does, so
 * this exercises the module that ships rather than a restatement of it.
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import net from 'node:net';
import vm from 'node:vm';
import { planChanges, applyChanges, adminEnvelope } from '../../src/sonoran/web/static/serial-write.js';
import { frame } from '../../src/sonoran/web/static/serial-frames.js';

const STATIC = '../../src/sonoran/web/static';
const require = createRequire(import.meta.url);
const protobuf = require(`${STATIC}/vendor/config-checker/js/vendor/protobuf.min.js`);

// The descriptor assigns to `window`; give it one.
const sandbox = { window: {} };
vm.createContext(sandbox);
new vm.Script(readFileSync(`${STATIC}/meshtastic-serial-proto.js`, 'utf8')).runInContext(sandbox);
const root = protobuf.Root.fromJSON(sandbox.window.MeshtasticSerialProto);
const AdminMessage = root.lookupType('meshtastic.AdminMessage');
const ToRadio = root.lookupType('meshtastic.ToRadio');

const current = JSON.parse(readFileSync('current.json', 'utf8'));
const fixed = JSON.parse(readFileSync('fixed.json', 'utf8'));
const nodeNum = Number(process.argv[2]);

const rows = planChanges(current, fixed);
console.log('PLAN:', JSON.stringify(rows.map((r) => `${r.section}.${r.field} ${r.from}->${r.to}`)));

const sock = net.createConnection({ host: '127.0.0.1', port: 14403 });
await new Promise((ok, no) => { sock.once('connect', ok); sock.once('error', no); });
sock.on('data', () => {});   // drain FromRadio

const result = await applyChanges(rows, {
  current,
  send: async (message) => {
    sock.write(Buffer.from(frame(adminEnvelope(message, nodeNum, { AdminMessage, ToRadio }))));
    await new Promise((r) => setTimeout(r, 400));
  },
  onProgress: (line) => console.log('  ', line),
});
console.log('RESULT:', JSON.stringify(result));
await new Promise((r) => setTimeout(r, 2500));
sock.end();
