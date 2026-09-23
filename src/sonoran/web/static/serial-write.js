/*
 * Write recommended settings to a node over USB (#117).
 *
 * This changes somebody's radio. Everything here is shaped by that.
 *
 * The sequence is the Meshtastic admin API, not CLI text:
 *
 *   AdminMessage { begin_edit_settings }
 *   AdminMessage { set_config }        per changed section
 *   AdminMessage { set_module_config } per changed section
 *   AdminMessage { set_channel }       per changed channel
 *   AdminMessage { commit_edit_settings }
 *
 * One commit, one reboot, at the end.
 *
 * **Do not port upstream's `applySerialConfig()`.** It writes
 * `meshtastic --set …` CLI strings at the serial port, which the
 * firmware does not understand (#115), and it covers a fixed subset
 * rather than the whole `ConfigFixer` result.
 */

/*
 * Settings this never writes unless the caller explicitly asks.
 *
 * #117: "A mistake there can lock someone out of their own node." A
 * channel PSK changes which mesh the node is on; an admin key or
 * `is_managed` can remove the owner's own ability to administer it;
 * turning off serial or Bluetooth can remove the last way in.
 *
 * Held as a DENY LIST that the diff is filtered through, rather than
 * as a rule the caller is trusted to follow, because the caller is
 * `ConfigFixer` output and it has no idea what is dangerous.
 */
export const PROTECTED = Object.freeze({
  security: ['adminKey', 'privateKey', 'publicKey', 'isManaged', 'adminChannelEnabled'],
  bluetooth: ['enabled'],
  serial: ['enabled'],
  // A channel's `psk` decides which mesh this node is on at all.
  channel: ['psk'],
});

/** True when this field must not be written without being asked for. */
export function isProtected(section, field) {
  const guarded = PROTECTED[section];
  return Boolean(guarded && guarded.includes(field));
}

/*
 * Settings that move the node to a different mesh.
 *
 * Not forbidden -- fixing the region is often the whole point -- but
 * #117 asks that the reader be told in plain words before confirming,
 * so the caller can find them without re-deriving the list.
 */
export const CHANGES_WHICH_MESH = Object.freeze([
  'lora.region',
  'lora.modemPreset',
  'lora.usePreset',
  'lora.channelNum',
]);

/**
 * What would change, current against recommended.
 *
 * Returns one row per differing field, each with `section`, `field`,
 * `from`, `to`, `protected` and `changesMesh`. Rows are the unit the
 * preview renders and the unit the reader ticks, so nothing can be
 * written that was not shown.
 */
export function planChanges(current, fixed) {
  const rows = [];
  for (const [group, key] of [['config', 'config'], ['moduleConfig', 'moduleConfig']]) {
    const before = (current && current[key]) || {};
    const after = (fixed && fixed[key]) || {};
    for (const section of Object.keys(after)) {
      const was = before[section] || {};
      const now = after[section] || {};
      for (const field of Object.keys(now)) {
        if (same(was[field], now[field])) continue;
        rows.push({
          group,
          section,
          field,
          from: was[field],
          to: now[field],
          protected: isProtected(section, field),
          changesMesh: CHANGES_WHICH_MESH.includes(`${section}.${field}`),
        });
      }
    }
  }
  return rows;
}

function same(a, b) {
  if (a === b) return true;
  // An absent setting and its zero value are the same node behaviour,
  // and writing one over the other is a change the reader would not
  // recognise as one.
  if ((a === undefined || a === null) && (b === 0 || b === false || b === '')) return true;
  if ((b === undefined || b === null) && (a === 0 || a === false || a === '')) return true;
  return false;
}

/**
 * Write the chosen rows, in the admin sequence, over an open port.
 *
 * `rows` must be the ones the reader ticked. **Protected rows are
 * dropped here as well as in the preview**, unless `allowProtected`
 * names them, because "the preview filtered it" is one refactor away
 * from being untrue.
 *
 * `send` frames and writes one AdminMessage; injected so the tests can
 * drive the whole sequence without a radio.
 */
export async function applyChanges(rows, {
  send,
  allowProtected = [],
  onProgress = () => {},
} = {}) {
  const allowed = rows.filter((row) => {
    if (!row.protected) return true;
    return allowProtected.includes(`${row.section}.${row.field}`);
  });
  const refused = rows.length - allowed.length;
  if (!allowed.length) {
    return { written: 0, refused, sections: [] };
  }

  onProgress('Opening the node for editing…');
  await send({ beginEditSettings: true });

  // One message per SECTION, not per field: the admin API sets a whole
  // `Config` section at a time, and sending two messages for two
  // fields of the same section would make the second overwrite the
  // first with stale values.
  const bySection = new Map();
  for (const row of allowed) {
    const key = `${row.group}:${row.section}`;
    if (!bySection.has(key)) bySection.set(key, { group: row.group, section: row.section, fields: {} });
    bySection.get(key).fields[row.field] = row.to;
  }

  const sections = [];
  for (const { group, section, fields } of bySection.values()) {
    const payload = group === 'moduleConfig'
      ? { setModuleConfig: { [section]: fields } }
      : { setConfig: { [section]: fields } };
    onProgress(`Writing ${section}…`);
    await send(payload);
    sections.push(section);
  }

  onProgress('Saving. The node will reboot.');
  await send({ commitEditSettings: true });
  return { written: allowed.length, refused, sections };
}
