#!/usr/bin/env bash
# Back up the Sonoran database on a schedule, and keep a set number of
# the backups. The `backup` service in docker-compose.yml runs this.
#
# Why this exists: on 2026-09-25 the production box rebooted and the
# database did not start again. The storage lost writes that Postgres
# had flushed, so pg_control was stale. The newest backup was two days
# old, because tools/db_backup.sh only runs when a person runs it. See
# issue #216 and docs/DATABASE.md section 9.
#
# Each backup is two files, the same two that tools/db_backup.sh makes,
# so tools/db_restore.sh restores either one:
#
#   azmsh-<UTC timestamp>.dump   the database, custom format, compressed
#   roles-<UTC timestamp>.sql    the cluster roles
#
# A backup is written under a temporary name first. It gets its real
# name only after pg_restore reads the whole file back without an
# error. A dump that cannot be read is worse than no dump, because it
# looks like a backup. So a failed dump never enters the rotation and
# never pushes a good one out.
#
# Modes:
#   loop    (default) back up when due, then once per interval, for ever
#   once    take one backup now, then prune
#   prune   remove the backups that the rotation does not keep
#   check   exit 0 if the last good backup is recent, 1 if not. The
#           compose healthcheck runs this, so a stopped backup shows as
#           an unhealthy container in `docker ps`.
#
# Environment:
#   BACKUP_DIR               where the files go. Default: /backups
#   PGDATABASE               the database to dump. Default: azmsh
#   PGHOST, PGUSER, PGPASSWORD   the libpq connection. The roles dump
#                            needs a superuser.
#   BACKUP_KEEP_DAILY        how many of the newest backups to keep. Default: 7
#   BACKUP_KEEP_WEEKLY       how many weeks keep their newest backup. Default: 4
#   BACKUP_INTERVAL_SECONDS  the time between backups. Default: 86400
#   BACKUP_RETRY_SECONDS     the wait after a failed backup. Default: 900
#   BACKUP_STALE_SECONDS     the age at which `check` fails.
#                            Default: the interval plus 12 hours

set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/backups}"
PGDATABASE="${PGDATABASE:-azmsh}"
KEEP_DAILY="${BACKUP_KEEP_DAILY:-7}"
KEEP_WEEKLY="${BACKUP_KEEP_WEEKLY:-4}"
INTERVAL="${BACKUP_INTERVAL_SECONDS:-86400}"
RETRY="${BACKUP_RETRY_SECONDS:-900}"
STALE="${BACKUP_STALE_SECONDS:-$((INTERVAL + 43200))}"
export PGDATABASE

# The file that records the last good backup. Line 1 is its time in
# epoch seconds. Line 2 is its file name.
STATUS="$BACKUP_DIR/last-good"

# Only files with exactly this name are part of the rotation. A dump
# that a person made by hand, with any other name, is never removed.
DUMP_PATTERN='^azmsh-[0-9]{8}-[0-9]{6}\.dump$'

# The dumps in the rotation, newest first.
rotation_dumps() {
  local path name
  for path in "$BACKUP_DIR"/azmsh-*.dump; do
    name="${path##*/}"
    if [[ "$name" =~ $DUMP_PATTERN ]]; then
      printf '%s\n' "$name"
    fi
  done | sort -r
}

log() {
  printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

# The newest backup must always survive a prune.
if ((KEEP_DAILY < 1)); then
  KEEP_DAILY=1
fi

last_good_epoch() {
  if [[ -r "$STATUS" ]]; then
    head -1 "$STATUS" | tr -dc '0-9'
  fi
}

# Refuse to start a dump that could fill the disk. The estimate is the
# size of the newest good dump, times two. A full disk stops the
# database, and on this box it also stops the other accounts.
enough_space() {
  local newest need avail
  newest="$(rotation_dumps | head -1)"
  if [[ -z "$newest" ]]; then
    return 0
  fi
  need=$(($(stat -c %s "$BACKUP_DIR/$newest") * 2))
  avail=$(($(df -Pk "$BACKUP_DIR" | awk 'NR==2 {print $4}') * 1024))
  if ((avail < need)); then
    log "not enough free space: $avail bytes free, $need bytes needed"
    return 1
  fi
}

take_backup() {
  local ts tmp
  ts="$(date -u +%Y%m%d-%H%M%S)"
  tmp="$BACKUP_DIR/.partial-$ts"

  # A partial file from an attempt that was killed is garbage.
  rm -f "$BACKUP_DIR"/.partial-*

  # Docker makes a missing bind-mount directory as root. The service
  # does not run as root, so say what to change instead of letting the
  # first redirect fail with a bare "Permission denied".
  if ! touch "$tmp.probe" 2>/dev/null; then
    log "cannot write to $BACKUP_DIR as uid $(id -u); make the host directory" \
      "writable by that uid, or set BACKUP_UID and BACKUP_GID in .env"
    return 1
  fi
  rm -f "$tmp.probe"

  enough_space || return 1

  log "dumping roles"
  pg_dumpall --roles-only >"$tmp.roles" || return 1
  if ! grep -q '^CREATE ROLE' "$tmp.roles"; then
    log "the roles dump has no CREATE ROLE line"
    return 1
  fi

  log "dumping $PGDATABASE"
  pg_dump -Fc -Z6 "$PGDATABASE" >"$tmp.dump" || return 1

  # Read the whole archive back. `--list` reads only the table of
  # contents, so it does not see a file that was cut short.
  log "verifying the dump"
  pg_restore --file=/dev/null "$tmp.dump" || return 1

  mv "$tmp.roles" "$BACKUP_DIR/roles-$ts.sql"
  mv "$tmp.dump" "$BACKUP_DIR/azmsh-$ts.dump"
  printf '%s\nazmsh-%s.dump\n' "$(date -u +%s)" "$ts" >"$STATUS.tmp"
  mv "$STATUS.tmp" "$STATUS"
  log "backup azmsh-$ts.dump is good ($(stat -c %s "$BACKUP_DIR/azmsh-$ts.dump") bytes)"
}

# Keep the newest KEEP_DAILY backups. Also keep the newest backup of
# each of the newest KEEP_WEEKLY ISO weeks. Remove the others.
prune() {
  local f ts day week i=0
  local -A keep=() weeks=()
  local dumps=()
  mapfile -t dumps < <(rotation_dumps)

  for f in "${dumps[@]}"; do
    if ((i < KEEP_DAILY)); then
      keep[$f]=1
    fi
    i=$((i + 1))
    day="${f:6:8}"
    week="$(date -u -d "$day" +%G-%V)"
    if [[ -z "${weeks[$week]:-}" ]] && ((${#weeks[@]} < KEEP_WEEKLY)); then
      weeks[$week]=1
      keep[$f]=1
    fi
  done

  for f in "${dumps[@]}"; do
    if [[ -z "${keep[$f]:-}" ]]; then
      ts="${f#azmsh-}"
      ts="${ts%.dump}"
      rm -f "$BACKUP_DIR/$f" "$BACKUP_DIR/roles-$ts.sql"
      log "removed $f"
    fi
  done
}

attempt() {
  if take_backup; then
    prune
    return 0
  fi
  log "the backup failed"
  rm -f "$BACKUP_DIR"/.partial-*
  return 1
}

check() {
  local last
  last="$(last_good_epoch)"
  if [[ -z "$last" ]]; then
    echo "no good backup yet"
    return 1
  fi
  local age=$(($(date -u +%s) - last))
  if ((age > STALE)); then
    echo "the last good backup is ${age}s old"
    return 1
  fi
  echo "the last good backup is ${age}s old"
}

loop() {
  local last age
  # Wait out the rest of the interval if a backup is recent. Otherwise
  # a container that restarts often dumps the database each time.
  last="$(last_good_epoch)"
  if [[ -n "$last" ]]; then
    age=$(($(date -u +%s) - last))
    if ((age < INTERVAL)); then
      log "the last good backup is ${age}s old; next in $((INTERVAL - age))s"
      sleep $((INTERVAL - age))
    fi
  fi
  while true; do
    if attempt; then
      sleep "$INTERVAL"
    else
      sleep "$RETRY"
    fi
  done
}

mkdir -p "$BACKUP_DIR"

case "${1:-loop}" in
  loop) loop ;;
  once) attempt ;;
  prune) prune ;;
  check) check ;;
  *)
    echo "unknown mode: $1" >&2
    exit 2
    ;;
esac
