/*
 * Config check.
 *
 * This is Sonoran's interface over the community config checker. It
 * imports that project's logic unchanged from vendor/config-checker/js/
 * and draws the result in this dashboard's own style. It is the same
 * arrangement as the coverage planner: the vendored code is the engine,
 * the interface here is ours.
 *
 * Only the logic is imported. The upstream `app.js` is its own
 * interface for its own page and is not used.
 *
 * Nothing here goes to the server. A config file, a channel key, and an
 * MQTT password are read in this browser and sent nowhere. Sonoran has
 * no endpoint for this page and must never gain one. See AGENTS.md 9.17.
 *
 * This file is a module, so it runs after app.js. `configReady` in
 * app.js is the promise it resolves, which is how the router waits for
 * it. Helpers such as `el` and `$` come from app.js: a top-level const
 * in a classic script is visible to a module.
 */

import { ConfigParser } from './vendor/config-checker/js/parser.js';
import { ConfigChecker } from './vendor/config-checker/js/checker.js';
import { ConfigFixer } from './vendor/config-checker/js/fixer.js';
/*
 * Upstream's diagnostics module, imported rather than reimplemented
 * (#119). Its privacy model is a WHITELIST: the report is built
 * field-by-field from a fixed list of non-sensitive scalars, and there
 * is no code path that copies a caller-supplied object wholesale. So a
 * future caller handing it a config by mistake still cannot leak one.
 *
 * Reimplementing that would mean reimplementing the guarantee, and a
 * blacklist written from memory is how PSKs end up in bug reports.
 */
import { Diagnostics, STEPS } from './vendor/config-checker/js/diagnostics.js';
import { readConfig, serialUnavailableReason } from './serial-read.js';
import { planChanges, applyChanges } from './serial-write.js';
import { frame as serialFrame } from './serial-frames.js';

/*
 * Give the vendored code decoders that need no `new Function`.
 *
 * protobuf.js builds its encoders and decoders by compiling strings.
 * This dashboard forbids that: `script-src` carries no `unsafe-eval`,
 * and that is what stops a config someone hands us from becoming
 * running code. So `Root.fromJSON` throws here, and an Android `.cfg`
 * cannot be read.
 *
 * `meshtastic-static.js` is the same schema compiled ahead of time by
 * `tools/generate_protobuf_static.sh`. It carries explicit encoders and
 * decoders and calls `Function` nowhere. Pointing `Root.fromJSON` at
 * those types lets the vendored parser work unchanged, with the policy
 * left alone.
 *
 * Only the two types the checker asks for are served. Anything else is
 * an error rather than a silent undefined, so a change upstream that
 * needs a third type is noticed here instead of failing deep inside a
 * parse.
 */
/*
 * Loaded when a config is first read, not when the page is.
 *
 * `meshtastic-static.js` is 408 kB -- larger than app.js -- and it
 * arrived through this module's import graph on EVERY page, because
 * config-check.js is loaded unconditionally. Most visitors never open
 * the Config check tab. Compression takes it to about 27 kB on the
 * wire, so the transfer argument is mostly gone, but the parse cost
 * is not, and it is paid on a phone by everybody.
 *
 * It has to be in place BEFORE parsing rather than during: the
 * vendored parser calls `Root.fromJSON().lookupType()` synchronously,
 * so the await belongs at the entry points, not inside the override.
 * `ready()` is idempotent and holds the one promise, so two files
 * dropped at once do not fetch it twice.
 */
let typesReady = null;

function ready() {
  if (!typesReady) {
    typesReady = import('./meshtastic-static.js').then(({ meshtastic }) => {
      const STATIC_TYPES = {
        'meshtastic.DeviceProfile': meshtastic.DeviceProfile,
        'meshtastic.ChannelSet': meshtastic.ChannelSet,
      };
      // Only the two types the checker asks for are served. Anything
      // else is an error rather than a silent undefined, so a change
      // upstream that needs a third type is noticed here instead of
      // failing deep inside a parse.
      window.protobuf.Root.fromJSON = () => ({
        lookupType(name) {
          const type = STATIC_TYPES[name];
          if (!type) {
            throw new Error(
              `${name} is not in the pre-compiled protobuf types. ` +
                'Add it to STATIC_TYPES in config-check.js.',
            );
          }
          return type;
        },
      });
    });
  }
  return typesReady;
}

/** Where the checker's own settings live between visits. */
const CHOICES = 'sonoran.config-check';

const state = {
  region: 'metro',
  nodeType: 'stationary',
  config: null,
  fileName: '',
  result: null,
};

/* ---------------------------------------------------------------- */
/* Firmware                                                          */

/*
 * The one outbound request this dashboard makes.
 *
 * It asks which firmware release is current so a node can be told it is
 * behind. It sends nothing. The host is in `connect-src` for this and
 * for nothing else. A failure is not worth reporting: the check simply
 * falls back to the version the vendored code was built with.
 */
const FIRMWARE_RELEASES = 'https://api.github.com/repos/meshtastic/firmware/releases/latest';

let firmwareAsked = false;

async function loadLatestFirmware() {
  if (firmwareAsked) return;
  firmwareAsked = true;
  try {
    const response = await fetch(FIRMWARE_RELEASES);
    if (!response.ok) return;
    const release = await response.json();
    const tag = String(release.tag_name || '').replace(/^v/, '');
    const [major, minor, patch] = tag.split('.');
    if (patch === undefined) return;
    ConfigChecker.setLatestFirmware(
      tag,
      (parseInt(major, 10) || 0) * 10000 +
        (parseInt(minor, 10) || 0) * 100 +
        (parseInt(patch, 10) || 0),
    );
  } catch (error) {
    console.warn('firmware release lookup failed', error);
  }
}

/* ---------------------------------------------------------------- */
/* Drawing                                                           */

const STATUS_LABEL = { pass: 'pass', fail: 'fix this', warn: 'check', info: 'note' };

/** One check, as a row that can be opened for the reasoning. */
function checkRow(check) {
  const detail = [
    check.current != null
      ? el('div', { class: 'kv' },
          el('span', { class: 'muted', text: 'Now' }), el('span', { text: String(check.current) }))
      : null,
    check.expected != null
      ? el('div', { class: 'kv' },
          el('span', { class: 'muted', text: 'Wanted' }), el('span', { text: String(check.expected) }))
      : null,
    check.settingKey
      ? el('div', { class: 'kv' },
          el('span', { class: 'muted', text: 'Setting' }),
          el('code', { text: check.settingKey }))
      : null,
    check.why ? el('p', { class: 'muted why', text: check.why }) : null,
    Array.isArray(check.fix) && check.fix.length
      ? el('pre', { class: 'fix', text: check.fix.join('\n') })
      : null,
  ].filter(Boolean);

  const summary = el('summary', {},
    el('span', { class: `pill ${check.status}`, text: STATUS_LABEL[check.status] || check.status }),
    el('span', { class: 'title', text: check.title }),
    el('span', { class: 'muted', text: check.detail || '' }));

  // A passing check needs no explanation, so it does not open.
  if (!detail.length) return el('div', { class: 'check' }, summary);
  return el('details', { class: 'check' }, summary, el('div', { class: 'check-body' }, ...detail));
}

function drawResult(page) {
  const target = $('[data-config-result]', page);
  const result = state.result;
  if (!result) return replace(target);

  const tone = result.failed ? 'bad' : result.warnings ? 'warn' : 'good';
  replace(target, [
    el('div', { class: 'grid' },
      statTile('Score', `${result.score}%`),
      statTile('Passing', `${result.passed} of ${result.total}`),
      statTile('To fix', String(result.failed)),
      statTile('Worth a look', String(result.warnings))),
    el('p', { class: `notice ${tone}`, style: 'margin-top:1rem' },
      result.failed
        ? `${result.failed} setting${result.failed === 1 ? '' : 's'} do not match the azmsh.net recommendations.`
        : result.warnings
          ? 'Nothing is wrong, but some settings are worth a look.'
          : 'This node matches the azmsh.net recommendations.'),
    ...result.categories.map((category) =>
      el('div', { class: 'panel', style: 'margin-top:1rem' },
        el('h3', { text: `${category.icon || ''} ${category.title}`.trim() }),
        el('div', { class: 'checks' }, category.checks.map(checkRow)))),
  ]);

  $('[data-config-exports]', page).hidden = false;
  // The optional panel is only useful once there is a config to apply
  // it to, and it appears with the export controls for that reason.
  const extras = $('[data-config-extras]', page);
  if (extras) extras.hidden = false;
}

/** Say which config is loaded, and from where. */
function drawSource(page) {
  const target = $('[data-config-source]', page);
  if (!state.config) return replace(target);
  const config = state.config;
  replace(target, el('p', { class: 'muted', style: 'font-size:.85rem' },
    el('strong', { text: config.longName || config.shortName || 'Unnamed node' }),
    ` — ${state.fileName || 'built from the recommendations'}`));
}

/* ---------------------------------------------------------------- */
/* Loading a config                                                  */

function setNotice(page, text, kind) {
  const notice = $('[data-config-notice]', page);
  notice.textContent = text || '';
  notice.hidden = !text;
  notice.className = `notice${kind ? ` ${kind}` : ''}`;
}

async function run(page) {
  if (!state.config) return;
  await loadLatestFirmware();
  state.result = ConfigChecker.check(state.config, state.region, state.nodeType);
  drawSource(page);
  drawResult(page);
}

async function loadFile(page, file) {
  if (!file) return;
  setNotice(page, '', '');
  hideDiagnostics(page);
  try {
    const buffer = await file.arrayBuffer();
    await ready();
    state.config = await ConfigParser.parse(buffer, file.name);
    state.fileName = file.name;
    await run(page);
  } catch (error) {
    state.config = null;
    state.result = null;
    replace($('[data-config-result]', page));
    $('[data-config-exports]', page).hidden = true;
    const extras = $('[data-config-extras]', page);
    if (extras) extras.hidden = true;
    setNotice(page, explain(error), 'bad');
    /*
     * "Today, when the checker breaks on a real config, we never find
     * out" (#119, and #61 before it). The reader is the only person
     * who can tell us, and they will not paste a stack trace they
     * cannot read or a config they should not share.
     *
     * The step is named from upstream's fixed enum rather than free
     * text, so the report says WHICH stage broke without saying
     * anything about the file.
     */
    recordFailure(page, STEPS.PARSE, error, file);
  }
}

/* ------------------------------------------------- diagnostics (#119) */

const diagnostics = new Diagnostics();

/** Note a failure and offer the reader a report they can read first. */
function recordFailure(page, step, error, file) {
  try {
    diagnostics.record({
      step,
      error,
      format: state.config && state.config.format,
      fileExt: file && file.name ? `.${String(file.name).split('.').pop()}` : null,
      fileSize: file && typeof file.size === 'number' ? file.size : null,
    });
    drawDiagnostics(page);
  } catch (failed) {
    // A broken bug-reporter must not replace the bug. The reader still
    // has the plain-English notice above.
    console.warn('diagnostics failed', failed);
  }
}

function hideDiagnostics(page) {
  const panel = $('[data-config-diagnostics]', page);
  if (panel) panel.hidden = true;
}

/**
 * Show the report, in full, before anything is copied.
 *
 * #119 asks for "a preview of exactly what will be copied, so the
 * reader can see there is nothing private in it". A claim that a
 * report is privacy-safe is worth less than the report itself sitting
 * on the page where they can read it.
 */
function drawDiagnostics(page) {
  const panel = $('[data-config-diagnostics]', page);
  if (!panel) return;
  const report = diagnostics.generateReport();
  const preview = $('[data-config-diagnostics-text]', page);
  if (preview) preview.textContent = report;
  panel.hidden = false;
  const button = $('[data-config-diagnostics-copy]', page);
  if (!button || button.dataset.wired === 'true') return;
  button.dataset.wired = 'true';
  button.addEventListener('click', async () => {
    const text = $('[data-config-diagnostics-text]', page).textContent;
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = 'Copied';
    } catch {
      // Same shape as the planner's copy control: say what the
      // browser did rather than pretending it worked. The text is on
      // the page already, so selecting it by hand still works.
      button.textContent = 'The browser refused — select the text above';
    }
    setTimeout(() => { button.textContent = 'Copy diagnostic report'; }, 4000);
  });
}

/** Turn a parse failure into something worth reading. */
function explain(error) {
  return (
    `${String((error && error.message) || error)}\n` +
    'Export a config from the Meshtastic app, or with ' +
    '`meshtastic --export-config`. Android .cfg, CLI YAML, and iOS or ' +
    'web JSON all work.'
  );
}

/* ---------------------------------------------------------------- */
/* Exports                                                           */

/**
 * Hand a file to the browser.
 *
 * The blob is made here and released straight after. Nothing is
 * uploaded: this is the same config, corrected, going back to the
 * person who loaded it.
 */
function download(data, filename, mimeType) {
  const blob = new Blob([data], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = el('a', { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function exportFixed(page) {
  if (!state.config) return;
  try {
    const extras = readExtras(page);
    if (extras === null) return;
    const fixed = ConfigFixer.fix(
      state.config, state.region, state.nodeType, extras.overrides, extras.mqtt,
    );
    const out = ConfigFixer.exportFixed(fixed, state.fileName, !state.fileName);
    download(out.data, out.filename, out.mimeType);
    setNotice(page, `Corrected config saved as ${out.filename}.`, '');
  } catch (error) {
    setNotice(page, `Could not build a corrected config: ${error.message || error}`, 'bad');
  }
}

/** A plain text report of the result, for sharing without the config. */
function exportReport(page) {
  const result = state.result;
  if (!result) return;
  const lines = [
    'azmsh.net config check',
    `Score ${result.score}% (${result.passed} of ${result.total} passing)`,
    `Region: ${state.region === 'metro' ? 'Phoenix and Tucson metro' : 'rural Arizona'}`,
    `Node: ${state.nodeType}`,
    '',
  ];
  for (const category of result.categories) {
    lines.push(category.title, '-'.repeat(category.title.length));
    for (const check of category.checks) {
      lines.push(`  [${(STATUS_LABEL[check.status] || check.status).toUpperCase()}] ${check.title}`);
      if (check.detail) lines.push(`      ${check.detail}`);
    }
    lines.push('');
  }
  download(lines.join('\n'), 'azmsh-config-report.txt', 'text/plain');
  setNotice(page, 'Report saved.', '');
}

/* ---------------------------------------------------------------- */
/* Wiring                                                            */

function remember() {
  try {
    localStorage.setItem(CHOICES, JSON.stringify({
      region: state.region,
      nodeType: state.nodeType,
    }));
  } catch {
    // A browser with storage turned off still works, it just forgets.
  }
}

function recall() {
  try {
    const saved = JSON.parse(localStorage.getItem(CHOICES) || '{}');
    if (saved.region) state.region = saved.region;
    if (saved.nodeType) state.nodeType = saved.nodeType;
  } catch {
    // Nothing saved, or nothing readable. The defaults stand.
  }
}

let wired = false;

function wire(page) {
  if (wired) return;
  wired = true;
  recall();

  for (const button of $$('[data-config-region]', page)) {
    button.addEventListener('click', () => {
      state.region = button.dataset.configRegion;
      remember();
      syncChoices(page);
      run(page);
    });
  }
  for (const button of $$('[data-config-node]', page)) {
    button.addEventListener('click', () => {
      state.nodeType = button.dataset.configNode;
      remember();
      syncChoices(page);
      run(page);
    });
  }

  wireExtras(page);
  wireSerial(page);

  const input = $('[data-config-file]', page);
  input.addEventListener('change', () => loadFile(page, input.files[0]));

  const drop = $('[data-config-drop]', page);
  // No click forwarding: the label does that natively now, and calling
  // `input.click()` from inside a label opens the picker twice.
  drop.addEventListener('dragover', (event) => {
    event.preventDefault();
    drop.classList.add('over');
  });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (event) => {
    event.preventDefault();
    drop.classList.remove('over');
    loadFile(page, event.dataTransfer.files[0]);
  });

  $('[data-config-new]', page).addEventListener('click', async () => {
    // The fixer encodes a channel URL, which needs the same types.
    await ready();
    state.config = ConfigFixer.buildNewConfig({
      longName: '',
      shortName: '',
      region: state.region,
      nodeType: state.nodeType,
      role: 0,
      hopLimit: 3,
    });
    state.fileName = '';
    setNotice(page, 'Built from the azmsh.net recommendations. Export it and import it to a node.', '');
    await run(page);
  });

  $('[data-config-fix]', page).addEventListener('click', () => exportFixed(page));
  $('[data-config-report]', page).addEventListener('click', () => exportReport(page));

  syncChoices(page);
}

function syncChoices(page) {
  for (const button of $$('[data-config-region]', page)) {
    button.setAttribute('aria-pressed', String(button.dataset.configRegion === state.region));
  }
  for (const button of $$('[data-config-node]', page)) {
    button.setAttribute('aria-pressed', String(button.dataset.configNode === state.nodeType));
  }
}

/** Called by the router when the Config check page is shown. */
async function show(page) {
  wire(page);
  loadLatestFirmware();
}

window.SonoranConfigCheck = { show };
if (window.sonoranConfigLoaded) window.sonoranConfigLoaded();


/* ------------------------------------- MQTT and editable values (#118) */

/*
 * Read the optional panel, or refuse the export and say why.
 *
 * Returns null when a value cannot be read, having shown the reason.
 * #118: "a bad value blocks export with a clear message" -- exporting
 * a config with a silently-dropped interval is worse than not
 * exporting, because the reader flashes it and finds out on the mesh.
 *
 * PRIVACY. The MQTT password is read straight out of the field and
 * handed to the fixer, which puts it in the downloaded file. It is
 * never written to `localStorage`, never sent anywhere, and there is
 * deliberately no "remember me": this page's whole promise is that
 * nothing leaves the device, and a stored broker password would be the
 * one thing on it worth stealing.
 */
function readExtras(page) {
  const panel = $('[data-config-extras]', page);
  const error = $('[data-config-extras-error]', page);
  if (error) { error.hidden = true; error.textContent = ''; }
  if (!panel) return { overrides: undefined, mqtt: undefined };

  const overrides = {};
  for (const field of $$('[data-override]', page)) {
    const raw = field.value.trim();
    if (!raw) continue;
    if (!Number.isFinite(secondsFrom(raw))) {
      if (error) {
        error.textContent =
          `"${raw}" is not a time this understands. Use 30m, 1.5h, 2d, or a ` +
          'number of seconds. Nothing was exported.';
        error.hidden = false;
      }
      field.focus();
      return null;
    }
    overrides[field.dataset.override] = raw;
  }

  const enabled = $('[data-mqtt="enabled"]', page);
  const mqtt = enabled && enabled.checked
    ? {
      enabled: true,
      address: $('[data-mqtt="address"]', page).value.trim(),
      username: $('[data-mqtt="username"]', page).value.trim(),
      password: $('[data-mqtt="password"]', page).value,
    }
    : undefined;

  return { overrides: Object.keys(overrides).length ? overrides : undefined, mqtt };
}

/*
 * The same forms upstream's `parseTimeInput` accepts, checked here so
 * the reader is told before the export rather than after.
 *
 * Not imported, because upstream keeps it inside a closure in
 * `fixer.js` and does not export it. So this is a second copy of one
 * regular expression, and the risk is that they drift. The test for
 * this holds BOTH against the same table of inputs, which is the
 * cheapest way to find out if they ever do.
 */
function secondsFrom(text) {
  const value = String(text).trim().toLowerCase();
  if (!value) return NaN;
  const match = value.match(
    /^([0-9]*\.?[0-9]+)\s*(d|days?|h|hr|hrs|hours?|m|min|mins|minutes?|s|sec|secs|seconds?)?$/,
  );
  if (!match) {
    const plain = Number(value);
    return Number.isNaN(plain) ? NaN : plain;
  }
  const amount = parseFloat(match[1]);
  const unit = match[2] || '';
  if (!unit || unit.startsWith('s')) return Math.round(amount);
  if (unit.startsWith('m')) return Math.round(amount * 60);
  if (unit.startsWith('h')) return Math.round(amount * 3600);
  if (unit.startsWith('d')) return Math.round(amount * 86400);
  return Math.round(amount);
}

/** Put every editable field back to the recommendation. */
function wireExtras(page) {
  const reset = $('[data-config-extras-reset]', page);
  if (reset) {
    reset.addEventListener('click', () => {
      for (const field of $$('[data-override]', page)) field.value = '';
      const error = $('[data-config-extras-error]', page);
      if (error) error.hidden = true;
    });
  }
}


/* ------------------------------------------ connect by USB (#116, #117) */

/*
 * The button is shown only when the browser can actually do it, and
 * replaced by one line when it cannot. A control that fails when
 * pressed is worse than one that explains itself first -- #116 asks
 * for exactly that wording: "USB needs Chrome or Edge on a computer.
 * You can still upload an exported config."
 */
function wireSerial(page) {
  const panel = $('[data-serial-panel]', page);
  if (!panel) return;
  panel.hidden = false;

  const status = $('[data-serial-status]', page);
  const connect = $('[data-serial-connect]', page);
  const reason = serialUnavailableReason();
  if (reason) {
    connect.hidden = true;
    status.textContent = reason;
    status.hidden = false;
    return;
  }

  let port = null;
  const say = (message, tone = '') => {
    status.textContent = message;
    status.className = `notice${tone ? ` ${tone}` : ''}`;
    status.hidden = !message;
  };

  const release = async () => {
    // Belt and braces: `readConfig` closes the port itself, and this
    // runs if the reader navigates away mid-read. A port left open
    // blocks the Meshtastic app and the CLI.
    if (!port) return;
    try { await port.close(); } catch { /* already closed */ }
    port = null;
    $('[data-serial-disconnect]', page).hidden = true;
  };
  window.addEventListener('pagehide', release);

  connect.addEventListener('click', async () => {
    try {
      // Must be inside the click handler: the browser only grants a
      // port chooser in response to a gesture.
      port = await navigator.serial.requestPort();
      $('[data-serial-disconnect]', page).hidden = false;
      say('Connecting…');
      const { root, FromRadio, ToRadio } = await serialSchema();
      const config = await readConfig(port, {
        decode: (bytes) => FromRadio.toObject(FromRadio.decode(bytes), { longs: Number }),
        encodeWantConfig: (id) =>
          ToRadio.encode(ToRadio.fromObject({ wantConfigId: id })).finish(),
        onProgress: (line) => say(line),
      });
      port = null;
      $('[data-serial-disconnect]', page).hidden = true;
      state.config = config;
      state.fileName = 'node-over-usb';
      say('Read the configuration. Checking it…');
      await run(page);
      drawSerialPlan(page);
      say('');
    } catch (error) {
      await release();
      say(String((error && error.message) || error), 'bad');
      recordFailure(page, STEPS.SERIAL_READ, error, null);
    }
  });

  $('[data-serial-disconnect]', page).addEventListener('click', release);
  $('[data-serial-apply]', page).addEventListener('click', () => applySerial(page));
}

/** protobuf.js over the generated descriptor, built once. */
let serialRoot = null;
async function serialSchema() {
  if (serialRoot) return serialRoot;
  const pb = window.protobuf;
  if (!pb) throw new Error('The protobuf library did not load, so USB is unavailable.');
  const root = pb.Root.fromJSON(window.MeshtasticSerialProto);
  serialRoot = {
    root,
    FromRadio: root.lookupType('meshtastic.FromRadio'),
    ToRadio: root.lookupType('meshtastic.ToRadio'),
  };
  return serialRoot;
}

/**
 * Show every change before anything is written (#117).
 *
 * One tick box per row, so nothing can be written that was not shown
 * and chosen. Protected rows are not offered at all -- they are
 * counted in a line underneath instead, because a tick box implies a
 * choice the reader should not be casually making with a PSK.
 */
function drawSerialPlan(page) {
  const wrap = $('[data-serial-plan]', page);
  if (!wrap || !state.config || !state.result) return;
  const fixed = ConfigFixer.fix(state.config, state.region, state.nodeType);
  const rows = planChanges(state.config, fixed);
  const offered = rows.filter((row) => !row.protected);
  const guarded = rows.filter((row) => row.protected);

  replace($('[data-serial-rows]', page), offered.map((row) => el('li', {},
    el('label', { class: 'stack' },
      el('input', { type: 'checkbox', checked: true, 'data-serial-row':
        `${row.group}.${row.section}.${row.field}` }),
      ` ${row.section}.${row.field}: ${format(row.from)} → ${format(row.to)}`))));

  const protectedNote = $('[data-serial-protected]', page);
  protectedNote.textContent = guarded.length
    ? `${guarded.length} security setting${guarded.length === 1 ? '' : 's'} `
      + `(${guarded.map((r) => `${r.section}.${r.field}`).join(', ')}) `
      + 'will not be written. Changing these can lock you out of your own node.'
    : '';
  protectedNote.hidden = !guarded.length;

  const mesh = offered.filter((row) => row.changesMesh);
  const warning = $('[data-serial-mesh-warning]', page);
  warning.textContent = mesh.length
    ? 'This changes which mesh the node is on: '
      + `${mesh.map((r) => `${r.field} ${format(r.from)} → ${format(r.to)}`).join(', ')}. `
      + 'It will stop hearing its current mesh.'
    : '';
  warning.hidden = !mesh.length;

  wrap.hidden = !offered.length;
}

function format(value) {
  if (value === undefined || value === null) return 'unset';
  return String(value);
}

/** Write what was ticked, after a backup and a confirmation. */
async function applySerial(page) {
  const fixed = ConfigFixer.fix(state.config, state.region, state.nodeType);
  const ticked = new Set(
    $$('[data-serial-row]', page).filter((box) => box.checked)
      .map((box) => box.dataset.serialRow),
  );
  const rows = planChanges(state.config, fixed)
    .filter((row) => ticked.has(`${row.group}.${row.section}.${row.field}`));
  if (!rows.length) return;

  if ($('[data-serial-backup]', page).checked) {
    // Before, not after. A backup written after a failed write is a
    // backup of whatever the node ended up as.
    const out = ConfigFixer.exportFixed(state.config, 'node-backup', true);
    download(out.data, out.filename, out.mimeType);
  }

  const name = (state.config.myInfo && state.config.myInfo.myNodeNum) || 'this node';
  // eslint-disable-next-line no-alert
  if (!window.confirm(`Write ${rows.length} setting${rows.length === 1 ? '' : 's'} to ${name} and reboot it?`)) {
    return;
  }

  const status = $('[data-serial-status]', page);
  try {
    const port = await navigator.serial.requestPort();
    await port.open({ baudRate: 115200 });
    const { root } = await serialSchema();
    const AdminMessage = root.lookupType('meshtastic.AdminMessage');
    const writer = port.writable.getWriter();
    const result = await applyChanges(rows, {
      send: async (message) => {
        const bytes = AdminMessage.encode(AdminMessage.fromObject(message)).finish();
        await writer.write(serialFrame(bytes));
      },
      onProgress: (line) => { status.textContent = line; status.hidden = false; },
    });
    writer.releaseLock();
    await port.close();
    status.textContent = `Wrote ${result.written} setting${result.written === 1 ? '' : 's'}. `
      + 'The node is rebooting; reconnect to check it took.';
    status.hidden = false;
  } catch (error) {
    status.textContent = String((error && error.message) || error);
    status.className = 'notice bad';
    status.hidden = false;
    recordFailure(page, STEPS.SERIAL_APPLY, error, null);
  }
}
