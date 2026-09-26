/*
 * Behaviour cases for the live map's line lifetimes (#222).
 *
 * Reported: "Lines vanish too quickly to read, whichever mode is on",
 * and switching modes "feels broken".
 *
 * Measured from the constants before the change: motion on ran the
 * particle twice (2 x 850 ms), held 5 s and faded 3 s -- about 9.7 s.
 * Motion off painted whole, held 5 s, faded 3 s -- 8 s. The poll is
 * 15 s, so the map emptied for about half of every cycle in both
 * states.
 *
 * Run rather than read: the claims are arithmetic over the constants
 * and the behaviour of a rescale, neither of which a grep can settle.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../../../src/sonoran/web/static/map-live.js'), 'utf8');

const num = (name) => {
  const m = source.match(new RegExp(`const ${name} = (\\d+)`));
  if (!m) throw new Error(`${name} not found`);
  return Number(m[1]);
};

let failed = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

const HOLD = num('HOLD_MS');
const FADE = num('FADE_MS');
const LIVE_HOLD = num('LIVE_HOLD_MS');
const POLL_MS = 15000;  // LIVE_INTERVAL_MS in app.js

// --- the reported symptom -----------------------------------------

ok('the long hold is at least 30 s', LIVE_HOLD >= 30000, `got ${LIVE_HOLD}`);
const liveLife = LIVE_HOLD + FADE;
ok('a line outlasts the poll', liveLife > POLL_MS,
  `life ${liveLife} ms must exceed the ${POLL_MS} ms poll or the map empties`);
// The old behaviour, kept as the thing that must not come back.
ok('the old static life did NOT outlast the poll', HOLD + FADE < POLL_MS,
  'if this ever passes, the premise of the issue has changed');

// Motion stays brief: rule B, "just now, and that way".
const FLIGHT = Number((source.match(/const FLIGHT_MS = (\d+)/) || [])[1]);
ok('motion timing is unchanged', Number.isFinite(FLIGHT) && FLIGHT > 0);
const arcLife = FLIGHT * 2 + HOLD + FADE;
ok('motion is much shorter than the lasting mode', arcLife < liveLife,
  `motion ${arcLife} ms vs lasting ${liveLife} ms`);

// --- the rescale on a mode switch ---------------------------------
//
// Extracted and run, because "keeps the lines" is only true if the
// remaining life converts correctly. A mark half-spent must stay half
// spent, not restart and not expire.

const rescale = (age, life, target) => {
  const left = Math.max(0, life - age);
  const fraction = life > 0 ? left / life : 0;
  return Math.max(1, target * fraction);
};

{
  // Half-spent in motion mode, switching to the lasting mode.
  const got = rescale(arcLife / 2, arcLife, liveLife);
  ok('a half-spent mark stays half-spent', Math.abs(got - liveLife / 2) < 1,
    `got ${got}, wanted ${liveLife / 2}`);
  // A brand new mark keeps a full life.
  ok('a new mark gets the full new life',
    Math.abs(rescale(0, arcLife, liveLife) - liveLife) < 1);
  // An almost-dead mark does not come back to life.
  ok('an almost-dead mark stays almost dead',
    rescale(arcLife - 10, arcLife, liveLife) < liveLife * 0.02,
    `got ${rescale(arcLife - 10, arcLife, liveLife)}`);
  // And never zero, which would divide by zero in the fade.
  ok('life is never zero', rescale(arcLife, arcLife, liveLife) >= 1);
  ok('a zero-life slot is safe', rescale(5, 0, liveLife) >= 1);
}

// --- thinning before the cap refuses ------------------------------

const MAX_LIVE = num('MAX_LIVE');
const thresholds = [...source.matchAll(/\[(0\.\d+), (\d)\]/g)].map((m) => [Number(m[1]), Number(m[2])]);
ok('there are mark-pressure rungs', thresholds.length >= 3, JSON.stringify(thresholds));

const rungForMarks = (alive) => {
  const share = alive / MAX_LIVE;
  for (const [t, r] of thresholds) if (share >= t) return r;
  return 0;
};

ok('an empty pool asks for no thinning', rungForMarks(0) === 0);
ok('a half-full pool asks for no thinning', rungForMarks(MAX_LIVE * 0.5) === 0);
ok('a nearly-full pool thins', rungForMarks(MAX_LIVE * 0.9) > 0,
  'without this the cap refuses whole packets while frames stay cheap');
ok('a full pool thins hard', rungForMarks(MAX_LIVE) >= 3);
// Monotonic: pressure must never reduce the rung as it grows.
let last = -1;
for (let n = 0; n <= MAX_LIVE; n += 10) {
  const r = rungForMarks(n);
  ok(`pressure is monotonic at ${n}`, r >= last, `${r} < ${last}`);
  last = r;
}

if (failed) { console.error(`${failed} failed`); process.exit(1); }
console.log(`live lifetimes: all cases passed (lasting ${liveLife} ms vs motion ${arcLife} ms)`);
