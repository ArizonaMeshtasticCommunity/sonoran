# SPLAT! coverage engine

These files are copied without change from the Meshtastic Site Planner.

- Source: https://github.com/meshtastic/meshtastic-site-planner
- Commit: `1f1c6bd4741824a582e500114510ef090bf527a6` (2026-07-23)
- Path in that repository: `src/engine/generated/`

| File | What it is |
|------|------------|
| `splat_driver.wasm` | The ITM / Longley-Rice model from SPLAT! by John A. Magliacane, KD2BD, compiled to WebAssembly. |
| `splat_driver.mjs` | The Emscripten loader for the module above. |
| `LICENSE-GPL3` | The licence both files are under. |

## Licence

The Site Planner is under the GNU General Public License version 3.
Sonoran uses its compiled engine, so the Sonoran web interface is a work
based on it and carries the same licence.

Keep `LICENSE-GPL3` beside these files. Do not remove the attribution.

## Updating

Replace both files from the same upstream commit, then write that commit
above. The two files must always come from one commit: the loader knows
the exact layout of the module it loads.

After any update, run the terrain tests. The engine reads elevation
pages made by `src/sonoran/terrain/`, and both sides must agree on the
cell order.

## What Sonoran does not copy

The Site Planner interface is a Vue application with a build step.
Sonoran has no build step, so `static/planner.js` and
`static/planner.worker.js` are a fresh implementation against the same
engine. They follow the upstream engine sources closely, and those are
named in their comments.
