# Third-party notices

Sonoran is under the GNU General Public License version 3. See
[`LICENSE`](LICENSE). This file lists the work of other people that the
repository holds and the image ships, with the licence of each. It uses
ASD-STE100 Simplified Technical English.

Python packages are not in this list. The image installs them from the
package index, and each one carries its own licence in its install.

## 1. Vendored code that the web interface serves

The licence texts are copied without change from each project's
repository at the tag of the vendored version. They are in
[`src/sonoran/web/static/vendor/LICENSES/`](src/sonoran/web/static/vendor/LICENSES/).

Each vendored Leaflet, ECharts, protobuf.js and js-yaml file was
compared with the release file that the project publishes on npm. The
SHA-256 of each pair is the same (checked 2026-10-21).

| Component | Version | Licence | Files here | Licence text |
|---|---|---|---|---|
| [Leaflet](https://github.com/Leaflet/Leaflet) | 1.9.4 | BSD-2-Clause | `vendor/leaflet.js`, `vendor/leaflet.css`, `vendor/images/` | `LICENSES/leaflet-1.9.4-LICENSE.txt` |
| [Apache ECharts](https://github.com/apache/echarts) | 5.5.1 | Apache-2.0 | `vendor/echarts.min.js` | `LICENSES/echarts-5.5.1-LICENSE.txt`, `LICENSES/echarts-5.5.1-NOTICE.txt` |
| d3.js, parts inside ECharts | as in ECharts 5.5.1 | BSD-3-Clause | inside `vendor/echarts.min.js` | `LICENSES/echarts-5.5.1-LICENSE-d3.txt` |
| [ZRender](https://github.com/ecomfe/zrender), inside ECharts | 5.6.0 | BSD-3-Clause | inside `vendor/echarts.min.js` | `LICENSES/zrender-5.6.0-LICENSE.txt` |
| [protobuf.js](https://github.com/protobufjs/protobuf.js) | 7.6.3 | BSD-3-Clause | `vendor/config-checker/js/vendor/protobuf.min.js` | `LICENSES/protobufjs-7.6.3-LICENSE.txt` |
| [js-yaml](https://github.com/nodeca/js-yaml) | 4.2.0 | MIT | `vendor/config-checker/js/vendor/js-yaml.min.js` | `LICENSES/js-yaml-4.2.0-LICENSE.txt` |
| [Meshtastic Site Planner](https://github.com/meshtastic/meshtastic-site-planner) build of [SPLAT!](https://www.qsl.net/kd2bd/splat.html) | commit `1f1c6bd` | GPL-3.0 | `vendor/splat/splat_driver.wasm`, `vendor/splat/splat_driver.mjs` | `vendor/splat/LICENSE-GPL3`, and `vendor/splat/README.md` |
| Arizona Meshtastic Community config checker | commit `e2a892d` | **licence pending from its authors** | `vendor/config-checker/` | none yet. See section 4 |

The paths in the table are relative to `src/sonoran/web/static/`.

Notes:

- The ECharts file reports two versions. `version="5.5.1"` is ECharts
  itself. `version:"5.6.0"` is the ZRender library that ECharts 5.5.1
  bundles. The file is identical to `echarts@5.5.1/dist/echarts.min.js`.
- js-yaml carries no version in the minified file. The config checker's
  own `README.md` and `CHANGELOG.md` say 4.2.0, and the file is
  identical to `js-yaml@4.2.0/dist/js-yaml.min.js`.
- ZRender is a separate project that the ECharts build includes. The
  ECharts licence does not name it, so its own licence is here too.

## 2. Code generated from other people's schemas

| Source | Licence | Files here |
|---|---|---|
| [Meshtastic protobufs](https://github.com/meshtastic/protobufs), commit in `proto/UPSTREAM_REV.txt` | GPL-3.0 | `src/sonoran/meshtastic/*_pb2.py`, `src/sonoran/web/static/meshtastic-static.js`, `src/sonoran/web/static/meshtastic-serial-proto.js`, and `vendor/config-checker/js/protobuf/meshtastic-proto.js` |

These files are under the same licence as Sonoran, so `LICENSE` covers
them.

## 3. Data

| Data | Licence | Files here | Details |
|---|---|---|---|
| Köppen-Geiger climate map, Beck et al. (2023) | CC BY 4.0 | `src/sonoran/climate/koppen_1991_2020.u8.gz` | `src/sonoran/climate/PROVENANCE.md` |
| APRS symbol names (aprs-symbol-index) | CC BY-SA 4.0 | `src/sonoran/web/static/vendor/aprs/aprs-tables.js` | `src/sonoran/web/static/vendor/aprs/PROVENANCE.md` |
| APRS device names (aprs-deviceid `tocalls.yaml`) | CC BY-SA 2.0 | `src/sonoran/web/static/vendor/aprs/aprs-tables.js` | the same file |
| APRS symbol icons (aprs-symbols) | released "to the APRS community ... for free" | `src/sonoran/web/static/vendor/aprs/aprs-symbols-24-*.png` | the same file. Some icons are copies of company logos, which their owners hold |

Each of these is data that the code reads. Its licence covers that data
only, and does not change the licence of the code.

## 4. The config checker has no licence yet

The config checker in `src/sonoran/web/static/vendor/config-checker/` is
a copy of the community's own project at commit `e2a892d`. Its upstream
repository has no licence file, so this copy has none.

**The licence is pending from its authors.** Until they grant one, the
copy is all rights reserved, and publishing this repository publishes it.
Do not edit the vendored copy to add one here. The authors add a licence
upstream, and the copy is then made again from upstream, as `AGENTS.md`
section 8 says.

## 5. Not in this repository

- `mesh-graph` is a container image that Docker pulls from its author's
  registry when the stack starts (`docker-compose.yml`). No part of it
  is in this repository or in the Sonoran image. GitHub shows no licence
  for its source repository.
- The TimescaleDB image is pulled in the same way, and it carries its
  own licences.

## 6. When you change a vendored file

1. Replace the licence text in `vendor/LICENSES/` with the one at the
   new version's tag. Give the file the new version in its name.
2. Change the version in this file.
3. Compare the new vendored file with the project's release file, and
   record the result here.
