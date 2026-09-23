/*
 * Behaviour cases for `serial-frames.js` (#116).
 *
 * Run by `tests/unit/test_serial_frames.py`, which shells out to
 * node. There is no JavaScript test runner in this repo, and a
 * stream decoder is the wrong thing to check by reading its source:
 * every bug it can have is a bug about what happens across two
 * reads, which only shows up when you run it.
 *
 * Exits non-zero on the first failure count, so the Python side
 * only has to look at the status and print the output.
 */
import { FrameDecoder, frame, MAX_PAYLOAD } from '../../../src/sonoran/web/static/serial-frames.js';

const bytes = (...n) => Uint8Array.from(n);
const text = (s) => new TextEncoder().encode(s);
const join = (...parts) => {
  const total = parts.reduce((n, p) => n + p.length, 0);
  const out = new Uint8Array(total);
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
};
let failed = 0;
const eq = (name, got, want) => {
  const a = JSON.stringify(got), b = JSON.stringify(want);
  if (a === b) { console.log(`  PASS ${name}`); }
  else { failed += 1; console.log(`  FAIL ${name}\n       got  ${a}\n       want ${b}`); }
};
const payloads = (fs) => fs.map((f) => [...f]);

// 1. one whole frame in one read
{
  const d = new FrameDecoder();
  eq('one whole frame', payloads(d.push(frame(bytes(1, 2, 3)))), [[1, 2, 3]]);
}
// 2. a frame split across every possible boundary
{
  const whole = frame(bytes(9, 8, 7, 6));
  for (let cut = 1; cut < whole.length; cut += 1) {
    const d = new FrameDecoder();
    const first = payloads(d.push(whole.slice(0, cut)));
    const second = payloads(d.push(whole.slice(cut)));
    eq(`split at ${cut}`, [...first, ...second], [[9, 8, 7, 6]]);
  }
}
// 3. log text before, between and after
{
  const d = new FrameDecoder();
  const stream = join(
    text('INFO | Booting\n'), frame(bytes(1)),
    text('DEBUG | radio up\n'), frame(bytes(2, 2)),
    text('trailing log'),
  );
  eq('frames among log text', payloads(d.push(stream)), [[1], [2, 2]]);
  eq('log kept', d.takeLog(), 'INFO | Booting\nDEBUG | radio up\ntrailing log');
}
// 4. a lone 0x94 at the end of a read is not dropped
{
  const d = new FrameDecoder();
  const whole = frame(bytes(5, 5));
  eq('0x94 held, nothing yet', payloads(d.push(whole.slice(0, 1))), []);
  eq('completed next read', payloads(d.push(whole.slice(1))), [[5, 5]]);
}
// 5. 0x94 0xC3 inside log output, with an implausible length
{
  const d = new FrameDecoder();
  const stream = join(bytes(0x94, 0xc3, 0xff, 0xfe), text('log'), frame(bytes(7)));
  eq('resyncs past a false header', payloads(d.push(stream)), [[7]]);
}
// 6. a zero-length payload is a real frame
{
  const d = new FrameDecoder();
  eq('empty payload', payloads(d.push(frame(bytes()))), [[]]);
}
// 7. several frames in one read
{
  const d = new FrameDecoder();
  const stream = join(frame(bytes(1)), frame(bytes(2)), frame(bytes(3)));
  eq('three at once', payloads(d.push(stream)), [[1], [2], [3]]);
}
// 8. one byte at a time, the worst case
{
  const d = new FrameDecoder();
  const stream = join(text('x'), frame(bytes(4, 4)), text('y'), frame(bytes(6)));
  const got = [];
  for (const b of stream) got.push(...payloads(d.push(Uint8Array.of(b))));
  eq('byte at a time', got, [[4, 4], [6]]);
}
// 9. the buffer does not grow without bound on pure log
{
  const d = new FrameDecoder();
  for (let i = 0; i < 200; i += 1) d.push(text('a long line of firmware log output\n'));
  eq('buffer stays small', d.buffer.length <= 1, true);
}
// 10. framing rejects an oversized payload rather than truncating
{
  let threw = false;
  try { frame(new Uint8Array(MAX_PAYLOAD + 1)); } catch { threw = true; }
  eq('oversized payload refused', threw, true);
  eq('at the limit is fine', frame(new Uint8Array(MAX_PAYLOAD)).length, MAX_PAYLOAD + 4);
}
// 11. round trip at the maximum length
{
  const d = new FrameDecoder();
  const big = new Uint8Array(MAX_PAYLOAD).fill(0x41);
  eq('max-length round trip', payloads(d.push(frame(big))).map((p) => p.length), [MAX_PAYLOAD]);
}
console.log(failed ? `\n${failed} FAILED` : '\nall passed');
process.exit(failed ? 1 : 0);
