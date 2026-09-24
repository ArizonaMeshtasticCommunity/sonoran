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
 * The port an AdminMessage travels on. `PortNum.ADMIN_APP`.
 */
export const ADMIN_PORT = 6;

/**
 * Wrap an AdminMessage for the wire.
 *
 * **An AdminMessage is not sent on its own.** It goes inside a
 * `MeshPacket` addressed to the local node on the admin port, inside a
 * `ToRadio`. #117 says so in one line -- "each is sent as a MeshPacket
 * to the local node on the admin port" -- and sending the bare
 * AdminMessage instead is silently accepted by the firmware and
 * silently does NOTHING.
 *
 * Measured against meshtasticd 2.7.26: sending bare AdminMessages
 * reported success, and a re-read showed `lora.hopLimit` still at its
 * old value. Nothing errored. That is the worst shape a bug can have
 * on a path that writes to somebody's radio, and no simulator of mine
 * would have caught it -- the simulator checks what we send, not what
 * a node does with it.
 *
 * `nodeNum` is the local node's own number, from `my_info` on the
 * read. Addressing the packet to the node itself is what makes it an
 * admin request rather than traffic.
 */
export function adminEnvelope(admin, nodeNum, { AdminMessage, ToRadio }) {
  const payload = AdminMessage.encode(AdminMessage.fromObject(admin)).finish();
  return ToRadio.encode(ToRadio.fromObject({
    packet: {
      to: nodeNum,
      from: nodeNum,
      wantAck: true,
      decoded: { portnum: ADMIN_PORT, payload },
    },
  })).finish();
}

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
  // A nested message (`mqtt.mapReportSettings`) arrives as a fresh
  // object on each side -- `ConfigFixer` deep-clones -- so it never
  // equals by reference. Compare what it holds.
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    return JSON.stringify(a) === JSON.stringify(b);
  }
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
 * `current` is the config as read off the node. **Each section is sent
 * whole**: the current section with the chosen fields laid over it.
 * The firmware REPLACES a section with what it is sent
 * (`config.lora = validatedLora` in `AdminModule.cpp`), so a section
 * that holds only the changed field sets every other field in it to
 * zero. For `lora` that is region UNSET and `tx_enabled` false; for
 * `security` it is every key.
 *
 * `send` frames and writes one AdminMessage; injected so the tests can
 * drive the whole sequence without a radio.
 */
export async function applyChanges(rows, {
  current,
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

  // Check every section before anything is sent. Refusing halfway
  // would leave the node inside an open edit.
  for (const row of allowed) {
    const had = current && current[row.group] && current[row.group][row.section];
    if (!had) {
      throw new Error(`The node's ${row.section} settings were not read, so ${row.section} cannot be `
        + 'written without setting the rest of that section to zero. Read the node again.');
    }
  }

  onProgress('Opening the node for editing…');
  await send({ beginEditSettings: true });

  // One message per SECTION, not per field, and each one carries the
  // WHOLE section: the admin API replaces a section with what it is
  // sent. Two messages for two fields of one section would make the
  // second overwrite the first.
  const bySection = new Map();
  for (const row of allowed) {
    const key = `${row.group}:${row.section}`;
    if (!bySection.has(key)) {
      bySection.set(key, {
        group: row.group,
        section: row.section,
        fields: { ...current[row.group][row.section] },
      });
    }
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
