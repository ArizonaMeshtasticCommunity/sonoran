/*
 * Behaviour cases for the long-facet slice (§6.2).
 *
 * Will asked for the hardware filter to be a top ten plus a search box
 * plus "show more", and the numbers support it: production reports 57
 * hardware models and 17 of them hold two nodes or fewer.
 *
 * The rules here are all ways to mislead a reader about what is in force,
 * so they are run rather than read:
 *
 *  - a chosen value is drawn even when it is outside the slice or does
 *    not match what is typed. Dropping it leaves the fieldset showing
 *    "Any" as chosen while the filter is applied, and no way to undo it.
 *  - "nothing matched" and "nothing left to show" are different answers
 *    and need different words.
 *  - the search matches the words on the button as well as the value on
 *    the wire: a role reads "Client" and travels as `CLIENT`.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../../../src/sonoran/web/static/app.js'), 'utf8');

function extract(name) {
  const start = source.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found`);
  const end = source.indexOf('\n}', start);
  return source.slice(start, end + 2);
}

const facetSlice = new Function(`${extract('facetSlice')}; return facetSlice;`)();

let failed = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};

// 57 models, named so the tail is findable by name, with counts falling
// away the way a real facet's do.
const models = Array.from({ length: 57 }, (_, index) => ({
  value: `MODEL_${index}`,
  words: `MODEL_${index}`,
  count: 57 - index,
}));

// --- the top slice ---------------------------------------------------
const closed = facetSlice(models, { top: 10 });
ok('ten of fifty-seven are shown', closed.shown.length === 10, `${closed.shown.length} shown`);
ok('the order the server sent is kept', closed.shown[0].value === 'MODEL_0');
ok('the rest are counted for the button', closed.more === 47, `more ${closed.more}`);
ok('how many matched is reported', closed.matched === 57);

const opened = facetSlice(models, { top: 0 });
ok('opened, all of them are shown', opened.shown.length === 57);
ok('opened, nothing is withheld', opened.more === 0);

const short = facetSlice(models.slice(0, 4), { top: 10 });
ok('a short facet is not sliced', short.shown.length === 4);
ok('a short facet withholds nothing, so no button', short.more === 0);

// --- the search box --------------------------------------------------
const typed = facetSlice(models, { top: 10, query: 'MODEL_5' });
ok('a search narrows to what matches',
  typed.shown.every((entry) => entry.value.startsWith('MODEL_5')),
  typed.shown.map((entry) => entry.value).join(','));
ok('MODEL_5 and MODEL_50..56 is eight', typed.matched === 8, `matched ${typed.matched}`);
ok('eight under a top of ten hides nothing', typed.more === 0);

ok('the search is case-insensitive',
  facetSlice(models, { top: 10, query: 'model_33' }).matched === 1);
ok('the search matches part of a name',
  facetSlice(models, { top: 10, query: '_4' }).matched === 11,
  `${facetSlice(models, { top: 10, query: '_4' }).matched}`);
ok('surrounding space is ignored',
  facetSlice(models, { top: 10, query: '  MODEL_33  ' }).matched === 1);

const nothing = facetSlice(models, { top: 10, query: 'zzzz' });
ok('a search that matches nothing shows nothing', nothing.shown.length === 0);
// AND says so differently from "nothing left to show": `more` is 0 in
// both, so the caller has to read `matched` to tell them apart.
ok('a search that matches nothing reports it as matching nothing',
  nothing.matched === 0, `matched ${nothing.matched}`);

// The words on the button, not only the value on the wire.
const roles = [
  { value: 'CLIENT_BASE', words: 'Client, base station', count: 7 },
  { value: 'ROUTER', words: 'Router', count: 4 },
];
ok('the search matches what the reader can see',
  facetSlice(roles, { top: 1, query: 'base station' }).matched === 1);
ok('the search still matches the wire value',
  facetSlice(roles, { top: 1, query: 'CLIENT_BASE' }).matched === 1);

// --- THE ONE THAT MISLEADS: the chosen value ------------------------
const chosenDeep = facetSlice(models, { top: 10, chosen: 'MODEL_40' });
ok('a chosen value outside the top slice is still drawn',
  chosenDeep.shown.some((entry) => entry.value === 'MODEL_40'),
  'the panel would show "Any" as chosen while the filter was in force');
ok('and it is not counted as withheld', chosenDeep.more === 46, `more ${chosenDeep.more}`);
ok('and it is drawn once', chosenDeep.shown.filter((e) => e.value === 'MODEL_40').length === 1);

const chosenHidden = facetSlice(models, { top: 10, query: 'MODEL_1', chosen: 'MODEL_40' });
ok('a chosen value that does not match the search is not smuggled back in',
  !chosenHidden.shown.some((entry) => entry.value === 'MODEL_40'),
  'a search is a search; the chip above the table is how it comes off');

const chosenTop = facetSlice(models, { top: 10, chosen: 'MODEL_2' });
ok('a chosen value already in the slice is not duplicated',
  chosenTop.shown.filter((entry) => entry.value === 'MODEL_2').length === 1);
ok('and the withheld count is unchanged by it', chosenTop.more === 47);

// A number chosen and compared with a string value: the facets come back
// as JSON and a channel or a precision can be either.
ok('a chosen value of a different type still matches',
  facetSlice([{ value: 13, words: '13', count: 2 }, ...models], { top: 1, chosen: 13 })
    .shown.some((entry) => String(entry.value) === '13'));

// --- rubbish in ------------------------------------------------------
ok('no values at all does not throw', facetSlice(null, { top: 10 }).shown.length === 0);
ok('no options at all does not throw', facetSlice(models).shown.length === 57);
ok('an empty query is not a filter', facetSlice(models, { top: 10, query: '' }).matched === 57);
ok('a whitespace query is not a filter',
  facetSlice(models, { top: 10, query: '   ' }).matched === 57);
// `chosen` of null means nothing is chosen, which must not match the
// value `null` or a value that stringifies to "null".
ok('nothing chosen keeps nothing extra',
  facetSlice(models, { top: 10, chosen: null }).shown.length === 10);

if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('nodes facet slice: all cases pass');
