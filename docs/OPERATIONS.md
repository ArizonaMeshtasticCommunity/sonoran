# OPERATIONS.md — Run a Sonoran deployment

This document tells you how to check a running deployment, restart a
service, read the logs, back up and restore the database, and repair
the common faults. It uses ASD-STE100 Simplified Technical English.

Run every command in the directory that holds `docker-compose.yml`.
The commands use the Docker Compose plugin (`docker compose`). The
services are in `docker-compose.yml` and in `docs/ARCHITECTURE.md` 2.
To put a new commit on a deployment, or to roll one back, see
`docs/DEPLOY.md`.

## 1. Routine checks

1. **Each service runs.**

   ```bash
   docker compose ps -a
   ```

   `migrate` is `Exited (0)`. That is correct: it runs once. Every other
   service is `Up`. A restart count that goes up means a crash loop:

   ```bash
   docker inspect -f '{{.State.Health.Status}} {{.RestartCount}}' $(docker compose ps -q api)
   ```

   Only `timescaledb`, `api` and `backup` have a healthcheck. `ingest`
   and `jobs` have none, so read their logs (step 3).

2. **The API answers.** It listens on the loopback address only.

   ```bash
   curl -fsS http://127.0.0.1:8000/health
   ```

   The answer is `{"status":"ok","version":"0.1.0"}`. `/health` does not
   read the database. It shows that the API process answers, nothing
   more. The `version` is the package version, not the release. See
   `docs/RELEASING.md` 3.1.

3. **Ingest stores packets.**

   ```bash
   docker compose logs --since 10m ingest | grep -c 'stored packet='
   ```

   A busy mesh gives many lines each minute. Zero lines for a long time
   means that ingest receives nothing. See 5.2.

4. **The jobs run.** The coverage job logs
   `published coverage run <stamp>` at the end of each run. The
   supervisor logs `the <name> job used at most N MB of its M MB limit`
   after each job.

   ```bash
   docker compose logs --since 24h jobs | grep -E 'published coverage run|used at most'
   ```

5. **The backups are current.** An `unhealthy` backup service means
   that the backups have stopped.

   ```bash
   docker compose run --rm backup check
   cat backups/last-good
   ```

   `backups/` is `BACKUP_HOST_DIR`. See `docs/DATABASE.md` 9.1.

6. **The disk has space.** Each service keeps at most three log files
   of 20 MB (`x-logging` in `docker-compose.yml`). The database, the
   backups and the coverage tiles grow. Check them with `df -h` and
   `docker system df -v`.

## 2. Restart a service

Use the service name from `docker-compose.yml`:

```bash
docker compose restart ingest
```

`restart` keeps the old environment. After a change to `.env`, make the
container again, so that it reads the new values:

```bash
docker compose up -d --no-deps ingest
```

After a code change, build the image first. See `docs/DEPLOY.md` 3 for
which service to build for each change:

```bash
docker compose build api
docker compose up -d --no-deps api
```

Rules:

- Do not restart `jobs` while a coverage run is in progress. The run
  stops. Wait for `published coverage run` in its log.
- The static files are hashed when the API starts. A frontend change
  needs an `api` rebuild.
- Never stop a server with `pkill -f`. See `docs/DEPLOY.md` 7.
- The optional services need their profile in every command, for
  example `docker compose --profile rf restart rf-ingest`.

## 3. Read the logs

```bash
docker compose logs --tail 200 ingest      # the last 200 lines
docker compose logs -f --since 1h jobs     # follow, from one hour ago
docker compose logs --since 1h             # every service
```

`LOG_LEVEL` in `.env` sets how much the Sonoran services write. The
default is `INFO`. Make the container again after a change (section 2).

The log driver keeps 60 MB for each service. Older lines are gone.
Copy a log off the box before you rely on it later.

## 4. Back up and restore

### 4.1 Backups

The `backup` service writes a dump of the database once a day into
`BACKUP_HOST_DIR` (default `./backups`), and keeps it in rotation.
`docs/DATABASE.md` 9.1 gives the rules. Each backup is two files:
`azmsh-<UTC time>.dump` and `roles-<UTC time>.sql`.

To take a backup now:

```bash
docker compose run --rm backup once
```

`tools/db_backup.sh` makes the same two files from a shell, into
`~/sonoran-backups`, and can leave the message bodies out with
`--no-text`.

A backup on the same disk does not survive the loss of that disk. Copy
the files to another machine.

### 4.2 Restore

`tools/db_restore.sh` **drops the database** and makes it again from a
dump. It asks before it does. It reads `POSTGRES_PASSWORD` from `.env`
and needs the `timescaledb` container to run.

1. Stop the services that use the database:

   ```bash
   docker compose stop api ingest jobs
   ```

   Also stop `rf-ingest` and `contrib` if they run.

2. Restore:

   ```bash
   tools/db_restore.sh backups/azmsh-<UTC time>.dump backups/roles-<UTC time>.sql
   ```

   It prints the row counts of the busiest tables at the end.

3. Start the stack again. `migrate` applies any revision that is newer
   than the dump.

   ```bash
   docker compose up -d
   ```

## 5. Common faults

### 5.1 `ingest` restarts again and again

Read its log: `docker compose logs --tail 50 ingest`.

- `KeyDecodeError`: a value in `CHANNEL_KEYS` is not base64 of 16 or 32
  bytes. A short form such as `AQ==` gives this. Give the full key. The
  public default key is `1PG7OiApB1nwvP+rz05pAQ==`.
- `password authentication failed for user azmsh_ingest`: the password
  in `DATABASE_URL` is not the one the role was made with. See 5.4.

### 5.2 Ingest runs, but stores nothing or decodes nothing

- `MQTT connection failed: ...; retry in N seconds`: the broker host,
  port, TLS setting or login is wrong.
- No `stored packet=` lines and no error: the broker sends nothing on
  `MQTT_TOPICS`. Check the topics against what your gateways publish.
- `no configured key opened packet ...`: no key in `CHANNEL_KEYS` opens
  that channel. Some lines are normal, because other people's private
  channels pass through the broker. If every packet gives it,
  `CHANNEL_KEYS` is empty or wrong. Compose passes an empty value when
  `.env` has no `CHANNEL_KEYS`, and an empty value is no key at all.

### 5.3 `migrate` fails, and nothing else starts

Read its log: `docker compose logs migrate`.

- A role password is missing, empty or still `CHANGE_ME`: the first
  revision refuses to make the roles. Set the three `AZMSH_*_PASSWORD`
  values in `.env`.
- **Two heads.** `alembic upgrade head` stops with
  `Multiple head revisions are present`. Two branches each added a
  migration on the same parent. Show the heads from a checkout of the
  same commit:

  ```bash
  uv run alembic heads
  ```

  Repair it in the code, not on the host: set the `down_revision` of
  the newer migration to the other head, or add a merge revision.
  `tests/unit/test_migrations_head.py` fails while there are two heads.
  See `AGENTS.md` 8, "Change the database schema".

### 5.4 A service cannot log in to the database

The roles get their passwords once, when the first migration makes
them. A later change to `.env` does not change them. Change the
password of the role as the superuser with `ALTER ROLE`, and change the
matching `DATABASE_URL*` in the same step. See `docs/DATABASE.md` 2.1.

### 5.5 The coverage job runs out of memory

The coverage job is the largest thing the stack runs. Two limits apply,
and their names are close:

| Setting | Read by | What it limits |
|---|---|---|
| `JOBS_MEMORY_LIMITS` | the jobs supervisor | Each job inside the container, in MB, for example `coverage=800`. |
| `JOBS_MEMORY_LIMIT` | `docker-compose.yml` (`mem_limit`) | The whole jobs container, for example `2g`. `0` is no limit. |

The signs:

- The jobs log says
  `the coverage job used N MB, over its limit of M MB, and was stopped`.
  The supervisor stopped it at its ceiling. The other jobs go on.
- The jobs log says `the coverage job waits for memory`. The run waits
  until the other jobs give memory back. It is not a fault.
- `docker inspect -f '{{.State.OOMKilled}}' $(docker compose ps -q jobs)`
  says `true`: the container passed `JOBS_MEMORY_LIMIT`.
- With no `JOBS_MEMORY_LIMIT`, the kernel can stop any process on the
  box when memory runs out, and the API is a likely one.

What to do, in this order:

1. Set `COVERAGE_WORKERS=1`. Each worker holds its own engine heap.
2. Give the coverage job a higher ceiling in `JOBS_MEMORY_LIMITS`, if
   the box has the memory.
3. Set `JOBS_MEMORY_LIMIT` to what the box can give the jobs, so that a
   job that does not fit stops inside its own container.
4. Make the run smaller: lower `COVERAGE_RADIUS_KM` or
   `COVERAGE_MAX_NODES`.

Make the jobs container again after each change (section 2).

### 5.6 mesh-graph does not start, or draws nothing

- `required variable MQTT_HOST is missing a value`: Compose checks
  `MQTT_HOST` for every service, mesh-graph too. Set it in `.env`.
- `no matching manifest for linux/arm64`: the image is for
  `linux/amd64` only. Run the stack without it. See "Run without
  mesh-graph" in `README.md`.
- `mesh-graph.config.toml` is missing: the start command has no config
  to read, and the container restarts again and again. Docker can also
  make an empty directory with that name in its place. Remove that
  directory, and restore the file from the repository.
- It runs, but holds no traces: `topic` in `mesh-graph.config.toml` is
  not the topic your gateways publish to. Compose replaces only the
  broker, the port and the login in that file.
- The traceroute page shows no drawing, and `/api/traceroutes/<id>/drawing.svg`
  answers 502 `mesh-graph is not reachable`: the API cannot reach
  `MESH_GRAPH_INTERNAL_URL`.

### 5.7 The backup service is unhealthy

- The host directory is not writable by `BACKUP_UID`. Docker makes a
  missing bind directory as root. Give it to uid 1000
  (`sudo chown 1000:1000 backups`), or set `BACKUP_UID=0` and
  `BACKUP_GID=0` under rootless Docker.
- The disk is full. The service does not start a dump when the free
  space is less than two times the newest dump.
- `backups/failures` counts the failed attempts since the last good
  backup. Read the log: `docker compose logs --tail 100 backup`.
