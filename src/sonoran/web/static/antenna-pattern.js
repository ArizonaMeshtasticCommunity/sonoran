/*
 * Where a directional antenna actually points (#111, Yagi support).
 *
 * The engine takes ONE effective radiated power and radiates it equally
 * in every direction. It has no azimuth input and no pattern file, so a
 * Yagi cannot be handed to it directly -- doing that would draw a map
 * claiming the antenna was aimed at every point on it at once.
 *
 * What makes this tractable is the scale the engine reports on. Its
 * signal raster is a byte per cell holding dBm + 200: a LINEAR decibel
 * scale, one dB per unit. In the ITM model the path loss between two
 * points does not depend on how much power you put in, so the received
 * level is (radiated power) + (antenna gain in that direction) - (path
 * loss). Subtracting a per-direction figure from the finished raster is
 * therefore not an approximation of the right answer -- it IS the right
 * answer, provided the run used the antenna's boresight gain, which is
 * what the picker fills in.
 *
 * The shape
 * ---------
 * `patternLossDb` is the parabolic main-lobe approximation used across
 * radio planning (the same one 3GPP specifies for sector antennas):
 *
 *     loss_dB = 12 * (off_axis / beamwidth)^2
 *
 * It is chosen because it is pinned to the one number the listings do
 * give. At half a beamwidth off boresight it returns exactly 3 dB, and
 * "beamwidth" is defined as the angle between the half-power points --
 * so the curve agrees with the specification by construction rather
 * than by fitting.
 *
 * What it does NOT model, and says so
 * -----------------------------------
 * Side lobes and the back lobe. A real Yagi has both, and no listing
 * read for this catalogue states a front-to-back ratio, which is why
 * `front_to_back_db` is None on every entry. Rather than invent one,
 * the modelled loss is CAPPED: past the cap this stops pretending to
 * predict. The cap is deliberately modest, because assuming deep
 * rejection would draw confident emptiness behind the antenna, and
 * behind the antenna is exactly where this model knows least.
 *
 * A consequence worth stating plainly: coverage shown behind a
 * directional antenna is the least trustworthy part of the map.
 */

/*
 * Exposed as a global rather than an ES export, because `planner.js` is
 * loaded with a plain <script> tag and there is no build step. This
 * follows `planner-params.js`, which does the same for the same reason.
 */
window.SonoranAntennaPattern = (function build() {
/**
 * The most attenuation this model will claim, in dB.
 *
 * Not a specification. Small Yagis in this band typically manage 10-20
 * dB front-to-back, and none of the product pages say. Capping here
 * keeps the map from asserting a null it cannot support.
 */
const MAX_MODELLED_REJECTION_DB = 15;

/** Degrees in a circle, named so the modular arithmetic below reads. */
const FULL_CIRCLE = 360;
const HALF_CIRCLE = 180;

/**
 * Initial great-circle bearing from one point to another, in degrees
 * true, 0 = north and increasing clockwise.
 *
 * Spherical rather than planar on purpose. A planar approximation is
 * fine over a few kilometres but the planner runs to 150 km, and the
 * error grows with latitude -- at Arizona's latitude a flat-earth
 * bearing is off by enough at the edge of a long run to move the
 * main lobe by a visible amount.
 */
function bearingDeg(fromLat, fromLon, toLat, toLon) {
  const rad = Math.PI / HALF_CIRCLE;
  const phi1 = fromLat * rad;
  const phi2 = toLat * rad;
  const dLambda = (toLon - fromLon) * rad;
  const y = Math.sin(dLambda) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLambda);
  const deg = Math.atan2(y, x) / rad;
  return (deg + FULL_CIRCLE) % FULL_CIRCLE;
}

/**
 * The angle between a bearing and where the antenna is aimed, 0 to 180.
 *
 * Both directions off boresight are the same to a symmetrical antenna,
 * so this never exceeds a half turn. Getting this wrong by taking a
 * signed difference would put the main lobe on one side only, which is
 * the sort of error that looks plausible on a map.
 */
function offAxisDeg(bearing, boresight) {
  const delta = Math.abs(((bearing - boresight) % FULL_CIRCLE) + FULL_CIRCLE) % FULL_CIRCLE;
  return delta > HALF_CIRCLE ? FULL_CIRCLE - delta : delta;
}

/**
 * How much gain is lost this far off boresight, in dB (never negative).
 *
 * Returns 0 for a beamwidth that is missing or not a positive number:
 * an unknown pattern must not quietly become a modelled one. Callers
 * decide whether to proceed -- the planner refuses to aim at all in
 * that case and says why.
 */
function patternLossDb(offAxis, beamwidthDeg) {
  if (!Number.isFinite(beamwidthDeg) || beamwidthDeg <= 0) return 0;
  if (!Number.isFinite(offAxis)) return 0;
  const ratio = Math.abs(offAxis) / beamwidthDeg;
  return Math.min(12 * ratio * ratio, MAX_MODELLED_REJECTION_DB);
}

/**
 * The loss for a point, given where the antenna is and where it aims.
 *
 * A convenience over the three above so the raster loop and the link
 * budget cannot disagree about the order of the arguments.
 */
function lossTowardsDb(site, target, boresightDeg, beamwidthDeg) {
  const bearing = bearingDeg(site.lat, site.lon, target.lat, target.lon);
  return patternLossDb(offAxisDeg(bearing, boresightDeg), beamwidthDeg);
}

/**
 * The beamwidth to model with, or null when there is nothing to use.
 *
 * The catalogue states a horizontal beamwidth for the 12 dBi Yagi and
 * NOT for the 6 dBi one, whose listing gives no pattern at all. A
 * number typed by the person wins over the catalogue, because they may
 * be holding the datasheet the shop did not print.
 */
function chosenBeamwidth(antenna, typed) {
  const entered = Number(typed);
  if (Number.isFinite(entered) && entered > 0 && entered <= FULL_CIRCLE) return entered;
  const claimed = antenna && antenna.horizontal_beamwidth_deg;
  if (Number.isFinite(claimed) && claimed > 0) return claimed;
  return null;
}

  return {
    MAX_MODELLED_REJECTION_DB,
    bearingDeg,
    offAxisDeg,
    patternLossDb,
    lossTowardsDb,
    chosenBeamwidth,
  };
}());
