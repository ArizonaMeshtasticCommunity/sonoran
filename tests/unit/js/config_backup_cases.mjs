/*
 * Behaviour cases for `config-backup.js` (#117).
 *
 * Run by `tests/unit/test_config_backup.py`.
 *
 * Run, not read, because the thing under test is a FILE FORMAT: whether
 * the bytes this writes are bytes `meshtastic --configure` consumes.
 * The bug this replaces passed every source-level check it had -- the
 * download worked, the file parsed as YAML, and it restored nothing,
 * because its top-level keys were ones the CLI ignores.
 */
import { buildBackup, RESTORABLE_KEYS } from '../../../src/sonoran/web/static/config-backup.js';

let failed = 0;
const eq = (name, got, want) => {
  if (got === want) return;
  failed += 1;
  console.error(`FAIL ${name}\n  got:  ${JSON.stringify(got)}\n  want: ${JSON.stringify(want)}`);
};
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};
const threw = (name, fn, match) => {
  try { fn(); failed += 1; console.error(`FAIL ${name}: it did not throw`); }
  catch (e) {
    if (match && !String(e.message).includes(match)) {
      failed += 1;
      console.error(`FAIL ${name}: wrong message\n  got: ${e.message}`);
    }
  }
};

const read = {
  myInfo: { myNodeNum: 1770193104, longName: 'Megaton [CoA]', shortName: 'MGTN' },
  metadata: { firmwareVersion: '2.7.26.54e0d8d' },
  channels: [],
  config: {
    lora: { usePreset: true, modemPreset: 'MEDIUM_FAST', region: 'US', hopLimit: 3,
            txEnabled: true, txPower: 30, channelNum: 18, bandwidth: 250 },
    device: { role: 'CLIENT' },
    position: { positionBroadcastSecs: 900, gpsMode: 'ENABLED' },
  },
  moduleConfig: {
    mqtt: { enabled: true, address: 'mqtt.azmsh.net', username: 'u', password: 'p' },
    neighborInfo: { enabled: true, updateInterval: 39600 },
  },
};

const out = buildBackup(read, { now: new Date('2026-09-24T02:00:00Z') });
const text = out.data;

// THE CASE THE OLD FILE FAILED. These are the only keys the CLI reads.
ok('has a top-level config:', /^config:$/m.test(text), text.slice(0, 200));
ok('has a top-level module_config:', /^module_config:$/m.test(text));
ok('names the owner', /^owner: /m.test(text));
// And none of the DeviceProfile keys that the CLI ignores.
ok('no DeviceProfile device: at top level', !/^device:$/m.test(text));
ok('no DeviceProfile lora: at top level', !/^lora:$/m.test(text));
ok('no DeviceProfile module: at top level', !/^module:$/m.test(text));

// snake_case, as the CLI's own YAML uses.
ok('keys are snake_case', text.includes('hop_limit: 3'), text);
ok('nested sections are snake_case', text.includes('update_interval: 39600'));
ok('module sections keep their name', /^  neighbor_info:$/m.test(text));

// The bug that made the old file unusable even where it had data.
ok('no literal undefined anywhere', !text.includes('undefined'), text);

// Settings the old export dropped.
for (const needed of ['bandwidth: 250', 'tx_power: 30', 'channel_num: 18', 'region: US']) {
  ok(`keeps ${needed}`, text.includes(needed), text);
}

// The header must name a real CLI flag.
ok('header names --configure', text.includes('--configure'));
ok('header does not name --import-config', !text.includes('--import-config'));

// It must be honest about what a node cannot report.
ok('says the keys are not in it', /private key|admin key/i.test(text));

eq('the file is yaml', out.mimeType, 'text/yaml');
ok('the filename says what it is', /^meshtastic-backup-.*\.yaml$/.test(out.filename), out.filename);

// --- refusing rather than writing a useless file -------------------

threw('nothing to back up', () => buildBackup(null), 'no config');
threw('an unread node', () => buildBackup({ myInfo: { longName: 'x' } }), 'were not read');
threw('empty sections only', () => buildBackup({ config: {}, moduleConfig: {} }), 'were not read');

// An empty section must not be written: the CLI would read it as
// "set this section to nothing", which is the whole-section bug again.
const sparse = buildBackup({ config: { lora: { hopLimit: 3 }, device: {} } });
ok('an empty section is left out', !/^  device:$/m.test(sparse.data), sparse.data);
ok('a section with values is kept', /^  lora:$/m.test(sparse.data));

// A string that could be read as another type has to survive a round
// trip as a string.
const quoted = buildBackup({ config: { device: { role: 'CLIENT' } },
  myInfo: { longName: 'true' } });
ok('an owner named "true" is quoted', quoted.data.includes('owner: "true"'), quoted.data);

if (failed) { console.error(`${failed} failed`); process.exit(1); }
console.log(`config backup: all cases passed (${RESTORABLE_KEYS.length} restorable keys)`);
