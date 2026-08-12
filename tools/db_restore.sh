#!/usr/bin/env bash
# Restore a Sonoran database dump into a TimescaleDB instance.
#
# Use this on a fresh box to load a snapshot taken with
# tools/db_backup.sh, so other people can work against real data.
#
# Usage:
#   tools/db_restore.sh <azmsh-*.dump> <roles-*.sql>
#
# It expects the timescaledb container to be running. On a fresh box:
#   cp .env.example .env      # set POSTGRES_PASSWORD and the rest
#   docker compose up -d timescaledb
#   tools/db_restore.sh ~/sonoran-backups/azmsh-<ts>.dump \
#                       ~/sonoran-backups/roles-<ts>.sql
#
# THIS IS DESTRUCTIVE. It drops the target database and recreates it from
# the dump. It asks before it does. The roles come first, because the
# dump grants rights to them.
#
# It follows the TimescaleDB restore procedure: create the extension,
# timescaledb_pre_restore(), pg_restore, timescaledb_post_restore(). See
# https://docs.timescale.com/self-hosted/latest/backup-and-restore/
#
# Environment:
#   TSDB_SERVICE    the compose service name. Default: timescaledb
#   PGDATABASE      the database name. Default: azmsh
#   FORCE=1         skip the confirmation prompt

set -euo pipefail

cd "$(dirname "$0")/.."

TSDB_SERVICE="${TSDB_SERVICE:-timescaledb}"
PGDATABASE="${PGDATABASE:-azmsh}"

dump="${1:-}"
roles="${2:-}"
if [[ -z "$dump" || -z "$roles" ]]; then
  echo "usage: tools/db_restore.sh <azmsh-*.dump> <roles-*.sql>" >&2
  exit 2
fi
for f in "$dump" "$roles"; do
  [[ -f "$f" ]] || { echo "no such file: $f" >&2; exit 1; }
done

if [[ ! -f .env ]]; then
  echo "no .env in $(pwd); run this from the project root" >&2
  exit 1
fi
PGPASSWORD="$(grep -E '^POSTGRES_PASSWORD=' .env | head -1 | cut -d= -f2-)"
[[ -n "$PGPASSWORD" ]] || { echo "POSTGRES_PASSWORD is not set in .env" >&2; exit 1; }

cid="$(docker compose ps -q "$TSDB_SERVICE")"
[[ -n "$cid" ]] || { echo "the $TSDB_SERVICE container is not running" >&2; exit 1; }

dex() { docker exec -i -e PGPASSWORD="$PGPASSWORD" "$cid" "$@"; }
psql_su() { dex psql -U postgres -v ON_ERROR_STOP=1 "$@"; }

if [[ "${FORCE:-0}" != "1" ]]; then
  echo "This DROPS the '$PGDATABASE' database in container $cid and"
  echo "restores it from:"
  echo "  $dump"
  read -r -p "Type the database name ('$PGDATABASE') to continue: " reply
  [[ "$reply" == "$PGDATABASE" ]] || { echo "aborted."; exit 1; }
fi

echo "1/5  Creating roles (errors for roles that already exist are fine) ..."
# pg_dumpall --roles-only is idempotent enough: a role that exists raises,
# and ON_ERROR_STOP is off here on purpose so the rest still applies.
dex psql -U postgres -d postgres < "$roles" || true

echo "2/5  Recreating the database ..."
psql_su -d postgres -c "DROP DATABASE IF EXISTS $PGDATABASE WITH (FORCE);"
psql_su -d postgres -c "CREATE DATABASE $PGDATABASE;"

echo "3/5  Preparing TimescaleDB for the restore ..."
psql_su -d "$PGDATABASE" -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"
psql_su -d "$PGDATABASE" -c "SELECT timescaledb_pre_restore();"

echo "4/5  Restoring the data ..."
# Copy the dump into the container, restore, then remove it. Streaming
# custom-format over stdin is fussy across platforms; a temp file is not.
docker cp "$dump" "$cid:/tmp/restore.dump"
# The restore runs a couple of statements the pre_restore step also
# guards, so a stray notice is expected; the exit status is what matters.
dex pg_restore -U postgres -d "$PGDATABASE" --no-owner /tmp/restore.dump
dex rm -f /tmp/restore.dump

echo "5/5  Finishing the restore ..."
psql_su -d "$PGDATABASE" -c "SELECT timescaledb_post_restore();"

echo
echo "Row counts of the busiest tables:"
psql_su -d "$PGDATABASE" -tAc \
  "SELECT relname||': '||n_live_tup FROM pg_stat_user_tables
   ORDER BY n_live_tup DESC LIMIT 6;" | sed 's/^/  /'
echo
echo "Done. Start the rest of the stack with:  docker compose up -d"
