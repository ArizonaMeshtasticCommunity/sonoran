<div align="center">

<img src="src/sonoran/web/static/logo.png" alt="Sonoran" width="360" />

**The [azmsh.net](https://azmsh.net) Meshtastic dashboard.**
MQTT ingest · TimescaleDB storage · read-only API · static web UI.

[![CI](https://github.com/ArizonaMeshtasticCommunity/sonoran/actions/workflows/ci.yml/badge.svg)](https://github.com/ArizonaMeshtasticCommunity/sonoran/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB?style=flat-square&logo=python&logoColor=white)](pyproject.toml)
[![License](https://img.shields.io/badge/License-GPL%203.0-EA6A3A?style=flat-square)](LICENSE)
[![Lint: Ruff](https://img.shields.io/badge/lint-ruff-EA6A3A?style=flat-square)](https://github.com/astral-sh/ruff)
[![Types: mypy](https://img.shields.io/badge/types-mypy-2A6DB2?style=flat-square)](https://mypy-lang.org/)

</div>

---

Sonoran reads Meshtastic packets from an MQTT broker, decrypts and decodes
them, stores them in TimescaleDB with deduplication, and serves a read-only
JSON API and a static web UI. It replaces two older tools:
`az-meshtastic-metrics-exporter` (a collector with no deduplication) and
`meshview` (a web UI with a weak traceroute display and SQLite problems).

## ✨ Features

- 🗺️ **Live map** — nodes, neighbour links, and live traffic, one modem preset at a time.
- 🕸️ **Mesh graph** — the network laid out over the ground it sits on, coloured by role.
- 🔭 **Planner** — SPLAT!-based signal prediction from a vendored WebAssembly engine.
- 📡 **Coverage** — where the whole mesh reaches, predicted from every node, per preset,
  corrected against what the mesh measures, and embeddable on your own site.
- 📟 **Per-node pages** — telemetry, the gateways that heard it, and its links.
- 💬 **Chat, firehose, and statistics** — every packet family, deduplicated.
- 🔗 **Traceroute graphs** — offloaded to a linked `mesh-graph` instance.
- 🔧 **Device config checker** — reads a config in the browser and sends it nowhere.
- ⚡ **No build step** — the web UI is plain HTML, HTMX, Alpine.js, Leaflet, and ECharts.

## 🧩 How it fits together

The stack runs as six containers:

| Service | What it does | Port |
|---------|--------------|:----:|
| `timescaledb` | TimescaleDB (PostgreSQL) storage | internal |
| `migrate` | Runs the Alembic migrations once, then exits | — |
| `ingest` | Reads MQTT, decodes, and writes packets | — |
| `api` | The JSON API and the static web UI | **8000** |
| `jobs` | Scheduled work, such as daily snapshots | — |
| `mesh-graph` | The official mesh-graph traceroute engine | **8080** |

Three database roles keep the write path and the read path apart. The ingest
role has `INSERT` and `UPDATE` only. The API role has `SELECT` only. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 🚀 Quick start

You need Docker and Docker Compose.

```bash
# 1. Configure
cp .env.example .env
#    Edit .env and set at least:
#      POSTGRES_PASSWORD          the stack does not start without it
#      MQTT_HOST/USERNAME/PASSWORD your broker
#      CHANNEL_KEYS               base64 channel keys (default public key is set)
#      MESH_GRAPH_BASE_URL        the public URL of the mesh-graph service

# 2. Start everything (migrations run first, automatically)
docker compose up -d --build
```

Then open the dashboard at **<http://localhost:8000>**. The mesh-graph engine is
at **<http://localhost:8080>**.

## ⚙️ Configuration

Every setting is an environment variable. [`.env.example`](.env.example) lists
them all with a comment on each. The ones you are most likely to change:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL`, `DATABASE_URL_API`, `DATABASE_URL_JOBS` | One database URL per role |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TOPICS` | The broker |
| `CHANNEL_KEYS` | Full base64 AES keys, comma-separated |
| `CORE_CHANNELS` | The channels this mesh claims as its own |
| `MAP_TILE_URL`, `MAP_TILE_ATTRIBUTION` | The basemap |
| `STORE_TEXT_MESSAGES` | Set true to keep text message bodies (a privacy decision) |
| `RADIO_OVERRIDES_PATH` | The file naming each node's antenna, mast, and power |
| `COVERAGE_*` | The coverage job: how often, how far, how many workers |
| `EMBED_ENABLED`, `EMBED_FRAME_ANCESTORS` | The public coverage embed, off by default |

> [!NOTE]
> If you use `tile.openstreetmap.org` as the basemap, the browser must send a
> `Referer` or OSM returns a "blocked" placeholder tile with no visible error.
> The `Referrer-Policy` header is set for that. See [AGENTS.md](AGENTS.md) 9.9.1.

> [!WARNING]
> Never commit `.env`. It holds secrets.

## 🛠️ Development

The project uses [uv](https://docs.astral.sh/uv/). Python 3.13 or newer is required.

```bash
uv sync --extra dev        # install the app and the dev tools
uv run ruff check .        # lint
uv run ruff format .       # format
uv run mypy                # type check
uv run pytest              # tests
```

The integration tests start a real TimescaleDB in a throwaway container with
[testcontainers](https://testcontainers.com/). They need Docker, and they skip
when Docker is not available.

### Preview a change

To see a change in a browser while you make it, start the local preview:

```bash
./tools/dev/preview.sh
```

It starts a TimescaleDB container, runs the migrations, fills the database
with made-up data, and serves the dashboard at <http://127.0.0.1:8000> with
hot reload. The web UI has no build step, so a change to the HTML, the CSS,
or the JavaScript needs only a refresh. See
[tools/dev/README.md](tools/dev/README.md).

Run one service outside Compose by pointing the database URLs at a reachable
TimescaleDB and running its entry point:

```bash
uv run sonoran-api         # the API and web UI
uv run sonoran-ingest      # the MQTT reader
uv run sonoran-jobs        # the scheduled jobs
```

Database schema changes go through Alembic:

```bash
uv run alembic upgrade head
```

The coverage planner reads terrain tiles. Fill the local cache once with
`uv run python tools/prefetch_terrain.py`. See [docs/PLANNER.md](docs/PLANNER.md).

> [!IMPORTANT]
> Read [AGENTS.md](AGENTS.md) before you change ingest, the schema, or anything
> that draws signal quality. Section 9 lists the traps this project has already
> sprung.

## 📚 Documentation

| Document | What it covers |
|----------|----------------|
| [docs/PLAN.md](docs/PLAN.md) | The purpose, decisions, and requirements |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Module contracts and data flow |
| [docs/DATABASE.md](docs/DATABASE.md) | The full database schema |
| [docs/API.md](docs/API.md) | The API specification |
| [docs/PLANNER.md](docs/PLANNER.md) | The coverage planner and its licence |
| [docs/COVERAGE.md](docs/COVERAGE.md) | The coverage map, its calibration, and the embed |
| [docs/QA.md](docs/QA.md) | The QA process |
| [docs/ISSUES.md](docs/ISSUES.md) | Open issues and what is wanted next |
| [docs/RESEARCH.md](docs/RESEARCH.md) | Research on the source tools and the protocol |
| [docs/REVIEW.md](docs/REVIEW.md) | Code review findings and their state |
| [AGENTS.md](AGENTS.md) | The rules for people and agents who change the code |

## 📄 Licence

Sonoran is licensed under the **GNU General Public License v3.0**. The coverage
engine in `src/sonoran/web/static/vendor/splat/` is a build of
[SPLAT!](https://www.qsl.net/kd2bd/splat.html) under the GPL-3, and the web
interface uses it, so the whole interface carries the same licence. The full
text is in [`LICENSE`](LICENSE). See [AGENTS.md](AGENTS.md) 7.1.
