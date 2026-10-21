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
// Every firmware preset is on offer since #383, so the default that is
// not on offer is a name that is not a preset at all.
eq('a default that is not on offer falls back to one that is',
  load({ configured: 'NotAPreset' }).P.current(), 'MediumFast');

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
// Since #383 that is a name no preset has: every firmware preset stays
// on offer, so a saved ShortTurbo is a real choice and is kept.
eq('a saved preset that is no longer offered is ignored',
  load({ saved: 'LongModerate' }).P.current(), 'MediumFast');
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
  // The two this mesh runs come first, then every other preset (#383).
  eq('starts on the two this mesh runs', P.options().slice(0, 2), ['MediumFast', 'LongFast']);
  eq('a real list replaces it', P.setAvailable(['MediumFast', 'LongFast', 'ShortFast']), false);
  eq('and is kept in the order given',
    P.options().slice(0, 3), ['MediumFast', 'LongFast', 'ShortFast']);
  eq('an empty list is ignored', P.setAvailable([]), false);
  eq('so the old list stands', P.options().slice(0, 3), ['MediumFast', 'LongFast', 'ShortFast']);
}
{
  // Narrowing the list can move the reader's choice, and that counts as
  // a change so the pages redraw.
  // A preset the firmware runs never leaves the list (#383), so the
  // narrowed-away one is a name only the server offered.
  const { P } = load();
  P.setAvailable(['MediumFast', 'LongFast', 'Custom9']);
  P.set('Custom9');
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


// --- every preset, and several at once (#383) -------------------------
{
  const { P } = load();
  // Will: "Add all of the other presets for people to select."
  for (const name of ['LongFast', 'LongSlow', 'LongMod', 'LongTurbo', 'MediumFast',
    'MediumSlow', 'ShortFast', 'ShortSlow', 'ShortTurbo']) {
    eq(`${name} is on offer before any server list`, P.options().includes(name), true);
  }
  eq('a preset with no traffic yet can be chosen', P.set('ShortTurbo'), true);
  eq('and is the one in force', P.current(), 'ShortTurbo');
  eq('and survives a narrower server list', (P.setAvailable(['MediumFast']), P.current()), 'ShortTurbo');
  eq('LongModerate is not a channel name: firmware says LongMod', P.set('LongModerate'), false);
}
{
  // "Make MediumFast the default solo selected."
  const { P } = load();
  eq('the default is Medium Fast alone', P.selected(), ['MediumFast']);
  eq('which is not several', P.isSeveral(), false);
  eq('and asks the API for Medium Fast', P.query(), 'MediumFast');
}
{
  // "Would be awesome to ... select multiple presets as well."
  const { P, store } = load();
  const seen = [];
  P.onChange((name) => seen.push(name));
  eq('two presets can be chosen', P.setMany(['LongFast', 'MediumFast']), true);
  eq('both are chosen, in menu order', P.selected(), ['MediumFast', 'LongFast']);
  eq('that is several', P.isSeveral(), true);
  eq('and not all', P.isAll(), false);
  eq('the API is asked for both', P.query(), 'MediumFast,LongFast');
  eq('a one-preset page draws the default among them', P.single(), 'MediumFast');
  eq('current() names that one preset, never a list', P.current(), 'MediumFast');
  eq('both are written down', store['sonoran.preset'], 'MediumFast,LongFast');
  eq('each counts as matching', [P.matches('LongFast'), P.matches('MediumFast'), P.matches('ShortFast')],
    [true, true, false]);
  eq('the same pair again is not a change', P.setMany(['MediumFast', 'LongFast']), false);
  eq('subscribers heard one change', seen.length, 1);
}
{
  const { P } = load();
  P.setMany(['LongFast', 'ShortFast']);
  eq('without the default, a one-preset page draws the first chosen', P.single(), 'LongFast');
}
{
  const { P } = load();
  eq('an empty choice is refused', P.setMany([]), false);
  eq('a list with a name that is not a preset is refused whole', P.setMany(['LongFast', 'azmsh']), false);
  eq('and nothing changed', P.selected(), ['MediumFast']);
}
{
  const { P } = load();
  eq('a toggle adds a preset', P.toggle('LongFast'), true);
  eq('to the one already chosen', P.selected(), ['MediumFast', 'LongFast']);
  eq('a toggle takes one out', P.toggle('MediumFast'), true);
  eq('leaving the other', P.selected(), ['LongFast']);
  eq('the last one cannot be taken out', P.toggle('LongFast'), false);
  eq('so one stays chosen', P.selected(), ['LongFast']);
}
{
  const { P } = load();
  P.set(P.ALL);
  eq('under All, a toggle takes one preset out', P.toggle('LongFast'), true);
  eq('and every other stays', P.selected().includes('LongFast') || P.selected().length < 2, false);
  eq('choosing one alone after several leaves it alone', (P.set('LongFast'), P.selected()), ['LongFast']);
}
// Backward compatible: what older builds stored still loads.
eq('an old stored single name loads', load({ saved: 'LongFast' }).P.selected(), ['LongFast']);
eq('an old stored "All" loads', load({ saved: '*' }).P.isAll(), true);
eq('a stored pair loads', load({ saved: 'LongFast,MediumFast' }).P.selected(), ['MediumFast', 'LongFast']);
eq('a stored pair with one bad name keeps the good one',
  load({ saved: 'LongFast,Nonsense' }).P.selected(), ['LongFast']);
eq('a stored list of nothing usable is the default',
  load({ saved: ',,' }).P.selected(), ['MediumFast']);

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
