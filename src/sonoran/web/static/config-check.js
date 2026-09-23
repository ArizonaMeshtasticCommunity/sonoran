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
    setNotice(page, explain(error), 'bad');
  }
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
    const fixed = ConfigFixer.fix(state.config, state.region, state.nodeType);
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
