/*
 * Coverage engine worker.
 *
 * This worker owns one instance of the SPLAT! WebAssembly module and
 * computes a slice of the radials of one coverage run.
 *
 * It is a port of `src/engine/core.ts`, `src/engine/protocol.ts` and
 * `src/engine/coverage.worker.ts` from the Meshtastic Site Planner,
 * written as plain JavaScript because this project has no build step.
 * The engine itself is vendored without change. See vendor/splat/.
 *
 * Two rules run through the whole file:
 *
 * 1. Read `HEAPU8`, `HEAP32` and `HEAPF64` again after any call that can
 *    grow the heap. A view taken before the growth points at a buffer
 *    that has been thrown away, and reads rubbish without any error.
 * 2. Every `_splat_malloc` needs a `_splat_free` in a `finally` block.
 *    A run allocates many times, and the module has no garbage collector.
 */

import createSplatModule from './vendor/splat/splat_driver.mjs';

const ENGINE_ERRORS = {
  '-1': 'out of memory',
  '-2': 'bad handle',
  '-3': 'bad page',
  '-4': 'coverage region too large',
  '-5': 'invalid parameters',
};

class EngineError extends Error {
  constructor(code, what) {
    super(`${what}: ${ENGINE_ERRORS[String(code)] || `engine error ${code}`}`);
    this.name = 'EngineError';
    this.code = code;
  }
}

/** Raise on a negative return code. Every engine call goes through this. */
function check(code, what) {
  if (code < 0) throw new EngineError(code, what);
  return code;
}

/** Cells in one elevation page at a given resolution. */
function pageCells(ippd) {
  return ippd * ippd;
}

/** One coverage computation. Wraps an engine handle. */
class EngineContext {
  constructor(module, handle, ippd) {
    this.m = module;
    this.handle = handle;
    this.ippd = ippd;
  }

  static create(module, p) {
    const handle = module._splat_create(
      p.lat,
      p.lon,
      p.txAltFeet,
      p.rxAltFeet,
      p.frequencyMhz,
      p.erpWatts,
      p.groundDielectric,
      p.groundConductivity,
      p.atmosphereBending,
      p.radioClimate,
      p.polarization,
      p.conf,
      p.rel,
      p.clutterHeightM,
      p.radiusKm,
      p.resolutionIppd,
    );
    check(handle, 'splat_create');
    return new EngineContext(module, handle, p.resolutionIppd);
  }

  /** Return the south-west corner of every page the run needs. */
  pages() {
    const count = check(this.m._splat_page_count(this.handle), 'splat_page_count');
    const out = this.m._splat_malloc(8);
    try {
      const refs = [];
      for (let i = 0; i < count; i += 1) {
        check(this.m._splat_page_info(this.handle, i, out), 'splat_page_info');
        const base = out >> 2;
        refs.push({ minNorth: this.m.HEAP32[base], minWest: this.m.HEAP32[base + 1] });
      }
      return refs;
    } finally {
      this.m._splat_free(out);
    }
  }

  loadPage(index, data) {
    const cells = pageCells(this.ippd);
    if (data.length !== cells) {
      throw new Error(`page ${index}: expected ${cells} cells, got ${data.length}`);
    }
    const bytes = new Uint8Array(data.buffer, data.byteOffset, data.byteLength);
    const ptr = this.m._splat_malloc(bytes.length);
    if (!ptr) throw new EngineError(-1, 'splat_malloc');
    try {
      // The allocation above may have grown the heap, so take the view now.
      this.m.HEAPU8.set(bytes, ptr);
      check(this.m._splat_load_page(this.handle, index, ptr), 'splat_load_page');
    } finally {
      this.m._splat_free(ptr);
    }
  }

  radialCount() {
    return check(this.m._splat_radial_count(this.handle), 'splat_radial_count');
  }

  runRadials(start, count) {
    return check(this.m._splat_run_radials(this.handle, start, count), 'splat_run_radials');
  }

  rasterize() {
    check(this.m._splat_rasterize(this.handle), 'splat_rasterize');
  }

  region() {
    const out = this.m._splat_malloc(8 * 8);
    try {
      check(this.m._splat_region_info(this.handle, out), 'splat_region_info');
      const view = this.m.HEAPF64;
      const base = out >> 3;
      return {
        width: view[base],
        height: view[base + 1],
        north: view[base + 2],
        south: view[base + 3],
        east: view[base + 4],
        west: view[base + 5],
        radials: view[base + 6],
        pages: view[base + 7],
      };
    } finally {
      this.m._splat_free(out);
    }
  }

  signal(width, height) {
    const ptr = this.m._splat_signal_ptr(this.handle);
    if (!ptr) throw new Error('no signal raster: rasterize first');
    return this.m.HEAPU8.slice(ptr, ptr + width * height);
  }

  mask(width, height) {
    const ptr = this.m._splat_mask_ptr(this.handle);
    if (!ptr) throw new Error('no mask raster: rasterize first');
    return this.m.HEAPU8.slice(ptr, ptr + width * height);
  }

  /** Counts of ITM model warnings, by error number. */
  errnumCounts() {
    const out = this.m._splat_malloc(6 * 4);
    try {
      check(this.m._splat_errnum_counts(this.handle, out), 'splat_errnum_counts');
      const base = out >> 2;
      return Array.from(this.m.HEAP32.subarray(base, base + 6));
    } finally {
      this.m._splat_free(out);
    }
  }

  /** One link from the transmitter to a point, with its terrain profile. */
  pointToPoint(latitude, longitude, altitudeFeet) {
    const out = this.m._splat_malloc(5 * 8);
    if (!out) throw new EngineError(-1, 'splat_malloc');
    try {
      const points = check(
        this.m._splat_point_to_point(this.handle, latitude, longitude, altitudeFeet, out),
        'splat_point_to_point',
      );
      // The call may have grown the heap. Take the view again.
      let view = this.m.HEAPF64;
      const base = out >> 3;
      const result = {
        lossDb: view[base],
        dbm: view[base + 1],
        distanceKm: view[base + 2],
        azimuthDeg: view[base + 3],
        itmErrno: view[base + 4],
        profile: [],
      };
      const profilePtr = this.m._splat_p2p_profile_ptr(this.handle);
      if (profilePtr) {
        view = this.m.HEAPF64;
        const pb = profilePtr >> 3;
        for (let i = 0; i < points; i += 1) {
          result.profile.push({
            distanceKm: view[pb + 2 * i],
            groundM: view[pb + 2 * i + 1],
          });
        }
      }
      return result;
    } finally {
      this.m._splat_free(out);
    }
  }

  destroy() {
    if (this.handle > 0) {
      this.m._splat_destroy(this.handle);
      this.handle = 0;
    }
  }
}

/*
 * Give the event loop a turn between chunks of radials.
 *
 * This must be a macrotask. With a microtask the `onmessage` handler
 * never runs, so a cancel message would sit unread until the whole run
 * finished, which is the opposite of what cancel is for.
 */
const yieldToEventLoop = (() => {
  if (typeof MessageChannel === 'undefined') {
    return () => new Promise((resolve) => setTimeout(resolve, 0));
  }
  const channel = new MessageChannel();
  let pending = null;
  channel.port1.onmessage = () => {
    const resolve = pending;
    pending = null;
    if (resolve) resolve();
  };
  return () =>
    new Promise((resolve) => {
      pending = resolve;
      channel.port2.postMessage(null);
    });
})();

/** Build a context with its terrain loaded. The caller must destroy it. */
function prepare(module, params, pageData) {
  const context = EngineContext.create(module, params);
  try {
    const refs = context.pages();
    if (pageData.length !== refs.length) {
      throw new Error(`expected ${refs.length} pages, got ${pageData.length}`);
    }
    for (let i = 0; i < refs.length; i += 1) {
      // A null page is terrain we hold nothing for. The engine reads an
      // unloaded page as sea level, which is what we want there.
      if (pageData[i]) context.loadPage(i, pageData[i]);
    }
    return context;
  } catch (error) {
    context.destroy();
    throw error;
  }
}

/** Run one slice of the radials and return its rasters. */
async function runCoverageSlice(module, params, pageData, options) {
  const context = prepare(module, params, pageData);
  try {
    const total = context.radialCount();
    const start = options.start == null ? 0 : options.start;
    const end = Math.min(options.end == null ? total : options.end, total);
    const chunk = Math.max(1, options.chunk == null ? 32 : options.chunk);

    let at = start;
    while (at < end) {
      if (options.shouldCancel && options.shouldCancel()) {
        throw new DOMException('aborted', 'AbortError');
      }
      at += context.runRadials(at, Math.min(chunk, end - at));
      if (options.onProgress) options.onProgress(at - start, end - start);
      if (at < end) await yieldToEventLoop();
    }

    context.rasterize();
    const region = context.region();
    return {
      signal: context.signal(region.width, region.height),
      mask: context.mask(region.width, region.height),
      region,
      itmWarnings: context.errnumCounts(),
    };
  } finally {
    context.destroy();
  }
}

let modulePromise = null;
const cancelled = new Set();

function getModule() {
  // The loader resolves the .wasm file next to its own URL, so no
  // locateFile override is needed while both stay in vendor/splat/.
  if (modulePromise === null) modulePromise = createSplatModule({});
  return modulePromise;
}

function post(message, transfer) {
  self.postMessage(message, transfer || []);
}

self.onmessage = async (event) => {
  const message = event.data;

  if (message.type === 'cancel') {
    cancelled.add(message.runId);
    return;
  }

  if (message.type === 'pages') {
    // Ask the engine which elevation pages this run needs. The caller
    // fetches them and sends them back in this exact order: the engine
    // loads a page by its index in this list.
    const { runId, params } = message;
    let context = null;
    try {
      const module = await getModule();
      context = EngineContext.create(module, params);
      post({ type: 'pages', runId, pages: context.pages(), radials: context.radialCount() });
    } catch (error) {
      post({
        type: 'error',
        runId,
        code: error instanceof EngineError ? `engine:${error.code}` : 'pages',
        message: error instanceof Error ? error.message : String(error),
      });
    } finally {
      if (context) context.destroy();
    }
    return;
  }

  if (message.type === 'link') {
    // One point-to-point link. This does not touch the coverage rasters,
    // so it can run before or after a sweep.
    const { runId, params, pages, target } = message;
    let context = null;
    try {
      const module = await getModule();
      context = prepare(module, params, pages);
      const result = context.pointToPoint(target.lat, target.lon, target.altFeet);
      post({ type: 'link', runId, result });
    } catch (error) {
      post({ type: 'error', runId, code: 'link', message: String(error && error.message) });
    } finally {
      if (context) context.destroy();
    }
    return;
  }

  if (message.type !== 'run') return;
  const { runId, params, pages, start, end, chunk } = message;

  try {
    const module = await getModule();
    const result = await runCoverageSlice(module, params, pages, {
      start,
      end,
      chunk,
      onProgress: (radialsDone) => post({ type: 'progress', runId, radialsDone }),
      shouldCancel: () => cancelled.has(runId),
    });
    cancelled.delete(runId);
    post(
      {
        type: 'done',
        runId,
        signal: result.signal,
        mask: result.mask,
        region: result.region,
        itmWarnings: result.itmWarnings,
      },
      [result.signal.buffer, result.mask.buffer],
    );
  } catch (error) {
    cancelled.delete(runId);
    if (error instanceof DOMException && error.name === 'AbortError') {
      post({ type: 'error', runId, code: 'aborted', message: 'cancelled' });
    } else if (error instanceof EngineError) {
      post({ type: 'error', runId, code: `engine:${error.code}`, message: error.message });
    } else {
      post({
        type: 'error',
        runId,
        code: 'internal',
        message: error instanceof Error ? error.message : String(error),
      });
    }
  }
};

post({ type: 'ready' });
