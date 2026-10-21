/*
 * The coverage settings panel (#334): its defaults, its count, its reset,
 * its address and its storage.
 *
 * The cases that matter are these:
 *
 * - The defaults are the map Logan and Tyler asked for: precise
 *   positions, routers and repeaters, the usable layer, every role.
 * - A plain `#coverage` link always means that map. A stored choice
 *   must never turn the same link into the approximate map.
 * - The approximate map is never shown when the run did not compute
 *   it. The page must not pretend.
 * - Storage that throws costs the memory of the choice, and nothing else.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SOURCE = readFileSync(
  new URL('../../../src/sonoran/web/static/coverage-settings.js', import.meta.url), 'utf8',
);

function load() {
  const sandbox = { window: {}, JSON, Number, Date, URLSearchParams };
  vm.createContext(sandbox);
  new vm.Script(SOURCE).runInContext(sandbox);
  return sandbox.window.SonoranCoverageSettings;
}

function storage(saved = {}) {
  const store = { ...saved };
  return {
    store,
    getItem: (key) => (key in store ? store[key] : null),
    setItem: (key, value) => { store[key] = String(value); },
    removeItem: (key) => { delete store[key]; },
  };
}

const refused = {
  getItem() { throw new Error('blocked'); },
  setItem() { throw new Error('blocked'); },
  removeItem() { throw new Error('blocked'); },
};

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) console.log(`  PASS ${name}`);
  else {
    failed += 1;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  }
};

const C = load();

const PRECISE_ONLY = [
  { key: 'infrastructure', label: 'Routers and repeaters', approximate: false },
  { key: 'extended', label: 'Also nodes that repeat', approximate: false },
];
const WITH_APPROXIMATE = [
  ...PRECISE_ONLY,
  { key: 'infrastructure_approximate', label: 'Routers and repeaters, rounded positions included', approximate: true },
  { key: 'extended_approximate', label: 'Also nodes that repeat, rounded positions included', approximate: true },
];

// --- the defaults are Logan's and Tyler's -----------------------------
{
  const d = C.defaults();
  eq('the default map is routers and repeaters', d.base, 'infrastructure');
  eq('the default map is precise only', d.approximate, false);
  eq('the default layer is usable', d.layer, 'usable');
  eq('no role is hidden by default', d.hiddenRoles, []);
  eq('any time by default', d.heard, 'any');
  eq('moving nodes shown by default', d.hideMoving, false);
  eq('uncertainty circles off by default', d.circles, false);
  eq('fully opaque by default, as today', d.opacity, 1);
  eq('every display layer on by default', [d.showMap, d.showNodes, d.showSignal], [true, true, true]);
  eq('the defaults count nothing', C.changedCount(d), 0);
  d.hiddenRoles.push('CLIENT');
  eq('the defaults are a fresh copy each time', C.defaults().hiddenRoles, []);
}

// --- the count is of settings, not of controls -------------------------
{
  const s = C.defaults();
  s.hiddenRoles = ['CLIENT', 'SENSOR', 'TRACKER'];
  eq('three hidden roles are one setting', C.changedCount(s), 1);
  s.layer = 'downlink';
  s.approximate = true;
  s.heard = '24h';
  s.circles = true;
  s.hideMoving = true;
  s.opacity = 0.5;
  s.base = 'extended';
  s.showMap = false;
  eq('every changed setting counts once', C.changedCount(s), 9);
  eq('reset is the defaults again', C.changedCount(C.reset()), 0);
  // A diagnostic run's first map is not `infrastructure`. Its own first
  // map is the default there, so landing on it is not a change.
  const diag = { ...C.defaults(), base: 'diagnostic' };
  eq('the run\'s own first map is not a change', C.changedCount(diag, { defaultBase: 'diagnostic' }), 0);
  eq('without that it is', C.changedCount(diag), 1);
}

// --- the site set ------------------------------------------------------
{
  eq('the approximate toggle picks the matching approximate set',
    C.resolveSiteSet(WITH_APPROXIMATE, 'extended', true),
    { key: 'extended_approximate', base: 'extended', approximate: true, approximateAvailable: true });
  eq('off, the precise set',
    C.resolveSiteSet(WITH_APPROXIMATE, 'infrastructure', false),
    { key: 'infrastructure', base: 'infrastructure', approximate: false, approximateAvailable: true });
  eq('asked for, but not computed: the precise set, and it says so',
    C.resolveSiteSet(PRECISE_ONLY, 'infrastructure', true),
    { key: 'infrastructure', base: 'infrastructure', approximate: false, approximateAvailable: false });
  eq('an unknown map falls to the run\'s first, never to nothing',
    C.resolveSiteSet(PRECISE_ONLY, 'nonsense', false).key, 'infrastructure');
  eq('a run from before site sets is the infrastructure map',
    C.resolveSiteSet([], 'extended', true),
    { key: 'infrastructure', base: 'infrastructure', approximate: false, approximateAvailable: false });
  // A run made before #315 has no `approximate` field; the name says it.
  eq('the name marks an approximate set when the flag is missing',
    C.baseSets([{ key: 'infrastructure' }, { key: 'infrastructure_approximate' }]).map((s) => s.key),
    ['infrastructure']);
  eq('only the precise sets are map sources', C.baseSets(WITH_APPROXIMATE).map((s) => s.key),
    ['infrastructure', 'extended']);
}

// --- the address -------------------------------------------------------
{
  eq('a plain link is the default map', C.fromHash('#coverage'),
    { base: 'infrastructure', approximate: false, layer: 'usable', floor: 0 });
  eq('a link names its map',
    C.fromHash('#coverage?set=extended&approx=1&layer=downlink'),
    { base: 'extended', approximate: true, layer: 'downlink', floor: 0 });
  eq('an unknown layer is the default', C.fromHash('#coverage?layer=sideways').layer, 'usable');
  eq('a set name that is not a set name is the default',
    C.fromHash('#coverage?set=..%2Fetc').base, 'infrastructure');
  eq('an approximate set name is not a map source; approx says that',
    C.fromHash('#coverage?set=infrastructure_approximate').base, 'infrastructure');
  eq('approx must say 1', C.fromHash('#coverage?approx=yes').approximate, false);
  eq('the default map writes a plain link', C.toHash(C.defaults()), '#coverage');
  eq('a changed map writes only what changed',
    C.toHash({ ...C.defaults(), approximate: true, layer: 'uplink' }), '#coverage?approx=1&layer=uplink');
  const round = { ...C.defaults(), base: 'extended', approximate: true, layer: 'downlink' };
  eq('a written link reads back as the same map', C.fromHash(C.toHash(round)),
    { base: 'extended', approximate: true, layer: 'downlink', floor: 0 });
  eq('the address says whether it names anything', [C.hashNamesMap('#coverage'),
    C.hashNamesMap('#coverage?layer=uplink')], [false, true]);
  eq('display filters never reach the address',
    C.toHash({ ...C.defaults(), hiddenRoles: ['CLIENT'], circles: true, opacity: 0.4 }), '#coverage');
}

// --- storage holds the display filters only ---------------------------
{
  const local = storage();
  const chosen = {
    ...C.defaults(),
    base: 'extended',
    approximate: true,
    layer: 'downlink',
    hiddenRoles: ['CLIENT'],
    heard: '7d',
    hideMoving: true,
    circles: true,
    opacity: 0.6,
  };
  eq('a save reports it was kept', C.save(local, chosen), true);
  const back = C.load(local);
  eq('the display filters come back',
    [back.hiddenRoles, back.heard, back.hideMoving, back.circles, back.opacity],
    [['CLIENT'], '7d', true, true, 0.6]);
  eq('the map choices do not: a plain link must mean the precise map',
    [back.base, back.approximate, back.layer], ['infrastructure', false, 'usable']);
}
{
  eq('refused storage loads the defaults', C.load(refused), C.defaults());
  eq('refused storage saves nothing and does not throw', C.save(refused, C.defaults()), false);
  eq('no storage at all loads the defaults', C.load(null), C.defaults());
}
{
  const junk = storage({ 'sonoran.coverage.settings': '{"heard":"forever","hiddenRoles":"CLIENT","opacity":7,"circles":"yes"}' });
  const got = C.load(junk);
  eq('stored junk is refused field by field',
    [got.heard, got.hiddenRoles, got.opacity, got.circles], ['any', [], 1, false]);
  eq('a stored value that is not an object is ignored',
    C.load(storage({ 'sonoran.coverage.settings': '[1,2]' })), C.defaults());
  eq('unparseable storage is ignored',
    C.load(storage({ 'sonoran.coverage.settings': '{' })), C.defaults());
  const roles = C.load(storage({ 'sonoran.coverage.settings': '{"hiddenRoles":["CLIENT","<img>","NULL","CLIENT"]}' }));
  eq('a hidden role must look like a role, once each', roles.hiddenRoles, ['CLIENT', 'NULL']);
}
{
  // A viewer who set the opacity before this panel existed keeps it.
  const old = storage({ 'sonoran.coverage.signalOpacity': '0.35' });
  eq('the old opacity key is still read', C.load(old).opacity, 0.35);
  eq('a saved zero is not a preference', C.load(storage({ 'sonoran.coverage.signalOpacity': '0' })).opacity, 1);
  const local = storage();
  C.save(local, { ...C.defaults(), opacity: 0 });
  eq('a zero is not saved either', C.load(local).opacity, 1);
  const reset = storage({ 'sonoran.coverage.signalOpacity': '0.35' });
  C.save(reset, C.reset());
  eq('reset clears the old key too, or it comes back on reload', C.load(reset).opacity, 1);
}

// --- which nodes a marker is drawn for ---------------------------------
{
  const now = Date.parse('2026-10-08T12:00:00Z');
  const hour = 3600 * 1000;
  const at = (hours) => new Date(now - hours * hour).toISOString();
  const router = { role: 'ROUTER', last_heard: at(2) };
  const old = { role: 'ROUTER', last_heard: at(30) };
  const older = { role: 'ROUTER', last_heard: at(200) };
  const tracker = { role: 'TRACKER', last_heard: at(1) };
  const tak = { role: 'TAK_TRACKER', last_heard: at(1) };
  const nameless = { role: null, last_heard: at(1) };
  const silent = { role: 'ROUTER', last_heard: null };
  const d = C.defaults();
  const shown = (s, node) => C.nodeShown(node, s, now);
  eq('by default every node is drawn',
    [router, old, older, tracker, tak, nameless, silent].map((n) => shown(d, n)),
    [true, true, true, true, true, true, true]);
  eq('a hidden role is hidden', shown({ ...d, hiddenRoles: ['ROUTER'] }, router), false);
  eq('no role reported is a role of its own here', shown({ ...d, hiddenRoles: ['NULL'] }, nameless), false);
  eq('and hiding it leaves the clients', shown({ ...d, hiddenRoles: ['NULL'] }, router), true);
  eq('24 h keeps the recent', shown({ ...d, heard: '24h' }, router), true);
  eq('24 h drops a node heard 30 h ago', shown({ ...d, heard: '24h' }, old), false);
  eq('7 d keeps it', shown({ ...d, heard: '7d' }, old), true);
  eq('7 d drops 200 h', shown({ ...d, heard: '7d' }, older), false);
  eq('a node never heard is not "heard in 24 h"', shown({ ...d, heard: '24h' }, silent), false);
  eq('moving nodes are the two tracker roles',
    [tracker, tak, router].map((n) => shown({ ...d, hideMoving: true }, n)), [false, false, true]);
  eq('the moving roles are named', C.MOVING_ROLES, ['TRACKER', 'TAK_TRACKER']);
  eq('the roles present, once each, no role reported last',
    C.rolesPresent([router, tracker, nameless, old, tak]), ['ROUTER', 'TAK_TRACKER', 'TRACKER', 'NULL']);
}

// --- where an uncertainty circle goes -----------------------------------
{
  const sites = [
    { node_id: '!a', used: true, position_deviation_m: 1200, position_source: 'reported' },
    { node_id: '!b', used: true, position_deviation_m: null, position_source: 'reported' },
    { node_id: '!c', used: true, position_deviation_m: 900, position_source: 'operator' },
    { node_id: '!d', used: false, position_deviation_m: 900 },
    { node_id: '!e', used: true, position_deviation_m: 500 },
  ];
  const rows = [
    { node_id: '!a', lat: 33.4, lon: -112.1 },
    { node_id: '!b', lat: 33.5, lon: -112.2 },
    { node_id: '!c', lat: 33.6, lon: -112.3 },
    { node_id: '!d', lat: 33.7, lon: -112.4 },
  ];
  eq('a circle for each used, rounded, reported site with a position',
    C.uncertaintyCircles(sites, rows),
    [{ node_id: '!a', lat: 33.4, lon: -112.1, radius: 1200 }]);
  eq('no sites, no circles', C.uncertaintyCircles(undefined, rows), []);
}

// --- what the legend says ---------------------------------------------
{
  eq('the precise map says so', C.mapWords('Routers and repeaters', false),
    'Routers and repeaters · precise positions only');
  eq('the approximate map says so', C.mapWords('Routers and repeaters', true),
    'Routers and repeaters · rounded positions included');
}

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
