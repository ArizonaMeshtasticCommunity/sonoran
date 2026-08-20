// Run the reference coverage scenario in a browser and print its hash.
//
// The coverage engine is one WebAssembly file. The planner page runs it
// in a browser worker. The coverage job runs it in Python. If the two
// ever answer differently, the map the mesh publishes and the plan a
// person made stop agreeing, and nothing on either page would say so.
//
// This tool produces the reference hash. The Python side asserts the
// same hash in `tests/unit/test_coverage_engine.py`, so the test needs
// no browser and CI stays fast.
//
// The scenario is defined in `SCENARIO` below and repeated in that test
// file. Keep the two the same. The terrain is made up, not downloaded,
// so the run is the same on every machine and exercises the page order
// as well as the propagation.
//
//   ./tools/dev/preview.sh            # in one terminal, serves /static
//   node tools/dev/engine_parity.js   # in another
//
// If the hash changes, the engine changed. Do not paste the new value
// into the test to make it pass. Find out what changed. See AGENTS.md
// 9.13, which says the same about the terrain transform.
const crypto = require('crypto');
const { chromium } = require('/opt/node22/lib/node_modules/playwright');

const BASE = process.env.SONORAN_DEV_URL || 'http://127.0.0.1:8000';

// The reference scenario. `tests/unit/test_coverage_engine.py` holds
// the same numbers.
const SCENARIO = {
  lat: 34.0,
  lon: -111.5,
  txAltFeet: 12.0 / 0.3048,
  rxAltFeet: 1.0 / 0.3048,
  frequencyMhz: 906.875,
  // erp_watts(22.0 dBm, 5.8 dBi, 1.5 dB), rounded to two places as the
  // params module rounds it.
  erpWatts: Number((10 ** ((22.0 + 5.8 - 1.5 - 30) / 10)).toFixed(2)),
  groundDielectric: 15.0,
  groundConductivity: 0.005,
  atmosphereBending: 301.0,
  radioClimate: 4, // desert
  polarization: 1, // vertical
  conf: 0.5,
  rel: 0.9,
  clutterHeightM: 0.0,
  radiusKm: 20.0,
  resolutionIppd: 1200,
};

const PAGE_SIZE = 1200;

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(String(error)));

  // The dashboard is served with the CSP the engine needs, including
  // 'wasm-unsafe-eval'. Loading the module from any other page would
  // fail with nothing visible.
  await page.goto(`${BASE}/`, { waitUntil: 'domcontentloaded', timeout: 30000 });

  const result = await page.evaluate(async ({ scenario, pageSize }) => {
    const { default: createSplatModule } = await import('/static/vendor/splat/splat_driver.mjs');
    const module = await createSplatModule();

    const handle = module._splat_create(
      scenario.lat, scenario.lon, scenario.txAltFeet, scenario.rxAltFeet,
      scenario.frequencyMhz, scenario.erpWatts, scenario.groundDielectric,
      scenario.groundConductivity, scenario.atmosphereBending, scenario.radioClimate,
      scenario.polarization, scenario.conf, scenario.rel, scenario.clutterHeightM,
      scenario.radiusKm, scenario.resolutionIppd,
    );
    if (handle < 0) throw new Error(`splat_create returned ${handle}`);

    // Made-up terrain. The same pattern is built in Python.
    const cells = pageSize * pageSize;
    const count = module._splat_page_count(handle);
    for (let index = 0; index < count; index += 1) {
      const heights = new Int16Array(cells);
      for (let i = 0; i < cells; i += 1) heights[i] = (i * 7 + index * 101) % 900;
      const bytes = new Uint8Array(heights.buffer);
      const pointer = module._splat_malloc(bytes.length);
      try {
        module.HEAPU8.set(bytes, pointer);
        const code = module._splat_load_page(handle, index, pointer);
        if (code < 0) throw new Error(`splat_load_page returned ${code}`);
      } finally {
        module._splat_free(pointer);
      }
    }

    const radials = module._splat_radial_count(handle);
    for (let start = 0; start < radials; start += 64) {
      module._splat_run_radials(handle, start, Math.min(64, radials - start));
    }
    module._splat_rasterize(handle);

    const out = module._splat_malloc(8 * 8);
    let region;
    try {
      module._splat_region_info(handle, out);
      const view = module.HEAPF64;
      const base = out >> 3;
      region = { width: view[base], height: view[base + 1] };
    } finally {
      module._splat_free(out);
    }

    const size = region.width * region.height;
    const signal = module.HEAPU8.slice(
      module._splat_signal_ptr(handle), module._splat_signal_ptr(handle) + size,
    );
    const mask = module.HEAPU8.slice(
      module._splat_mask_ptr(handle), module._splat_mask_ptr(handle) + size,
    );
    module._splat_destroy(handle);

    return {
      width: region.width,
      height: region.height,
      pages: count,
      radials,
      signal: Array.from(signal),
      mask: Array.from(mask),
    };
  }, { scenario: SCENARIO, pageSize: PAGE_SIZE });

  await browser.close();

  if (errors.length) {
    console.error('page errors:\n  ' + errors.join('\n  '));
    process.exit(1);
  }

  const digest = crypto.createHash('sha256');
  digest.update(Buffer.from(result.signal));
  digest.update(Buffer.from(result.mask));

  console.log(`pages    ${result.pages}`);
  console.log(`radials  ${result.radials}`);
  console.log(`region   ${result.width} x ${result.height}`);
  console.log(`covered  ${result.mask.filter((value) => value & 248).length}`);
  console.log(`sha256   ${digest.digest('hex')}`);
}

main();
