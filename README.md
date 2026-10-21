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
- 📱 **Installable app** — add it to a phone or computer; it says so when it is offline. See [docs/APP.md](docs/APP.md).
- ⚡ **No build step** — the web UI is plain HTML, CSS and JavaScript, with Leaflet and ECharts.

## 🧩 How it fits together

`docker compose up` starts seven containers. Two more are optional and
start only when you ask for their profile:

| Service | What it does | Port |
|---------|--------------|:----:|
| `timescaledb` | TimescaleDB (PostgreSQL) storage | internal |
| `migrate` | Runs the Alembic migrations once, then exits | — |
| `ingest` | Reads MQTT, decodes, and writes packets | — |
| `api` | The JSON API and the static web UI | **8000** |
| `jobs` | Scheduled work: snapshots, coverage, calibration, gaps, read models | — |
| `mesh-graph` | The upstream mesh-graph traceroute engine | **8080** |
| `backup` | A daily dump of the database, kept in rotation | — |
| `rf-ingest` | Optional (profile `rf`). Reads what RF stations publish | — |
| `contrib` | Optional (profile `contrib`). Gives jobs to contributors | — |

Both published ports bind to `127.0.0.1` only.

Three database roles keep the write path and the read path apart. The ingest
role has `INSERT` and `UPDATE` only. The API role has `SELECT` only. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 🚀 Quick start

You need Git, Docker, and the Docker Compose plugin (`docker compose`).
The defaults in `.env.example` are for the Arizona mesh (azmsh.net). Step
3 tells you what to change for a different mesh.

**1. Get the code and make your `.env`.**

```bash
git clone https://github.com/ArizonaMeshtasticCommunity/sonoran.git
cd sonoran
cp .env.example .env
```

**2. Set the passwords.** Replace every `CHANGE_ME` in `.env`. There are
seven: `POSTGRES_PASSWORD`, the three `AZMSH_*_PASSWORD` values, and the
password inside each of the three `DATABASE_URL*` values. Each
`DATABASE_URL*` password must be the same as its `AZMSH_*_PASSWORD`. The
comments in `.env.example` show the pairs and a command that makes four
random passwords. The database sets these passwords once, when it is
first made. A later change to `.env` does not change them.

**3. Point it at your mesh.** Set these in `.env`:

| Variable | What to put |
|----------|-------------|
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_USE_TLS` | Your MQTT broker. The default is the azmsh.net broker, which needs a login from that community. |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | The broker login. Empty means no login. |
| `MQTT_TOPICS` | The topics your gateways publish to, comma-separated. For example `msh/US/#`. |
| `CHANNEL_KEYS` | The keys of the channels to decrypt, comma-separated. The file holds the public Meshtastic default key. Add the keys of your own channels. |
| `CORE_CHANNELS` | The names of your mesh's own channels. |
| `MAP_HOME_*`, `MAP_DEFAULT_*` | The area the map opens on. The default is Arizona. Address search also drops results outside `MAP_HOME_*`. |
| `TERRAIN_LAT_*`, `TERRAIN_LON_*` | The area of the coverage planner, in whole degrees. |
| `DISPLAY_TIMEZONE` | The time zone of the times on the page. |

Give each key in `CHANNEL_KEYS` in full, as base64 of 16 or 32 bytes. The
Meshtastic apps show the default key in a short form, `AQ==`. Sonoran does
not read the short form, and ingest stops at start-up with
`KeyDecodeError`. The full form of `AQ==` is `1PG7OiApB1nwvP+rz05pAQ==`.
Do not leave `CHANNEL_KEYS` empty. An empty value gives no key at all, so
ingest stores every packet with an unknown port.

The mesh-graph service reads its broker, port and login from `.env`, but
its topic comes from `mesh-graph.config.toml`. Change `topic` in that file
to match `MQTT_TOPICS`.

**4. Make the backup directory.** The `backup` service writes to
`./backups` as uid 1000. Make the directory before the first start, so
that Docker does not make it as root:

```bash
mkdir -p backups && sudo chown 1000:1000 backups
```

Under rootless Docker, do not change the owner. Set `BACKUP_UID=0` and
`BACKUP_GID=0` in `.env` instead.

**5. Start it.**

```bash
docker compose up -d --build
```

The first build takes some minutes. Then open the dashboard at
**<http://localhost:8000>**. The mesh-graph engine is at
**<http://localhost:8080>**.

**6. Check it.** `docker compose ps -a` shows each service. `migrate` exits
with code 0 and the others stay up. `docker compose logs -f ingest` shows
a `stored packet=` line for each packet that arrives. A
`MQTT connection failed` line means that the broker settings are wrong.

### Run without mesh-graph

The `mesh-graph` image is built for `linux/amd64` only. On an ARM host,
such as a Raspberry Pi or an Apple Silicon Mac, Docker cannot pull it
unless the host can emulate amd64. Sonoran works without it: the
dashboard, the API, ingest and the jobs do not need it. Only the
traceroute drawings, and the links to the mesh-graph pages, then fail.

To leave it out, put it behind a profile in a
`docker-compose.override.yml` beside `docker-compose.yml`:

```yaml
services:
  mesh-graph:
    profiles: ["mesh-graph"]
```

`docker compose up -d` then starts the other six services. `MQTT_HOST`
must still be set in `.env`: Compose checks it for every service, the
one that does not start too.

## ⚙️ Configuration

Every setting is an environment variable. [`.env.example`](.env.example) lists
them all with a comment on each. The ones you are most likely to change:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL`, `DATABASE_URL_API`, `DATABASE_URL_JOBS` | One database URL per role |
| `AZMSH_INGEST_PASSWORD`, `AZMSH_API_PASSWORD`, `AZMSH_JOBS_PASSWORD` | The login password of each role. The migration creates the roles with these and has no default |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TOPICS` | The broker |
| `CHANNEL_KEYS` | Full base64 AES keys, comma-separated. Not the short form `AQ==` |
| `CORE_CHANNELS` | The channels this mesh claims as its own |
| `MAP_HOME_NORTH`, `MAP_HOME_SOUTH`, `MAP_HOME_EAST`, `MAP_HOME_WEST` | The area the map opens on, and the limit of address search |
| `MAP_TILE_URL`, `MAP_TILE_ATTRIBUTION` | The basemap |
| `STORE_TEXT_MESSAGES` | Set true to keep text message bodies (a privacy decision) |
| `RADIO_OVERRIDES_PATH` | The file naming each node's antenna, mast, and power |
| `COVERAGE_*` | The coverage job: how often, how far, how many workers |
| `EMBED_ENABLED`, `EMBED_FRAME_ANCESTORS` | The public coverage embed, off by default |
| `BACKUP_HOST_DIR`, `BACKUP_KEEP_*`, `BACKUP_UID` | The daily database backup. See [docs/DATABASE.md](docs/DATABASE.md) 9.1 |

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
| [docs/APP.md](docs/APP.md) | Installing the app, and what it does with no network |
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

The other vendored code and data, with the licence and the version of
each, are listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
The licence of the vendored config checker is not yet granted by its
authors. That file says what this means.
