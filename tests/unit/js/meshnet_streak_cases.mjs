/*
 * How a streak becomes a sentence.
 *
 * The arithmetic is server-side (`docs/design/2026-09-26-ux-overhaul.md`
 * §6.3, and `tests/unit/test_meshnet_streaks.py` enumerates its
 * boundaries). What is exercised here is the other half, and it is the
 * half that has bitten this repository five times: a value that is
 * MISSING, rendered as a value that is ZERO.
 *
 * `Number(null)` is 0. `null >= 0` is true. `null || 0` is 0. Any of
 * those three, next to a person's name on this page, states that they
 * checked in no weeks running when the truth is that nobody counted.
 *
 * The other rule under test is that an unfinished week is never
 * described as a broken anything.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const sandbox = { window: {} };
vm.createContext(sandbox);
new vm.Script(readFileSync(
  new URL('../../../src/sonoran/web/static/meshnet.js', import.meta.url), 'utf8',
)).runInContext(sandbox);
const M = sandbox.window.SonoranMeshnet;

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) console.log(`  PASS ${name}`);
  else {
    failed += 1;
    console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`);
  }
};
const has = (name, got, want) => {
  if (String(got).includes(want)) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       ${JSON.stringify(got)} lacks ${JSON.stringify(want)}`); }
};
const lacks = (name, got, want) => {
  if (!String(got).includes(want)) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       ${JSON.stringify(got)} contains ${JSON.stringify(want)}`); }
};

// --- `counted`: the guard the rest of the file stands on --------------
console.log('a missing count is never a number');
eq('null is not counted', M.counted(null), null);
eq('undefined is not counted', M.counted(undefined), null);
eq('an empty string is not counted', M.counted(''), null);
// '' and null are exactly the values `Number()` turns into 0.
eq('a string of digits is not counted', M.counted('3'), null);
eq('NaN is not counted', M.counted(Number.NaN), null);
eq('a fraction is not counted', M.counted(1.5), null);
eq('zero IS counted', M.counted(0), 0);
eq('a whole number is counted', M.counted(7), 7);

// --- a streak beside a name -------------------------------------------
console.log('\na streak beside a name');
eq('five weeks', M.streakWord({ streak_weeks: 5, first_ever: false }), '5 weeks in a row');
eq('a lower bound wears a plus',
  M.streakWord({ streak_weeks: 52, streak_at_least: true }), '52+ weeks in a row');
eq('a first check-in says so', M.streakWord({ streak_weeks: 1, first_ever: true }), 'First check-in');
eq('a run of one after a gap says that instead',
  M.streakWord({ streak_weeks: 1, first_ever: false }), 'Back after a gap');
// A run of 1 that reaches the floor is NOT a first check-in: the read
// simply stops there, and the page must not invent a beginning.
eq('a run of one at the floor is not called a beginning',
  M.streakWord({ streak_weeks: 1, streak_at_least: true, first_ever: true }), '1+ weeks in a row');

console.log('\nand a streak that was never measured');
for (const entry of [{}, { streak_weeks: null }, { streak_weeks: undefined }, { streak_weeks: '4' }]) {
  eq(`${JSON.stringify(entry)} is not known`, M.streakWord(entry), 'Streak not known');
}
eq('no entry at all is not known', M.streakWord(null), 'Streak not known');
eq('no entry at all is not known (undefined)', M.streakWord(undefined), 'Streak not known');
// The bug in one line: 0 must not become "0 weeks in a row", and it must
// not become "First check-in" either. A check-in with a run of zero is a
// contradiction and the page says it does not know.
eq('zero next to a check-in is a contradiction, not a count',
  M.streakWord({ streak_weeks: 0, first_ever: true }), 'Streak not known');
lacks('and never prints a zero', M.streakWord({ streak_weeks: 0 }), '0');
lacks('a missing streak never prints a zero', M.streakWord({}), '0');

console.log('\nthe detail line');
has('a measured run says how long', M.streakDetail({ streak_weeks: 3 }), '3 weeks');
has('a bounded run says the read is the limit',
  M.streakDetail({ streak_weeks: 52, streak_at_least: true }, '2025-08-04'), 'may be longer');
has('a bounded run names where the read starts',
  M.streakDetail({ streak_weeks: 52, streak_at_least: true }, '2025-08-04'), '2025-08-04');
has('a missing run blames the server, not the node', M.streakDetail({}), 'did not send');
lacks('and still prints no zero', M.streakDetail({}), '0');
eq('one week reads as one week, not "1 weeks"',
  M.streakDetail({ streak_weeks: 1 }),
  'Checked in every week for 1 week up to and including this one.');

// --- an absence -------------------------------------------------------
console.log('\nan absence on the week in progress');
{
  const said = M.absenceWord({ streak_weeks: 4 }, true);
  eq('is pending, not broken', said.tone, 'pending');
  has('and says the week is not over', said.detail, 'not over');
  has('the run is described as open', said.detail, 'still open');
  lacks('nothing about it "ends"', `${said.text} ${said.detail}`, 'end');
  lacks('and nobody "missed" anything', `${said.text} ${said.detail}`, 'iss');
  has('the words are about the message, not the person', said.text, 'No message yet');
}

console.log('\nan absence on a week that has finished');
{
  const said = M.absenceWord({ streak_weeks: 4 }, false);
  eq('is a broken run', said.tone, 'broken');
  has('named as an observation', said.text, 'No message found');
  lacks('never as a verdict', `${said.text} ${said.detail}`, 'iss');
  has('and it says what else could explain it', said.detail, 'may not have been stored');
  has('the run that ends is named', said.detail, 'A run of 4 weeks ends here');
}

/*
 * "A run of 1 weeks ends here" is what shipped to the live page in the
 * first draft. A page that cannot count to one will not be believed
 * about counting to thirty.
 */
console.log('\nand it can count to one');
has('a run of one week', M.absenceWord({ streak_weeks: 1 }, false).detail, 'A run of 1 week ends');
lacks('not "1 weeks"', M.absenceWord({ streak_weeks: 1 }, false).detail, '1 weeks');
has('a bounded run of one is still plural, because it may be more',
  M.absenceWord({ streak_weeks: 1, streak_at_least: true }, false).detail, 'A run of 1+ weeks');
has('and the open case too', M.absenceWord({ streak_weeks: 1 }, true).detail,
  'A run of 1 week is still open');

console.log('\nan absence with no run on it');
for (const inProgress of [true, false]) {
  const said = M.absenceWord({}, inProgress);
  lacks(`no zero run (${inProgress ? 'in progress' : 'finished'})`, said.detail, '0');
  lacks(`no empty run (${inProgress ? 'in progress' : 'finished'})`, said.detail, 'run of ');
}
eq('a lower-bound run keeps its plus', M.absenceWord({ streak_weeks: 9, streak_at_least: true }, false).detail,
  'A run of 9+ weeks ends here. The node may have been off, out of range, or its message may not '
  + 'have been stored.');

// --- a week's heading -------------------------------------------------
console.log('\na week heading');
eq('a normal week', M.weekWord({ check_in_count: 4, message_count: 5 }),
  '4 nodes checked in, 5 messages');
eq('one of each', M.weekWord({ check_in_count: 1, message_count: 1 }),
  '1 node checked in, 1 message');
eq('the week in progress hedges', M.weekWord({ check_in_count: 4, message_count: 5, in_progress: true }),
  '4 nodes checked in so far, 5 messages');
// Measured, and the answer is nothing. This week EXISTS and is empty,
// which is the gap the page is for.
eq('a week with nobody in it', M.weekWord({ check_in_count: 0, message_count: 0 }),
  'No check-in found');
eq('an empty week in progress', M.weekWord({ check_in_count: 0, message_count: 0, in_progress: true }),
  'No check-in found so far');
// Not counted at all: a different sentence, and it must not read as 0.
eq('a week with no count', M.weekWord({}), 'Check-ins not counted for this week');
eq('a week with a null count', M.weekWord({ check_in_count: null }),
  'Check-ins not counted for this week');
lacks('and it prints no zero', M.weekWord({ check_in_count: null }), '0');
eq('nodes counted, messages not', M.weekWord({ check_in_count: 2 }), '2 nodes checked in');

// --- nothing to compute from ------------------------------------------
console.log('\nnothing to compute from');
eq('an assessed page has no notice',
  M.noAssessmentWord({ streaks: { lookback_weeks: 60 }, text_storage: true }), null);
has('storage off says so',
  M.noAssessmentWord({ streaks: null, text_storage: false }), 'not being stored');
has('storage off says it is not a count of check-ins',
  M.noAssessmentWord({ streaks: null, text_storage: false }), 'not a count of');
has('an unexplained blank admits it', M.noAssessmentWord({ streaks: null, text_storage: true }),
  'not reported');
has('no data at all admits it', M.noAssessmentWord(null), 'could not be read');
// Storage off WITH data found is not a blank page: the rows exist and
// the streaks are real, so the notice must not appear.
eq('storage off but rows found is still assessed',
  M.noAssessmentWord({ streaks: { lookback_weeks: 60 }, text_storage: false }), null);

// --- a truncated message list -----------------------------------------
console.log('\na truncated message list');
eq('shorter than the count', M.messagesTruncated({ messages_shown: 50, message_count: 120 }), true);
eq('the whole week', M.messagesTruncated({ messages_shown: 5, message_count: 5 }), false);
// Neither number known: claiming truncation would invent a limit.
eq('nothing known', M.messagesTruncated({}), false);
eq('only one known', M.messagesTruncated({ message_count: 9 }), false);

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
