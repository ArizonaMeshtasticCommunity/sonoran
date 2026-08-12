#!/usr/bin/env bash
# Back up the Sonoran database to a portable file.
#
# This runs a logical dump against the running TimescaleDB container. It
# is safe: it takes a consistent snapshot and does not stop the database.
# The result is two files:
#
#   azmsh-<timestamp>.dump   the database, custom format, compressed
#   roles-<timestamp>.sql    the cluster roles (they live outside the
#                            database, so a plain dump does not hold them)
#
# Restore them on another box with tools/db_restore.sh.
#
# Why a logical dump and not a raw copy of the volume: the timescaledb-ha
# image keeps its data at /home/postgres/pgdata. A raw copy only works
# when both ends run the exact same image, and it carries none of the
# safety a logical dump has. A dump restores into a fresh instance of any
# matching version. See docs/DATABASE.md.
#
# Environment:
#   BACKUP_DIR      where to write the files. Default: ~/sonoran-backups
#   TSDB_SERVICE    the compose service name. Default: timescaledb
#   PGDATABASE      the database name. Default: azmsh
#
# Flags:
#   --no-text       leave text message bodies out of the dump. The bodies
#                   are a privacy decision (see docs/ISSUES.md 4.1); drop
#                   them when the dump is shared more widely than the mesh.

set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-$HOME/sonoran-backups}"
TSDB_SERVICE="${TSDB_SERVICE:-timescaledb}"
PGDATABASE="${PGDATABASE:-azmsh}"
exclude_text=0

for arg in "$@"; do
  case "$arg" in
    --no-text) exclude_text=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 2 ;;
  esac
done

if [[ ! -f .env ]]; then
  echo "no .env in $(pwd); run this from the project root" >&2
  exit 1
fi
PGPASSWORD="$(grep -E '^POSTGRES_PASSWORD=' .env | head -1 | cut -d= -f2-)"
if [[ -z "$PGPASSWORD" ]]; then
  echo "POSTGRES_PASSWORD is not set in .env" >&2
  exit 1
fi

cid="$(docker compose ps -q "$TSDB_SERVICE")"
if [[ -z "$cid" ]]; then
  echo "the $TSDB_SERVICE container is not running" >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
ts="$(date +%Y%m%d-%H%M%S)"
dump="$BACKUP_DIR/azmsh-$ts.dump"
roles="$BACKUP_DIR/roles-$ts.sql"

echo "Dumping roles ..."
docker exec -e PGPASSWORD="$PGPASSWORD" "$cid" \
  pg_dumpall -U postgres --roles-only > "$roles"

exclude_args=()
if [[ "$exclude_text" -eq 1 ]]; then
  echo "Leaving text_message bodies out of the dump."
  exclude_args=(--exclude-table-data 'public.text_message')
fi

echo "Dumping $PGDATABASE (this holds the packets, so it is the large one) ..."
docker exec -e PGPASSWORD="$PGPASSWORD" "$cid" \
  pg_dump -U postgres -Fc -Z6 "${exclude_args[@]}" "$PGDATABASE" > "$dump"

echo
echo "Done. Two files in $BACKUP_DIR:"
ls -lh "$dump" "$roles" | awk '{print "  "$5"\t"$9}'
echo
echo "Move them to the other host over a private network:"
echo "  scp '$dump' '$roles' user@backup-host:~/sonoran-backups/"
echo
echo "Then on that box, from the project root:"
echo "  tools/db_restore.sh ~/sonoran-backups/azmsh-$ts.dump ~/sonoran-backups/roles-$ts.sql"
