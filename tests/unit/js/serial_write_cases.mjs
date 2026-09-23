/*
 * Writing settings to a node, against a simulator (#117).
 *
 * This changes somebody's radio, so the cases that matter most are the
 * ones about what it REFUSES to write.
 */
import { planChanges, applyChanges, isProtected, PROTECTED, CHANGES_WHICH_MESH }
  from '../../../src/sonoran/web/static/serial-write.js';

let failed = 0;
const eq = (name, got, want) => {
  const a = JSON.stringify(got); const b = JSON.stringify(want);
  if (a === b) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${a}\n       want ${b}`); }
};

const current = {
  config: {
    lora: { region: 'UNSET', modemPreset: 'LONG_FAST', txEnabled: true },
    position: { positionBroadcastSecs: 900 },
    security: { adminKey: 'AAAA', isManaged: false },
    bluetooth: { enabled: true },
  },
  moduleConfig: { mqtt: { enabled: false }, neighborInfo: { enabled: false } },
};
const fixed = {
  config: {
    lora: { region: 'US', modemPreset: 'MEDIUM_FAST', txEnabled: true },
    position: { positionBroadcastSecs: 1800 },
    security: { adminKey: 'BBBB', isManaged: true },
    bluetooth: { enabled: false },
  },
  moduleConfig: { mqtt: { enabled: true }, neighborInfo: { enabled: true } },
};

// 1. The diff is per field, and unchanged fields are left out.
{
  const rows = planChanges(current, fixed);
  const keys = rows.map((r) => `${r.section}.${r.field}`).sort();
  eq('lists only what differs', keys, [
    'bluetooth.enabled', 'lora.modemPreset', 'lora.region',
    'mqtt.enabled', 'neighborInfo.enabled',
    'position.positionBroadcastSecs', 'security.adminKey', 'security.isManaged',
  ]);
  eq('txEnabled was equal, so it is absent', keys.includes('lora.txEnabled'), false);
  const region = rows.find((r) => r.field === 'region');
  eq('carries current -> new', [region.from, region.to], ['UNSET', 'US']);
}

// 2. Dangerous settings are FLAGGED in the plan.
{
  const rows = planChanges(current, fixed);
  const flagged = rows.filter((r) => r.protected).map((r) => `${r.section}.${r.field}`).sort();
  eq('flags keys, is_managed and bluetooth',
    flagged, ['bluetooth.enabled', 'security.adminKey', 'security.isManaged']);
  const mesh = rows.filter((r) => r.changesMesh).map((r) => r.field).sort();
  eq('flags what moves the node to another mesh', mesh, ['modemPreset', 'region']);
}

// 3. THE ONE THAT MATTERS: protected rows are not written, even when
//    handed straight to applyChanges.
{
  const sent = [];
  const rows = planChanges(current, fixed);
  const out = await applyChanges(rows, { send: async (m) => sent.push(m) });
  const wroteSecurity = JSON.stringify(sent).includes('adminKey')
    || JSON.stringify(sent).includes('isManaged');
  eq('never writes a key or is_managed', wroteSecurity, false);
  eq('never writes bluetooth.enabled', JSON.stringify(sent).includes('bluetooth'), false);
  eq('counts what it refused', out.refused, 3);
  eq('still wrote the safe ones', out.written, 5);
}

// 4. The admin sequence, in order, with ONE commit.
{
  const sent = [];
  const rows = planChanges(current, fixed);
  await applyChanges(rows, { send: async (m) => sent.push(m) });
  eq('begins with beginEditSettings', Boolean(sent[0].beginEditSettings), true);
  eq('ends with commitEditSettings', Boolean(sent[sent.length - 1].commitEditSettings), true);
  eq('commits exactly once',
    sent.filter((m) => m.commitEditSettings).length, 1);
}

// 5. One message per SECTION, not per field. Two fields of one section
//    in two messages would make the second overwrite the first.
{
  const twoFields = {
    config: { position: { positionBroadcastSecs: 1800, gpsUpdateInterval: 120 } },
    moduleConfig: {},
  };
  const before = { config: { position: { positionBroadcastSecs: 900, gpsUpdateInterval: 60 } }, moduleConfig: {} };
  const sent = [];
  await applyChanges(planChanges(before, twoFields), { send: async (m) => sent.push(m) });
  const sets = sent.filter((m) => m.setConfig);
  eq('one setConfig for the section', sets.length, 1);
  eq('carrying both fields',
    Object.keys(sets[0].setConfig.position).sort(), ['gpsUpdateInterval', 'positionBroadcastSecs']);
}

// 6. A protected row CAN be written when explicitly named.
{
  const sent = [];
  const rows = planChanges(current, fixed);
  const out = await applyChanges(rows, {
    send: async (m) => sent.push(m), allowProtected: ['bluetooth.enabled'],
  });
  eq('writes bluetooth when asked for by name',
    JSON.stringify(sent).includes('bluetooth'), true);
  eq('still refuses the two it was not asked for', out.refused, 2);
}

// 7. Nothing to do writes nothing at all -- no begin, no commit, no
//    reboot of somebody's node for zero changes.
{
  const sent = [];
  const out = await applyChanges([], { send: async (m) => sent.push(m) });
  eq('no changes means no admin traffic', sent.length, 0);
  eq('and nothing written', out.written, 0);
}

// 8. An absent setting and its zero value are not a change.
{
  const rows = planChanges(
    { config: { position: {} }, moduleConfig: {} },
    { config: { position: { positionBroadcastSmartEnabled: false } }, moduleConfig: {} },
  );
  eq('undefined vs false is not a change', rows.length, 0);
}

// 9. The deny list is reachable as data, so a preview can explain it.
{
  eq('isProtected agrees with the table', isProtected('security', 'privateKey'), true);
  eq('and lets ordinary fields through', isProtected('lora', 'region'), false);
  eq('psk is protected', PROTECTED.channel.includes('psk'), true);
  eq('mesh-changing list is non-empty', CHANGES_WHICH_MESH.length > 0, true);
}

// 10. A nested message that did not change is not a change. The fixer
//     deep-clones, so it is never the same object; the preview used to
//     offer "mqtt.mapReportSettings: [object Object] → [object Object]".
{
  const node = { config: {}, moduleConfig: { mqtt: { mapReportSettings: { publishIntervalSecs: 3600 } } } };
  const rows = planChanges(node, JSON.parse(JSON.stringify(node)));
  eq('an equal nested object is not a change', rows.length, 0);
}

console.log(failed ? `\n${failed} FAILED` : '\nall passed');
process.exit(failed ? 1 : 0);
