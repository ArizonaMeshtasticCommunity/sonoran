# PLAN.md — Purpose, decisions, and requirements

This document is the master plan for Sonoran, the azmsh.net Meshtastic dashboard.
It uses ASD-STE100 Simplified Technical English.

## 1. Purpose

The azmsh.net project runs two applications today:

- `az-meshtastic-metrics-exporter` collects MQTT data into TimescaleDB.
  It has the most complete collector.
  It does not deduplicate packets.
- `meshview` shows the data in a web UI.
  It deduplicates most packets.
  Its traceroute display is poor.
  Its SQLite database has reliability problems at our volume.

This project replaces both applications with one new application.
The new application keeps the strengths of both.
It fixes the weaknesses of both.

A third application, `mesh-graph`, stays in use.
It displays traceroute graphs.
The new application links to it.
We do not fork it.

## 2. Decisions

These decisions are final.
Do not reopen them without a documented reason.

| # | Decision | Choice |
|---|----------|--------|
| D1 | Language | Python 3.13 or newer |
| D2 | Database | TimescaleDB (PostgreSQL with the TimescaleDB extension) |
| D3 | API | Read-only JSON API. GET endpoints only. FastAPI |
| D4 | Frontend | Static files. HTML, HTMX, Alpine.js, Leaflet, ECharts. No build step |
| D5 | Deduplication | meshview model. One `packet` row. Many `packet_seen` rows |
| D6 | Raw data | Store the raw protobuf bytes of every unique packet |
| D7 | Traceroute graphs | Link to our own `mesh-graph` container. No fork |
| D8 | MQTT source | The azmsh.net broker. Host, topics, and keys come from environment variables |
| D9 | Deployment | Docker Compose on the azmsh.net host |
| D10 | Documentation | ASD-STE100 Simplified Technical English |
| D11 | Maintenance | LLM agents do most of the work. The QA process in `docs/QA.md` is mandatory |

## 3. Requirements

### 3.1 Scale requirements

- More than 1000 nodes are active on the network.
- Each node sends between 12 and 2000 packets per hour.
- The system must handle several million packet observations per day.
- The system must not lose packets when a handler fails.
- The system must not stop when the MQTT connection fails.
  It must reconnect.

### 3.2 Functional requirements

1. Collect all packet types that the exporter collects:
   - node information
   - positions
   - device metrics
   - environment metrics
   - air quality metrics
   - power metrics
   - pax counter metrics
   - neighbor information
   - mesh packet statistics
   - traceroutes
   - text messages
2. Deduplicate packets on (`from_node_num`, `packet_id`).
3. Store one observation row for each MQTT uplink of a packet.
4. Store the raw protobuf bytes of each unique packet.
5. Give a read-only JSON API for all stored data.
6. Give a static web dashboard for users.
7. Link each node and each traceroute to the matching `mesh-graph` page.
8. Apply automatic data retention.
9. Store daily snapshots for long-term statistics.

### 3.3 Non-functional requirements

1. Security: the public surface is read-only. Static files plus GET endpoints.
2. Reliability: no SQLite. TimescaleDB only.
3. Modularity: each module has one job. Modules have documented interfaces.
4. Testability: decoding and decryption have no database dependency.
5. Maintainability: the QA gates in `docs/QA.md` apply to every change.

## 4. System overview

```
MQTT broker (azmsh.net)
   |
   v
[ingest service]  Python, aiomqtt
   |  decrypt, decode, deduplicate
   v
TimescaleDB  (packet, packet_seen, node, metric tables)
   ^
   |  SQLAlchemy async, SELECT-only role
[api service]  FastAPI, GET endpoints only
   |
   v
[static UI]  HTML + HTMX + Alpine.js + Leaflet + ECharts
   |
   +-- links and embeds --> [mesh-graph container]
```

Three containers run the Python code:

- `ingest`: connects to MQTT. It is the only writer to most tables.
- `api`: serves the JSON API and the static files.
- `jobs`: runs retention checks and daily snapshots.

The `mesh-graph` container runs the upstream image.
It has its own MQTT subscription and its own small database.

## 5. Repository layout

```
azmsh-custom-app/
├── AGENTS.md                  # rules for AI agents
├── docs/                      # this documentation set
├── proto/                     # protobuf pin file + updater script
├── tools/                     # utilities (record_fixture.py)
├── src/sonoran/
│   ├── config.py              # environment-based settings
│   ├── logging.py
│   ├── db/
│   │   ├── models.py          # SQLAlchemy models
│   │   ├── session.py
│   │   ├── hypertables.py     # hypertable definitions
│   │   └── migrations/        # Alembic migrations
│   ├── meshtastic/            # vendored protobuf Python modules
│   ├── mqtt/
│   │   ├── client.py          # aiomqtt subscribe + reconnect
│   │   └── topics.py          # topic parsing
│   ├── crypto/
│   │   └── decrypt.py         # AES-CTR, multiple keys
│   ├── decode/
│   │   ├── envelope.py        # ServiceEnvelope to MeshPacket
│   │   └── payloads.py        # one decoder per PortNum
│   ├── terrain/
│   │   └── srtm.py            # SRTM elevation queries
│   ├── ingest/
│   │   ├── pipeline.py        # mqtt to decode to dedup to store
│   │   ├── dedup.py           # packet and packet_seen logic
│   │   └── handlers/          # one module per packet family
│   │       ├── context.py
│   │       ├── meshpacket.py
│   │       ├── neighborinfo.py
│   │       ├── nodeinfo.py
│   │       ├── paxcounter.py
│   │       ├── position.py
│   │       ├── presence.py
│   │       ├── telemetry.py
│   │       ├── text.py
│   │       └── traceroute.py
│   ├── api/
│   │   ├── app.py             # FastAPI application factory
│   │   ├── channels.py        # channel grouping
│   │   ├── dependencies.py    # DB session injection
│   │   ├── names.py           # node display name resolution
│   │   ├── schemas.py         # pydantic response models
│   │   └── routes/
│   │       ├── chat.py
│   │       ├── graph.py
│   │       ├── map.py
│   │       ├── nodes.py
│   │       ├── packets.py
│   │       ├── stats.py
│   │       └── traceroutes.py
│   ├── jobs/
│   │   ├── retention.py
│   │   └── snapshots.py
│   └── web/static/            # the static frontend
│       ├── index.html
│       ├── app.css
│       ├── app.js
│       └── vendor/            # vendored Leaflet + ECharts
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/              # recorded MQTT payloads
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── alembic.ini
├── .env.example
└── .github/workflows/ci.yml
```

## 6. Build state

Every build phase of the first roadmap is complete. The system ingests
from the azmsh.net broker, stores to TimescaleDB with deduplication,
serves the read-only API, and serves the dashboard.

Work is now tracked as issues. See `docs/ISSUES.md`.

## 7. Risks

| Risk | Effect | Mitigation |
|------|--------|------------|
| Protobuf definitions change upstream | Decode errors | Pin the protobuf commit. Use the generator script to update. Test with fixtures |
| MQTT broker sends malformed packets | Ingest errors | Isolate each packet in a try/except. Log and count bad packets. Never stop the pipeline |
| Insert volume is higher than expected | Database growth | Hypertables plus retention policies. Monitor disk usage |
| mesh-graph API changes | Broken links | Pin the container image tag. Test links in the UI tests |
| Text message privacy concerns | Public complaints | Add a config flag to disable text storage. Document it |

## 8. Open items

These were settled during the first deployment:

- The MQTT topic list is `msh/US/AZ/#`.
- The channel key list is the default public key. `CHANNEL_KEYS` is
  unset, so the built-in default applies.
- The mesh-graph instance is the one in `MESH_GRAPH_BASE_URL`.
- Text message storage is on. `STORE_TEXT_MESSAGES=true`.
