/*
 * The chosen preset has to survive a reload (#177 follow-up).
 *
 * Reported as "still set to LF even if I set it to MF". The picker kept
 * its choice in `state.preset` alone, which is closure state: switching
 * worked and then reopening #gaps dropped it, so the page went back to
 * whatever the server offered first.
 *
 * Run against a fake address bar rather than by reading the source, so
 * these exercise the behaviour that was broken.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SOURCE = readFileSync(
  new URL('../../../src/sonoran/web/static/gaps.js', import.meta.url), 'utf8',
);

/** A fresh module with its own fake address bar. */
function load(hash) {
  const replaced = [];
  const sandbox = {
    window: {},
    document: { querySelector: () => null, querySelectorAll: () => [] },
    location: { hash },
    history: { replaceState: (_s, _t, url) => { replaced.push(url); sandbox.location.hash = url; } },
    URLSearchParams,
    console: { warn() {}, log() {} },
  };
  sandbox.window.location = sandbox.location;
  sandbox.window.history = sandbox.history;
  vm.createContext(sandbox);
  new vm.Script(SOURCE).runInContext(sandbox);
  return { api: sandbox.window.SonoranGaps, replaced, sandbox };
}

let failed = 0;
const eq = (name, got, want) => {
  const a = JSON.stringify(got); const b = JSON.stringify(want);
  if (a === b) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${a}\n       want ${b}`); }
};

// --- reading the address --------------------------------------------
eq('a named preset is read back', load('#gaps?channel=MediumFast').api.presetFromAddress(),
  'MediumFast');
eq('a bare #gaps names none', load('#gaps').api.presetFromAddress(), null);
eq('an empty channel is not a choice', load('#gaps?channel=').api.presetFromAddress(), null);
// Another page's query must not be claimed: #map carries its own
// ?preset= for a focused node, and reading it here would apply a map
// setting to the gaps page.
eq('another page is left alone', load('#map/node/x?channel=LongFast').api.presetFromAddress(),
  null);
eq('other keys are ignored', load('#gaps?filter=bad').api.presetFromAddress(), null);
eq('a preset among other keys is found',
  load('#gaps?filter=bad&channel=ShortSlow').api.presetFromAddress(), 'ShortSlow');

// --- the address no longer WRITES ----------------------------------
//
// `writeAddress` is gone. The gaps page owned its preset while it had a
// picker and had to keep the choice across a reload; the menu owns it now
// and keeps it in localStorage, so nothing here writes the address. The
// inbound half is what remains, and it does MORE than before: a link
// naming a preset moves the whole site, so the menu cannot end up
// disagreeing with the page.
{
  const { api } = load('#gaps?channel=MediumFast');
  eq('nothing writes the address any more', typeof api.writeAddress, 'undefined');
  eq('but an inbound link is still read', api.presetFromAddress(), 'MediumFast');
}

// --- what show() actually asks the server for -----------------------
// The helpers above can be perfect while `show` never calls them, which
// is exactly the bug: the address was readable and nothing read it. So
// this drives show() and watches the URL it fetches.
async function requestedUrl(hash) {
  const asked = [];
  const sandbox = {
    window: {},
    // `baseURI` and `URL` are both needed: gaps.js builds every request
    // with `new URL(path, document.baseURI)`, so without them the fetch
    // throws before it happens and this case would pass on silence.
    document: { querySelector: () => null, querySelectorAll: () => [], baseURI: 'https://example.invalid/' },
    location: { hash },
    history: { replaceState: () => {} },
    URL,
    URLSearchParams,
    console: { warn() {}, log() {} },
    fetch: async (url) => {
      asked.push(url);
      return { ok: true, status: 200, json: async () => ({ available: false, reason: 'x' }) };
    },
    // gaps.js takes these from app.js at run time, which is not loaded
    // here. Stubbed rather than loading the whole page, because the
    // claim under test is which URL is fetched and that happens before
    // anything is drawn.
    $: () => null,
    $$: () => [],
    el: () => ({}),
    replace: () => {},
  };
  sandbox.window.location = sandbox.location;
  sandbox.window.history = sandbox.history;
  sandbox.window.fetch = sandbox.fetch;
  vm.createContext(sandbox);
  new vm.Script(SOURCE).runInContext(sandbox);
  /*
   * The drawing after the fetch reaches for more of app.js's globals
   * than it is worth stubbing, and it is not what is being claimed here.
   * The URL is recorded when `fetch` is called, which is before any of
   * that, so a failure past this point does not affect the answer.
   *
   * Swallowing it is safe only because `asked` is checked: if the fetch
   * never happened the array is empty and the case fails, which is how
   * this found that `new URL(path, document.baseURI)` was throwing
   * before any request went out.
   */
  try {
    await sandbox.window.SonoranGaps.show({});
  } catch {
    // drawing, not fetching
  }
  return asked[0] || null;
}

const named = await requestedUrl('#gaps?channel=MediumFast');
eq('show() asks for the preset the address names',
  named !== null && named.includes('channel=MediumFast'), true);

const bare = await requestedUrl('#gaps');
eq('a bare visit asks for no channel, leaving the default to the server',
  bare !== null && !bare.includes('channel='), true);

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
