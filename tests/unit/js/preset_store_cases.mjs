/*
 * The preset the whole site is looking at.
 *
 * Six pages used to ask this question separately -- the map's link layer,
 * coverage, gaps, the graph's tab strip, the leaderboards, and the chat
 * channel list -- so a reader could have the map on one preset and the
 * gaps page on another. These cases cover the store that replaced them,
 * and especially what it REFUSES: a stored name that is no longer on
 * offer must not pin the site to a preset with nothing in it.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SOURCE = readFileSync(
  new URL('../../../src/sonoran/web/static/preset.js', import.meta.url), 'utf8',
);

/** A fresh store, with its own storage and its own server default. */
function load({ saved = null, configured = 'MediumFast', storage = true } = {}) {
  const store = saved === null ? {} : { 'sonoran.preset': saved };
  const localStorage = storage
    ? {
      getItem: (key) => (key in store ? store[key] : null),
      setItem: (key, value) => { store[key] = value; },
    }
    // A private window: both accessors throw. The store has to work.
    : {
      getItem() { throw new Error('blocked'); },
      setItem() { throw new Error('blocked'); },
    };
  const sandbox = {
    window: { SONORAN: { defaultPreset: configured }, localStorage },
    console: { warn() {} },
  };
  vm.createContext(sandbox);
  new vm.Script(SOURCE).runInContext(sandbox);
  return { P: sandbox.window.SonoranPreset, store };
}

let failed = 0;
const eq = (name, got, want) => {
  const a = JSON.stringify(got); const b = JSON.stringify(want);
  if (a === b) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${a}\n       want ${b}`); }
};

// --- the default ----------------------------------------------------
eq('Medium Fast is the default', load().P.current(), 'MediumFast');
eq('the deployment setting is honoured',
  load({ configured: 'LongFast' }).P.current(), 'LongFast');
eq('a default that is not on offer falls back to one that is',
  load({ configured: 'ShortTurbo' }).P.current(), 'MediumFast');

// --- choosing and keeping -------------------------------------------
{
  const { P, store } = load();
  eq('choosing returns true', P.set('LongFast'), true);
  eq('and takes effect', P.current(), 'LongFast');
  eq('and is written down', store['sonoran.preset'], 'LongFast');
  eq('choosing the same one again is not a change', P.set('LongFast'), false);
  eq('an unknown preset is refused', P.set('Nonsense'), false);
  eq('and changes nothing', P.current(), 'LongFast');
}
eq('a saved choice survives a reload',
  load({ saved: 'LongFast' }).P.current(), 'LongFast');

// --- what it refuses to honour --------------------------------------
// The case that matters most. A name that was valid once -- a deployment
// that stopped running it, or a hand-edited value -- would otherwise pin
// every page to a preset with nothing in it, and the reader would have no
// way to tell why the whole site was empty.
eq('a saved preset that is no longer offered is ignored',
  load({ saved: 'ShortTurbo' }).P.current(), 'MediumFast');
eq('a saved rubbish value is ignored',
  load({ saved: '{}' }).P.current(), 'MediumFast');

// --- storage that throws --------------------------------------------
{
  const { P } = load({ storage: false });
  eq('a blocked storage still has a default', P.current(), 'MediumFast');
  eq('and can still be changed for this visit', P.set('LongFast'), true);
  eq('which takes effect', P.current(), 'LongFast');
}

// --- the list on offer ----------------------------------------------
{
  const { P } = load();
  eq('starts on the two this mesh runs', P.options(), ['MediumFast', 'LongFast']);
  eq('a real list replaces it', P.setAvailable(['MediumFast', 'LongFast', 'ShortFast']), false);
  eq('and is kept in the order given',
    P.options(), ['MediumFast', 'LongFast', 'ShortFast']);
  eq('an empty list is ignored', P.setAvailable([]), false);
  eq('so the old list stands', P.options().length, 3);
}
{
  // Narrowing the list can move the reader's choice, and that counts as
  // a change so the pages redraw.
  const { P } = load();
  P.set('LongFast');
  let told = null;
  P.onChange((name) => { told = name; });
  eq('narrowing away the chosen preset moves it', P.setAvailable(['MediumFast']), true);
  eq('and announces the move', told, 'MediumFast');
}

// --- subscribers ----------------------------------------------------
{
  const { P } = load();
  const seen = [];
  const off = P.onChange((name) => seen.push(name));
  P.set('LongFast');
  off();
  P.set('MediumFast');
  eq('a subscriber hears changes until it unsubscribes', seen, ['LongFast']);
}
{
  // One bad subscriber must not stop the others: half the site following
  // the new preset while the other half keeps the old one is the exact
  // inconsistency this module exists to remove.
  const { P } = load();
  const seen = [];
  P.onChange(() => { throw new Error('boom'); });
  P.onChange((name) => seen.push(name));
  P.set('LongFast');
  eq('a throwing subscriber does not stop the rest', seen, ['LongFast']);
}

// --- the chat rule Will asked for -----------------------------------
// The live payload shape, verbatim from /api/chat/overview.
const SECTIONS = [
  { channel: 'MediumFast', group: 'Presets', preset: 'MediumFast' },
  { channel: 'LongFast', group: 'Presets', preset: 'LongFast' },
  { channel: 'Weather', group: 'Weather', preset: '' },
  { channel: 'Traffic', group: 'Traffic', preset: '' },
  { channel: 'azmsh', group: 'Testing', preset: '' },
  { channel: 'Trivia', group: 'Games', preset: '' },
];
const names = (list) => list.map((item) => item.channel);
{
  const { P } = load();
  eq('on Medium Fast: the preset and the topic channels',
    names(P.channelsFor(SECTIONS)),
    ['MediumFast', 'Weather', 'Traffic', 'azmsh', 'Trivia']);
  P.set('LongFast');
  eq('on Long Fast: only Long Fast', names(P.channelsFor(SECTIONS)), ['LongFast']);
  // Named explicitly because Will named them.
  const hidden = ['Weather', 'Traffic', 'azmsh', 'MediumFast'];
  eq('Weather, Traffic, azmsh and MediumFast are all hidden',
    hidden.some((name) => names(P.channelsFor(SECTIONS)).includes(name)), false);
}
{
  // A deployment whose default is LongFast gets the same behaviour
  // without editing the rule: the topic channels ride on ITS default.
  const { P } = load({ configured: 'LongFast' });
  eq('the topic channels follow the deployment default, not the literal MediumFast',
    names(P.channelsFor(SECTIONS)), ['LongFast', 'Weather', 'Traffic', 'azmsh', 'Trivia']);
}
eq('no sections is not a crash', load().P.channelsFor(null), []);

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
