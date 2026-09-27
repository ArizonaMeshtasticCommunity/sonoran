/*
 * The frequency slot, exercised rather than read (§6.5).
 *
 * A slot is `lora.channel_num` on the radio and it counts from 1. The
 * firmware puts a node in the middle of a slot one bandwidth wide:
 *
 *     centre = 902 MHz + bandwidth / 2 + (slot - 1) * bandwidth
 *
 * Off by one here moves every prediction a whole slot -- 250 kHz on Medium
 * fast -- and nothing on the page would show it, because both numbers look
 * perfectly reasonable. So the cases below are anchored on a frequency
 * that is known from outside this repository: LongFast in the US is slot
 * 20 and 906.875 MHz. `sonoran/radio/channels.py` reaches the same
 * frequency from a zero-based index of 19, and `test_rf_channels.py`
 * already pins that, so the pair of tests catch a change on either side.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const SRC = readFileSync(
  new URL('../../../src/sonoran/web/static/planner-params.js', import.meta.url),
  'utf8',
);

function load() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  new vm.Script(SRC).runInContext(sandbox);
  return sandbox.window.SonoranPlannerParams;
}

const P = load();

let failed = 0;
const eq = (name, got, want) => {
  if (JSON.stringify(got) === JSON.stringify(want)) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${JSON.stringify(got)}\n       want ${JSON.stringify(want)}`); }
};

// --- the anchor -----------------------------------------------------
eq('LongFast slot 20 is 906.875 MHz, which is the published US default',
  P.frequencyForSlot('LONG_FAST', 20), 906.875);
eq('and 906.875 MHz reads back as slot 20',
  P.slotForFrequency('LONG_FAST', 906.875), 20);
/*
 * The off-by-one this is here to catch. A zero-based reading of slot 20
 * gives 907.125 MHz, which is a real frequency and a wrong answer.
 */
eq('a zero-based reading would give 907.125, and does not',
  P.frequencyForSlot('LONG_FAST', 21), 907.125);

// --- what this mesh runs --------------------------------------------
eq('slot 18 on Medium fast is 906.375 MHz (azmsh metro)',
  P.frequencyForSlot('MEDIUM_FAST', 18), 906.375);
eq('the planner opens on that frequency', P.DEFAULTS.frequency_mhz, 906.375);
eq('and on that slot', P.slotForFrequency(P.DEFAULTS.preset, P.DEFAULTS.frequency_mhz), 18);
eq('the default slot and preset names agree with DEFAULTS',
  [P.DEFAULT_SLOT, P.DEFAULT_PRESET_KEY], [18, P.DEFAULTS.preset]);
eq('the sensitivity in DEFAULTS is the one the default preset implies',
  P.DEFAULTS.sensitivity, P.sensitivityForPreset(P.DEFAULTS.preset));

// --- how many slots a bandwidth gives -------------------------------
eq('250 kHz divides the band into 104 slots', P.slotsForPreset('MEDIUM_FAST'), 104);
eq('125 kHz gives 208', P.slotsForPreset('LONG_MODERATE'), 208);
eq('500 kHz gives 52', P.slotsForPreset('SHORT_TURBO'), 52);
eq('62.5 kHz gives 416', P.slotsForPreset('VERY_LONG_SLOW'), 416);
eq('an unknown preset has no slots', P.slotsForPreset('NOT_A_PRESET'), 0);

// --- the ends of the band -------------------------------------------
eq('slot 1 sits half a bandwidth above 902 MHz',
  P.frequencyForSlot('MEDIUM_FAST', 1), 902.125);
eq('the last slot is inside the band',
  P.frequencyForSlot('MEDIUM_FAST', 104) < 928, true);
eq('one past the last slot does not exist',
  P.frequencyForSlot('MEDIUM_FAST', 105), null);

/*
 * --- ABSENT is not ZERO ---------------------------------------------
 *
 * `Number(null)`, `Number('')` and `Number(undefined ?? '')` are 0 or NaN,
 * and slot 0 does not exist. Without these guards an empty slot menu --
 * which is exactly what "not on a slot" leaves behind -- would compute
 * 901.875 MHz, below the band, and look like an ordinary typo. Five bugs
 * in this repository have been this shape (#149, #157, #190, #197).
 */
for (const empty of [null, undefined, '', ' ', 'x', NaN, 0, -1, 1.5]) {
  eq(`slot ${JSON.stringify(empty)} is not a slot`,
    P.frequencyForSlot('MEDIUM_FAST', empty), null);
}
for (const empty of [null, undefined, '']) {
  eq(`frequency ${JSON.stringify(empty)} is not a frequency`,
    P.slotForFrequency('MEDIUM_FAST', empty), null);
}

// --- a frequency between two slots ----------------------------------
/*
 * Not snapped, and not an error. `lora.override_frequency` is a real
 * setting and a licensed operator may sit anywhere; the form says so
 * instead of moving the number somebody typed.
 */
eq('a frequency between two slots is on no slot',
  P.slotForFrequency('MEDIUM_FAST', 906.5), null);
eq('one kilohertz off a centre is still off it',
  P.slotForFrequency('MEDIUM_FAST', 906.376), null);
eq('a frequency below the band is on no slot',
  P.slotForFrequency('MEDIUM_FAST', 400), null);
eq('a frequency above the band is on no slot',
  P.slotForFrequency('MEDIUM_FAST', 2400), null);
/*
 * The same frequency is a different slot on a different bandwidth, and on
 * some it is no slot at all. This is why the preset has to be part of the
 * question, and why changing the preset has to rebuild the menu.
 */
eq('906.375 MHz is not a slot centre at 125 kHz',
  P.slotForFrequency('LONG_MODERATE', 906.375), null);
eq('slot 18 at 125 kHz is 904.1875 MHz instead',
  P.frequencyForSlot('LONG_MODERATE', 18), 904.1875);
/*
 * Five decimals, not three. Half of 62.5 kHz is 31.25 kHz, so the narrow
 * presets sit on quarter-kilohertz boundaries: three decimals turned
 * Long moderate's own channel from 912.8125 into 912.812, which was inside
 * the tolerance below and so passed every round trip. It was the
 * comparison against `sonoran/radio/channels.py`, which works in integer
 * hertz, that found it.
 */
eq('the narrowest preset keeps its quarter kilohertz',
  P.frequencyForSlot('VERY_LONG_SLOW', 1), 902.03125);
eq('and reads back as slot 1',
  P.slotForFrequency('VERY_LONG_SLOW', 902.03125), 1);
eq('a reader who types the rounded form still lands on the slot',
  P.slotForFrequency('VERY_LONG_SLOW', 902.031), 1);

// --- every slot of every preset round-trips -------------------------
{
  const broken = [];
  for (const preset of P.PRESETS) {
    for (let slot = 1; slot <= P.slotsForPreset(preset.key); slot += 1) {
      const centre = P.frequencyForSlot(preset.key, slot);
      if (P.slotForFrequency(preset.key, centre) !== slot) broken.push([preset.key, slot, centre]);
    }
  }
  // 780 slots across the nine presets. A tolerance expressed in slots
  // rather than in hertz failed here, which is why the comparison in
  // `slotForFrequency` is made on the frequency.
  eq('every slot of every preset reads back as itself', broken, []);
}

// --- the slot never travels in a share link -------------------------
/*
 * Two numbers that say the same thing can disagree, and a link is read by
 * somebody who cannot check. The frequency goes; the slot is worked out
 * from it. §6.5 names this as the risk in a three-way binding.
 */
eq('slot is not a share field', P.SHARE_FIELDS.includes('slot'), false);
eq('nor under another name', P.SHARE_FIELDS.filter((f) => f.includes('slot')), []);
eq('the frequency is', P.SHARE_FIELDS.includes('frequency_mhz'), true);

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
