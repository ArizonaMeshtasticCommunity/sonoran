/*
 * Behaviour cases for the live feed's timing (#386).
 *
 * Reported by Will: "the box for Live traffic only updates in chunks and
 * leads to like 5 or 6 things happening". The poll fetches fifteen
 * seconds of traffic at once. The map spreads that batch over the next
 * fifteen seconds, so its lines start one at a time; the list took the
 * whole batch at fetch time.
 *
 * The feed now lists a packet when the engine releases it. These cases
 * run the real engine, `map-live.js`, against a stand-in map, canvas and
 * clock, and check the two things the feed reads from it:
 *
 *   - `onRelease` is told each packet in the frame its line starts, in
 *     the order the packets happened, and never before its time;
 *   - `pendingKeys()` holds exactly the packets still waiting, so the
 *     feed can leave them out.
 *
 * Run by `tests/unit/test_live_feed_pacing.py`, which shells out to node.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, '../../../src/sonoran/web/static/map-live.js'), 'utf8');

/* --- A stand-in browser ------------------------------------------- */

// A drawing context that accepts every call and every property.
const anything = new Proxy(function stub() {}, {
  get: (target, key) => (key === Symbol.toPrimitive ? () => 0 : anything),
  apply: () => anything,
  set: () => true,
});
const canvas = { style: {}, setAttribute() {}, getContext: () => anything, width: 0, height: 0 };
const document = { createElement: () => canvas };
const window = { devicePixelRatio: 1 };
let frames = [];
const requestAnimationFrame = (callback) => { frames.push(callback); return frames.length; };
const cancelAnimationFrame = () => { frames = []; };

// One clock for `Date.now` and `performance.now`, moved by hand.
let clock = 1_800_000_000_000;
const realNow = Date.now;
Date.now = () => clock;
const performance = { now: () => clock };

new Function('window', 'document', 'requestAnimationFrame', 'cancelAnimationFrame', 'performance', source)(
  window, document, requestAnimationFrame, cancelAnimationFrame, performance);
const { SonoranLive } = window;

const map = {
  createPane: () => ({ style: {}, appendChild() {} }),
  getContainer: () => ({}),
  getSize: () => ({ x: 800, y: 600 }),
  latLngToContainerPoint: ([lat, lng]) => ({ x: (lng + 115) * 100, y: (35 - lat) * 100 }),
  on() {},
};

/** Run every frame that is due, once. */
function frame() {
  const due = frames;
  frames = [];
  for (const callback of due) callback(clock);
}

let failed = 0;
const ok = (name, cond, detail) => {
  if (cond) return;
  failed += 1;
  console.error(`FAIL ${name}${detail ? `\n  ${detail}` : ''}`);
};
const keys = (set) => [...set].sort().join(' ');

/* --- Traffic ------------------------------------------------------- */

const SENDER = { node_id: '!0000000a', display_name: 'Sender', lat: 33.4, lon: -112.0 };
const GATEWAY = { node_id: '!0000000b', display_name: 'Gateway', lat: 33.6, lon: -111.8 };

/** One upload of one packet, `offset` ms after the first. */
function upload(id, offset, portnum = 'POSITION_APP') {
  return {
    time: new Date(clock - 20000 + offset).toISOString(),
    packet_id: id,
    portnum,
    channel: 'MediumFast',
    from: SENDER,
    gateway: GATEWAY,
    direct: false,
    hops_taken: 1,
    has_line: true,
    snr: null,
  };
}

/* --- Case 1: rows arrive with their lines, not with the poll -------- */
{
  const released = [];
  const live = SonoranLive.create(map, { onRelease: (packets) => released.push(packets.map((p) => p.packet_id)) });
  // Four packets three seconds apart, fetched in one poll.
  const packets = SonoranLive.aggregate([upload(1, 0), upload(2, 3000), upload(3, 6000), upload(4, 9000)]);
  live.push(packets, 15000);
  ok('every packet waits before the first frame', keys(live.pendingKeys()) === keys(new Set(packets.map((p) => p.key))),
    `pending: ${keys(live.pendingKeys())}`);

  frame();
  ok('the first frame releases the first packet alone', JSON.stringify(released) === '[[1]]',
    `released: ${JSON.stringify(released)}`);
  ok('the other three still wait', live.pendingKeys().size === 3, `pending: ${keys(live.pendingKeys())}`);

  clock += 2900;
  frame();
  ok('nothing is released before its time', released.length === 1, `released: ${JSON.stringify(released)}`);

  for (const want of [2, 3, 4]) {
    clock += 100;
    frame();
    const last = released[released.length - 1];
    ok(`packet ${want} is released on its own frame`, JSON.stringify(last) === `[${want}]`,
      `released: ${JSON.stringify(released)}`);
    clock += 2900;
    frame();
  }
  ok('the four were released one by one, in order', JSON.stringify(released) === '[[1],[2],[3],[4]]',
    `released: ${JSON.stringify(released)}`);
  ok('nothing waits at the end', live.pendingKeys().size === 0);
  live.clear();
}

/* --- Case 2: a packet the map will never draw does not wait --------- */
{
  frames = [];
  const live = SonoranLive.create(map, { onRelease: () => {} });
  const packets = SonoranLive.aggregate([
    upload(11, 0), upload(12, 5000, 'TELEMETRY_APP'), upload(13, 10000),
  ]);
  live.push(packets, 15000);
  live.setFamilyFilter(new Set(['TELEMETRY_APP']));
  ok('a hidden kind leaves the waiting list', ![...live.pendingKeys()].some((key) => key.endsWith('/12')),
    `pending: ${keys(live.pendingKeys())}`);
  ok('the shown kinds still wait', live.pendingKeys().size === 2, `pending: ${keys(live.pendingKeys())}`);
  live.skipToLive();
  ok('skipping to live leaves nothing waiting', live.pendingKeys().size === 0);
  live.clear();
}

/* --- Case 3: a paused map holds the feed with it -------------------- */
{
  frames = [];
  const released = [];
  const live = SonoranLive.create(map, { onRelease: (packets) => released.push(...packets) });
  live.push(SonoranLive.aggregate([upload(21, 0), upload(22, 4000)]), 15000);
  frame();
  live.setPaused(true);
  clock += 10000;
  frame();
  ok('a paused map releases nothing', released.length === 1, `released ${released.length}`);
  ok('a paused map keeps its packet waiting', live.pendingKeys().size === 1);
  live.setPaused(false);
  clock += 5000;
  frame();
  ok('resumed, the packet is released', released.length === 2, `released ${released.length}`);
  live.clear();
}

Date.now = realNow;
if (failed) {
  console.error(`${failed} case(s) failed`);
  process.exit(1);
}
console.log('live feed pacing: all cases passed');
