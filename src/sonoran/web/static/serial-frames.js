/*
 * Meshtastic's serial framing, decoded from a stream (#116).
 *
 * The firmware wraps every protobuf on the wire as
 *
 *     0x94 0xC3 <len-hi> <len-lo> <payload>
 *
 * and prints its debug log down the SAME port, in between frames and
 * in arbitrarily sized pieces. A reader therefore cannot assume that
 * one `read()` is one frame, that a frame arrives whole, or that what
 * sits between two frames is nothing.
 *
 * This is the half of #116 that needs no hardware, and the half where
 * the bugs live. The Web Serial plumbing around it -- requestPort,
 * open, the disconnect handling -- is a dozen lines that can only be
 * written against a real board.
 *
 * NOT a port of upstream's `readSerialConfig()`. That one writes
 * "\r\n" and hopes for YAML text back, which is not how the firmware
 * talks (#115). Do not revive it.
 *
 * Four things this has to get right, each of which is a real bug
 * somebody hits when they write this by hand:
 *
 *  1. A frame split across reads. The 4-byte header alone can arrive
 *     in two pieces.
 *  2. Log text between frames, which must be skipped without eating
 *     the frame that follows it.
 *  3. A lone 0x94 at the very end of a read. It may be the start of a
 *     header whose 0xC3 is in the next read, so it cannot be dropped
 *     -- and it may equally be a log byte, so it cannot be trusted.
 *  4. A length that is not plausible. `0x94 0xC3` can occur inside log
 *     output by chance; believing a 40 KB length there would stall the
 *     reader until the port closed.
 */

export const MAGIC_0 = 0x94;
export const MAGIC_1 = 0xc3;
export const HEADER_BYTES = 4;

/*
 * The firmware's own limit on a serial payload. A length above this
 * did not come from a frame header, whatever the two bytes before it
 * looked like, so the decoder resyncs instead of waiting for bytes
 * that are never going to arrive.
 */
export const MAX_PAYLOAD = 512;

export class FrameDecoder {
  constructor({ maxPayload = MAX_PAYLOAD } = {}) {
    this.maxPayload = maxPayload;
    this.buffer = new Uint8Array(0);
    /* Bytes skipped as not-a-frame. The firmware's log lives here. */
    this.skipped = [];
  }

  /** Everything skipped so far, as text, and clear it. */
  takeLog() {
    const bytes = Uint8Array.from(this.skipped);
    this.skipped = [];
    return new TextDecoder().decode(bytes);
  }

  /**
   * Add bytes from one read; return every COMPLETE payload in them.
   *
   * Returns an array because one read can finish several frames, and
   * an empty array because one read can finish none. Both are normal.
   */
  push(chunk) {
    const merged = new Uint8Array(this.buffer.length + chunk.length);
    merged.set(this.buffer, 0);
    merged.set(chunk, this.buffer.length);
    this.buffer = merged;

    const frames = [];
    for (;;) {
      const start = this._findHeader();
      if (start < 0) return frames;
      const length = (this.buffer[start + 2] << 8) | this.buffer[start + 3];
      if (length > this.maxPayload) {
        /*
         * Those two bytes were log output that happened to read as the
         * magic. Skip only the first of them: the second could itself
         * begin a real header, and skipping both would lose it.
         */
        this._skip(start + 1);
        continue;
      }
      const end = start + HEADER_BYTES + length;
      if (end > this.buffer.length) {
        /* The rest of this frame has not arrived. Keep it and wait. */
        this._skip(start);
        return frames;
      }
      this._skip(start);
      frames.push(this.buffer.slice(HEADER_BYTES, HEADER_BYTES + length));
      this.buffer = this.buffer.slice(HEADER_BYTES + length);
    }
  }

  /**
   * Index of the next complete header, or -1.
   *
   * -1 also trims the buffer down to what could still become one, so a
   * long run of log text does not grow it without bound.
   */
  _findHeader() {
    const buffer = this.buffer;
    for (let i = 0; i + 1 < buffer.length; i += 1) {
      if (buffer[i] === MAGIC_0 && buffer[i + 1] === MAGIC_1) {
        return i + HEADER_BYTES <= buffer.length ? i : this._hold(i);
      }
    }
    /*
     * No magic. A trailing 0x94 may be the first half of one, so it
     * stays; everything before it is log.
     */
    const keep = buffer.length && buffer[buffer.length - 1] === MAGIC_0 ? 1 : 0;
    this._skip(buffer.length - keep);
    return -1;
  }

  /** Keep a partial header and report "nothing complete yet". */
  _hold(index) {
    this._skip(index);
    return -1;
  }

  /** Move `count` leading bytes out of the buffer and into the log. */
  _skip(count) {
    if (count <= 0) return;
    for (let i = 0; i < count; i += 1) this.skipped.push(this.buffer[i]);
    this.buffer = this.buffer.slice(count);
  }
}

/** Frame one outgoing protobuf. The reverse of the above. */
export function frame(payload) {
  if (payload.length > MAX_PAYLOAD) {
    throw new RangeError(`payload is ${payload.length} bytes, over the ${MAX_PAYLOAD} limit`);
  }
  const out = new Uint8Array(HEADER_BYTES + payload.length);
  out[0] = MAGIC_0;
  out[1] = MAGIC_1;
  out[2] = (payload.length >> 8) & 0xff;
  out[3] = payload.length & 0xff;
  out.set(payload, HEADER_BYTES);
  return out;
}
