/*
 * Which tapbacks are delivery receipts, and where.
 *
 * Will reported the bug: Trivia's numerals were drawn as "Possibly
 * auto-acked" when they are people answering the quiz. Measured on the
 * live instance while fixing it -- of 40 recent Trivia messages, 7 carried
 * a numeral tapback and every one was an answer.
 *
 * The emoji below are verbatim from `/api/chat`, including the
 * variation-selector-16 and keycap codepoints the real payload carries,
 * because a rule that works on a bare "2" and not on "2️⃣" would pass a
 * hand-written test and fail on the mesh.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const sandbox = { window: {}, console: { warn() {} } };
vm.createContext(sandbox);
new vm.Script(readFileSync(
  new URL('../../../src/sonoran/web/static/labels.js', import.meta.url), 'utf8',
)).runInContext(sandbox);
const L = sandbox.window.SonoranLabels;

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}`); }
};

// --- the reported bug ------------------------------------------------
eq('Trivia 2️⃣ is a person answering', L.isAutoAck('2️⃣', 'Trivia'), false);
eq('Trivia 3️⃣ is a person answering', L.isAutoAck('3️⃣', 'Trivia'), false);
eq('MediumFast 2️⃣ is an ack', L.isAutoAck('2️⃣', 'MediumFast'), true);

// --- the three channels, and only those -----------------------------
for (const channel of ['MediumFast', 'LongFast', 'azmsh']) {
  eq(`${channel} 4️⃣ is an ack`, L.isAutoAck('4️⃣', channel), true);
}
for (const channel of ['Trivia', 'Weather', 'Traffic', 'Public', 'PKI', '', null]) {
  eq(`${channel || '(none)'} 4️⃣ is not an ack`, L.isAutoAck('4️⃣', channel), false);
}

// --- the marks, exactly as decided ----------------------------------
for (const mark of ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '*️⃣']) {
  eq(`${mark} counts`, L.isAutoAck(mark, 'MediumFast'), true);
}
// A bare digit: some clients drop the keycap.
eq('a bare 3 counts', L.isAutoAck('3', 'MediumFast'), true);
eq('a bare * counts', L.isAutoAck('*', 'MediumFast'), true);

// The three Will chose to leave out. These are assertions about a
// DECISION, not about the protocol: the automation engine really does send
// `#` for MQTT, and these reading as reactions is the accepted cost.
// See docs/design/2026-09-26-ux-overhaul.md §2.1 before changing them.
eq('#️⃣ (via MQTT) is no longer an ack', L.isAutoAck('#️⃣', 'MediumFast'), false);
eq('0️⃣ (older direct) is no longer an ack', L.isAutoAck('0️⃣', 'MediumFast'), false);
eq('🎯 (older direct) is no longer an ack', L.isAutoAck('🎯', 'MediumFast'), false);

// --- things that are plainly reactions ------------------------------
// 🐦‍⬛ appeared beside 2️⃣ and 7️⃣ on one real MediumFast message, which is
// the case that proves acks and reactions must be split per-emoji rather
// than per-message.
eq('🐦‍⬛ is a reaction even on MediumFast', L.isAutoAck('🐦‍⬛', 'MediumFast'), false);
eq('👍 is a reaction', L.isAutoAck('👍', 'MediumFast'), false);
eq('8️⃣ is not a hop count', L.isAutoAck('8️⃣', 'MediumFast'), false);
eq('an empty emoji is not an ack', L.isAutoAck('', 'MediumFast'), false);
eq('two marks together are not one ack', L.isAutoAck('2️⃣3️⃣', 'MediumFast'), false);

// --- what the mark means --------------------------------------------
eq('* reads as direct', L.autoAckMeaning('*️⃣'), 'direct');
eq('1 reads as one hop', L.autoAckMeaning('1️⃣'), '1 hop');
eq('4 reads as hops', L.autoAckMeaning('4️⃣'), '4 hops');
eq('7 reads as seven or more', L.autoAckMeaning('7️⃣'), '7 or more hops');

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
