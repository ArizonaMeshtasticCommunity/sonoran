/*
 * Where a directional antenna points, and what that costs off boresight.
 *
 * The cases that matter most are the ones about NOT modelling: an
 * unknown beamwidth must leave the pattern alone rather than become a
 * plausible shape, because a plausible shape on a map is indistinguish-
 * able from a measured one.
 */
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const sandbox = { window: {} };
vm.createContext(sandbox);
new vm.Script(readFileSync(
  new URL('../../../src/sonoran/web/static/antenna-pattern.js', import.meta.url), 'utf8',
)).runInContext(sandbox);
const P = sandbox.window.SonoranAntennaPattern;

let failed = 0;
const eq = (name, got, want) => {
  const a = JSON.stringify(got); const b = JSON.stringify(want);
  if (a === b) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${a}\n       want ${b}`); }
};
const near = (name, got, want, tol = 1e-9) => {
  if (Math.abs(got - want) <= tol) console.log(`  PASS ${name}`);
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${got}\n       want ${want}`); }
};

eq('the module loads as a global', typeof P, 'object');

// --- the half-power point, which pins the whole curve ---------------
// This is the one case that makes the formula defensible rather than
// decorative: "beamwidth" is DEFINED as the angle between the points
// where the power has halved, and half of a beamwidth off boresight
// must therefore be exactly 3 dB down. Not 2.9, not "about 3".
near('half a beamwidth off boresight is exactly 3 dB', P.patternLossDb(18, 36), 3);
near('the same holds for a different width', P.patternLossDb(22.5, 45), 3);
near('boresight loses nothing', P.patternLossDb(0, 36), 0);
near('a quarter beamwidth is 0.75 dB', P.patternLossDb(9, 36), 0.75);

// --- the cap --------------------------------------------------------
eq('straight behind is capped, not extrapolated',
  P.patternLossDb(180, 36), P.MAX_MODELLED_REJECTION_DB);
eq('the cap is the documented 15 dB', P.MAX_MODELLED_REJECTION_DB, 15);
// Without the cap this would be 12*(180/36)^2 = 300 dB, which would
// assert a silence no antenna delivers.
eq('the uncapped value would have been absurd', 12 * (180 / 36) ** 2, 300);

// --- an unknown pattern stays unknown -------------------------------
eq('a null beamwidth is not modelled', P.patternLossDb(90, null), 0);
eq('an undefined beamwidth is not modelled', P.patternLossDb(90, undefined), 0);
eq('a zero beamwidth is not modelled', P.patternLossDb(90, 0), 0);
eq('a negative beamwidth is not modelled', P.patternLossDb(90, -36), 0);

// --- off-axis wrapping ----------------------------------------------
// A signed difference here would put the main lobe on one side only,
// which looks plausible on a map and is wrong by the whole pattern.
eq('10 either side of north are the same', P.offAxisDeg(350, 0), P.offAxisDeg(10, 0));
eq('wrapping across north', P.offAxisDeg(350, 10), 20);
eq('never more than half a turn', P.offAxisDeg(0, 180), 180);
eq('exactly opposite', P.offAxisDeg(90, 270), 180);
eq('aimed at itself', P.offAxisDeg(123, 123), 0);

// --- bearings -------------------------------------------------------
near('due north is 0', P.bearingDeg(33, -112, 34, -112), 0, 1e-6);
near('due south is 180', P.bearingDeg(34, -112, 33, -112), 180, 1e-6);
// Just under 90: a great circle heading east curves, and a flat-earth
// bearing would say exactly 90. The difference is the point of using
// the spherical formula over a 150 km run.
const east = P.bearingDeg(33, -112, 33, -111);
eq('due east is just under 90, not exactly', east < 90 && east > 89.5, true);

// --- the two together -----------------------------------------------
const site = { lat: 33.5, lon: -112.1 };
near('a target on boresight pays nothing',
  P.lossTowardsDb(site, { lat: 34.5, lon: -112.1 }, 0, 36), 0, 1e-6);
eq('a target behind pays the cap',
  P.lossTowardsDb(site, { lat: 32.5, lon: -112.1 }, 0, 36), P.MAX_MODELLED_REJECTION_DB);

// --- choosing a beamwidth -------------------------------------------
const stated = { horizontal_beamwidth_deg: 36 };
const unstated = { horizontal_beamwidth_deg: null };
eq('the catalogue figure is used when present', P.chosenBeamwidth(stated, ''), 36);
// A typed number wins: somebody may hold the datasheet the shop did not
// print, which is exactly the L-Com case.
eq('a typed figure overrides the catalogue', P.chosenBeamwidth(stated, '20'), 20);
eq('no figure anywhere is null', P.chosenBeamwidth(unstated, ''), null);
eq('a typed figure rescues an unstated one', P.chosenBeamwidth(unstated, '45'), 45);
eq('nonsense is refused, not clamped', P.chosenBeamwidth(unstated, '0'), null);
eq('over a full circle is refused', P.chosenBeamwidth(unstated, '400'), null);
eq('text is refused', P.chosenBeamwidth(unstated, 'wide'), null);

if (failed) { console.log(`\n${failed} case(s) failed`); process.exit(1); }
console.log('\nall cases passed');
