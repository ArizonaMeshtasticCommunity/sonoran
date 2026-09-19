#!/usr/bin/env bash
# Start a local preview of the dashboard.
#
# The script does five things:
#   1. It starts a TimescaleDB container.
#   2. It runs the Alembic migrations.
#   3. It fills the database with made-up data, if the database is empty.
#   4. It starts the API with hot reload.
#   5. It prints the URL.
#
# The API reloads when you change a file in src/. The browser only
# needs a refresh to show a change to the HTML, the CSS, or the
# JavaScript, because the web UI has no build step.
#
# Use this for development only. The passwords below are not secret.
set -euo pipefail

cd "$(dirname "$0")/../.."

CONTAINER=sonoran-dev-db
PASSWORD=devpassword
PORT=${SONORAN_DEV_PORT:-8000}

export DATABASE_URL_MIGRATE="postgresql+psycopg://postgres:${PASSWORD}@127.0.0.1:5432/azmsh"
export AZMSH_INGEST_PASSWORD=$PASSWORD
export AZMSH_API_PASSWORD=$PASSWORD
export AZMSH_JOBS_PASSWORD=$PASSWORD

# Some sandboxes do not start the Docker daemon. Start it if it is down.
if ! docker info >/dev/null 2>&1; then
  echo "==> starting the Docker daemon"
  dockerd >/tmp/dockerd.log 2>&1 &
  for _ in $(seq 1 30); do
    docker info >/dev/null 2>&1 && break
    sleep 1
  done
fi

if [ -z "$(docker ps -q -f name="^${CONTAINER}$")" ]; then
  if [ -n "$(docker ps -aq -f name="^${CONTAINER}$")" ]; then
    echo "==> starting the database container"
    docker start "$CONTAINER" >/dev/null
  else
    echo "==> creating the database container"
    docker run -d --name "$CONTAINER" \
      -e POSTGRES_DB=azmsh \
      -e POSTGRES_USER=postgres \
      -e POSTGRES_PASSWORD="$PASSWORD" \
      -p 5432:5432 \
      timescale/timescaledb-ha:pg17 >/dev/null
  fi
fi

# The image starts Postgres, runs its setup, and then restarts it. A
# single successful connection is thus not proof that the database is
# up. Wait for three connections in a row on the published port.
echo "==> waiting for the database"
ready=0
for _ in $(seq 1 90); do
  if PGPASSWORD="$PASSWORD" docker exec -e PGPASSWORD="$PASSWORD" "$CONTAINER" \
      psql -h 127.0.0.1 -U postgres -d azmsh -tAc "SELECT 1" >/dev/null 2>&1; then
    ready=$((ready + 1))
    [ "$ready" -ge 3 ] && break
  else
    ready=0
  fi
  sleep 1
done
if [ "$ready" -lt 3 ]; then
  echo "the database did not come up; see: docker logs $CONTAINER" >&2
  exit 1
fi

# The .env file gives the API its database URL.
if [ ! -f .env ]; then
  echo "==> writing .env"
  cat > .env <<ENV
# Local development preview only. Git ignores this file.
# These are not real secrets.
POSTGRES_PASSWORD=${PASSWORD}
DATABASE_URL=postgresql+asyncpg://azmsh_ingest:${PASSWORD}@127.0.0.1:5432/azmsh
DATABASE_URL_API=postgresql+asyncpg://azmsh_api:${PASSWORD}@127.0.0.1:5432/azmsh
DATABASE_URL_JOBS=postgresql+asyncpg://azmsh_jobs:${PASSWORD}@127.0.0.1:5432/azmsh
DATABASE_URL_MIGRATE=postgresql+psycopg://postgres:${PASSWORD}@127.0.0.1:5432/azmsh
AZMSH_INGEST_PASSWORD=${PASSWORD}
AZMSH_API_PASSWORD=${PASSWORD}
AZMSH_JOBS_PASSWORD=${PASSWORD}
MESH_GRAPH_BASE_URL=http://localhost:8080
TERRAIN_CACHE_DIR=/tmp/sonoran-terrain
COVERAGE_CACHE_DIR=/tmp/sonoran-coverage
LOG_LEVEL=INFO
ENV
fi
mkdir -p /tmp/sonoran-terrain /tmp/sonoran-coverage

echo "==> running the migrations"
for attempt in 1 2 3; do
  if uv run alembic upgrade head; then
    break
  fi
  if [ "$attempt" = 3 ]; then
    echo "the migrations failed" >&2
    exit 1
  fi
  echo "==> the migrations failed, retry ${attempt}"
  sleep 5
done

NODES=$(docker exec -e PGPASSWORD="$PASSWORD" "$CONTAINER" \
  psql -U postgres -d azmsh -tAc "SELECT count(*) FROM node" 2>/dev/null || echo 0)
if [ "$NODES" = "0" ]; then
  echo "==> filling the database"
  SEED_DATABASE_URL="postgresql+asyncpg://postgres:${PASSWORD}@127.0.0.1:5432/azmsh" \
    uv run python tools/dev/seed.py
else
  echo "==> the database has ${NODES} nodes already, so no data is added"
fi

# The coverage gaps page reads a written file, not the database, so it
# has nothing to show until the job has run once. The job is only SQL
# and takes well under a second on the seed, so it runs here rather
# than leaving a preview with one empty page on it.
#
# The coverage map is not built here. That one runs the engine and takes
# minutes, so it stays a deliberate `sonoran-coverage-once`. Until it is
# run, the gaps page reports the predicted signal as "cannot tell",
# which is the honest state and worth seeing too.
echo "==> measuring the coverage gaps"
uv run sonoran-gaps-once || echo "==> the gaps job failed; the page will say so"

echo "==> the dashboard is at http://127.0.0.1:${PORT}"
exec uv run uvicorn --factory sonoran.api.app:create_app \
  --host 127.0.0.1 --port "$PORT" --reload --reload-dir src
