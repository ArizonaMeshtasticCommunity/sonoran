# Sonoran

Sonoran is the [azmsh.net](https://azmsh.net) Meshtastic dashboard. It reads
Meshtastic packets from an MQTT broker, decrypts and decodes them, stores them
in TimescaleDB with deduplication, and serves a read-only JSON API and a static
web UI.

It replaces two older tools: `az-meshtastic-metrics-exporter` (a collector with
no deduplication) and `meshview` (a web UI with a weak traceroute display and
SQLite problems).

## What it does

1. It reads Meshtastic packets from an MQTT broker.
2. It decrypts and decodes the packets.
3. It stores the packets in TimescaleDB (PostgreSQL) with deduplication.
4. It serves a read-only JSON API.
5. It serves a static web UI. There is no build step.
6. It links to a separate `mesh-graph` instance for traceroute graphs.

The web UI has a live map, a mesh graph, a firehose, per-node pages, a chat
view, statistics, a coverage planner, and a device config checker.

## How it fits together

The stack runs as six containers:

| Service | What it does | Port |
|---------|--------------|------|
| `timescaledb` | TimescaleDB (PostgreSQL) storage | internal |
| `migrate` | Runs the Alembic migrations once, then exits | — |
| `ingest` | Reads MQTT, decodes, and writes packets | — |
| `api` | The JSON API and the static web UI | 8000 |
| `jobs` | Scheduled work, such as daily snapshots | — |
| `mesh-graph` | The official mesh-graph traceroute engine | 8080 |

Three database roles keep the write path and the read path apart. The ingest
role has INSERT and UPDATE only. The API role has SELECT only. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Quick start

You need Docker and Docker Compose.

1. Copy the example environment file:

   ```bash
   cp .env.example .env
   ```

2. Edit `.env`. Set at least these:

   - `POSTGRES_PASSWORD` — the stack does not start without it.
   - `MQTT_HOST`, `MQTT_USERNAME`, `MQTT_PASSWORD` — your broker.
   - `CHANNEL_KEYS` — the base64 channel keys, comma-separated. The default
     public key is already set.
   - `MESH_GRAPH_BASE_URL` — the public URL of the mesh-graph service.

3. Start everything:

   ```bash
   docker compose up -d --build
   ```

   The `migrate` service runs the database migrations first. The other
   services wait for it.

4. Open the dashboard at <http://localhost:8000>. The mesh-graph engine is at
   <http://localhost:8080>.

## Configuration

Every setting is an environment variable. `.env.example` lists them all with a
comment on each. The ones you are most likely to change:

- `DATABASE_URL`, `DATABASE_URL_API`, `DATABASE_URL_JOBS` — one URL per role.
- `MQTT_HOST`, `MQTT_PORT`, `MQTT_USERNAME`, `MQTT_PASSWORD`, `MQTT_TOPICS`.
- `CHANNEL_KEYS` — full base64 AES keys, comma-separated.
- `CORE_CHANNELS` — the channels this mesh claims as its own.
- `MAP_TILE_URL`, `MAP_TILE_ATTRIBUTION` — the basemap. Do not point this at
  `tile.openstreetmap.org` without a `Referer`; see
  [AGENTS.md](AGENTS.md) 9.9.1.
- `STORE_TEXT_MESSAGES` — set true to keep text message bodies. This is a
  privacy decision.

Never commit `.env`. It holds secrets.

## Development

The project uses [uv](https://docs.astral.sh/uv/). Python 3.13 or newer is
required.

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

To run one service outside Compose, point the database URLs at a reachable
TimescaleDB and run its entry point:

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
`uv run python tools/prefetch_terrain.py`. See
[docs/PLANNER.md](docs/PLANNER.md).

Read [AGENTS.md](AGENTS.md) before you change ingest, the schema, or anything
that draws signal quality. Section 9 lists the traps this project has already
sprung.

## Documentation

- [docs/PLAN.md](docs/PLAN.md) — the purpose, decisions, and requirements
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — module contracts and data flow
- [docs/DATABASE.md](docs/DATABASE.md) — the full database schema
- [docs/API.md](docs/API.md) — the API specification
- [docs/PLANNER.md](docs/PLANNER.md) — the coverage planner and its licence
- [docs/QA.md](docs/QA.md) — the QA process
- [docs/ISSUES.md](docs/ISSUES.md) — open issues and what is wanted next
- [docs/RESEARCH.md](docs/RESEARCH.md) — research on the source tools and the protocol
- [docs/REVIEW.md](docs/REVIEW.md) — code review findings and their state
- [AGENTS.md](AGENTS.md) — the rules for people and agents who change the code

## Licence

The coverage engine in `src/sonoran/web/static/vendor/splat/` is a build of
[SPLAT!](https://www.qsl.net/kd2bd/splat.html), under the GNU General Public
License version 3. The Sonoran web interface uses it and therefore carries the
same licence. The licence text is at
[`src/sonoran/web/static/vendor/splat/LICENSE-GPL3`](src/sonoran/web/static/vendor/splat/LICENSE-GPL3).
See [AGENTS.md](AGENTS.md) 7.1.
