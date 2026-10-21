# DEPLOY.md — How to deploy Sonoran

This document tells you how to put a commit on a running Sonoran
deployment, how to check it, and how to go back. It uses ASD-STE100
Simplified Technical English. See #308.

No credentials and no host names are in this file. Ask the owner of the
deployment host for access.

For the day-to-day work on a running deployment (checks, restarts,
logs, backups and common faults), see `docs/OPERATIONS.md`.

## 1. The shape of a deployment

- The deployment is a clone of this repository in the home directory of
  a service account (for example `/home/team/sonoran`), on a **detached
  HEAD**. Everything runs as that account, under its own rootless
  Docker.
- The host may not reach GitHub. Deploy by **git bundle**.
- `docker-compose.yml` names the services. `docker-compose.override.yml`
  on the host adds what is local to it (for example `rf-ingest`).
  `mesh-graph` and `timescaledb` are upstream images.
- The static files are inside the `api` image, and they are hashed when
  the API starts. A frontend change needs an `api` rebuild.

## 2. Before you start

1. Make sure that nobody else is deploying. Read the deployment's
   reflog: `git -C <deployment> reflog -3 --date=iso`. Another person may
   have deployed since you last looked.
2. Write down the commit that runs now: `git rev-parse --short HEAD`.
   That is the rollback target.
3. Tag each image that you will rebuild, so that a rollback is one step:

   ```bash
   docker tag sonoran-api:latest sonoran-api:rollback-<old-sha>
   ```

   Compose names an image `<project>-<service>` and a container
   `<project>-<service>-1`. The project is the name of the directory
   that holds `docker-compose.yml`, unless `COMPOSE_PROJECT_NAME` sets
   it. The commands in this file use `sonoran`. A clone in a directory
   named `sonoran` has `sonoran-api`. `docker compose images`
   shows the names.

4. Take a snapshot of what the live API answers:

   ```bash
   python3 tools/deploy_check.py snapshot http://<api-host>:<port> > before.json
   ```

## 3. Deploy

On a machine with the repository:

```bash
git bundle create deploy.bundle <deployed-sha>..main
```

Copy the bundle to the service account. On the host, as that account:

```bash
cd <deployment>
git fetch deploy.bundle +main:refs/remotes/deploy/main
git checkout --detach refs/remotes/deploy/main
docker compose build api            # only the services whose code changed
docker compose up -d --no-deps api  # the same services
```

**Fetch into `refs/remotes/deploy/main`, never into a local branch
named `deploy/main`.** A local branch with that name shadows the remote
ref. The next `git checkout deploy/main` then goes to the stale branch,
not to what was just fetched. Git says "refname 'deploy/main' is
ambiguous" when this has happened.

To put a branch on a test deployment, fetch it to its own remote ref,
for example `refs/remotes/deploy/fix-something`, and check that out
detached in the same way.

Which services to rebuild:

| Changed | Rebuild |
|---|---|
| `src/sonoran/api/`, `src/sonoran/web/static/` | `api` |
| `src/sonoran/ingest/` | `ingest` |
| `src/sonoran/jobs/`, `src/sonoran/coverage/`, `src/sonoran/gaps/` | `jobs` |
| `src/sonoran/rf/` ingest code | `rf-ingest` |
| `src/sonoran/contrib/` | `contrib` (profile `contrib`) |
| A migration | `migrate` runs first on its own |

Do not restart `jobs` while a coverage run is in progress. A restart
during a run stops that run. Wait for `published coverage run` in its
log.

## 4. Check it on the running site

Do not stop at the diff. Check what runs:

1. Read the deployed commit back: `git rev-parse --short HEAD` in the
   deployment. A merged PR was once reported as deployed when only the
   PR before it was.
2. The rebuilt containers are `healthy` and their restart count is 0:
   `docker inspect -f '{{.State.Health.Status}} {{.RestartCount}}' sonoran-api-1`.
   `docker compose ps --format '{{.State}}'` says `running` and does not
   show health.
3. Compare the API with the snapshot:

   ```bash
   python3 tools/deploy_check.py compare before.json http://<api-host>:<port>
   ```

4. The page has the new asset hashes, and the endpoints that you
   changed answer.
5. The logs of the rebuilt services have no errors.
6. **After a deploy that changes a heavy endpoint, time it on the live
   data.** Seeded data hides slowness. #304 was found this way.

### 4.1 Many viewers (#371)

The views that cover hours or days are built by the jobs service and
read from its tables (`docs/DATABASE.md` 8.1), so most requests are
reads. On a box with spare cores, run several API workers with
`WEB_WORKERS`. Keep 1 on a small box.

Before a deployment that many people will watch goes live, load it on
**that** box, never on a small one that also runs production:

    python tools/load_test.py http://127.0.0.1:8000 --viewers 100 --tabs 2 \
        --minutes 5 --i-am-not-on-production

It prints each request's 50th, 95th and 99th percentile time, its
failures and its share of 304 answers, and exits 1 when anything failed.

## 4.2 Turn on contributors (#178)

Contributors are off until you turn them on. The design is
`docs/design/contributors.md`.

1. **The dispatcher login.** On the broker, make one login for Sonoran,
   for example `sonoran-contrib`, with a long random password. Keep the
   password for step 3.
2. **The registrar.** Set `DISPATCHER_USERNAME=sonoran-contrib` in the
   registrar's `.env`, and restart it with code that has the
   contributor rules (`docs/REGISTRAR.md` in the separate
   `sonoran-contributor` repository, not in this one). At start
   it:
   - adds the all-clients deny for `sonoran/v1/contributors/#`;
   - writes every login's rules again, with its own job topics;
   - gives the dispatcher login its rules.

   Its log says `added an all-clients broker rule` the first time.
3. **This deployment's `.env`.** Add `CONTRIB_MQTT_HOST` (empty means
   `RF_MQTT_HOST`), `CONTRIB_MQTT_PORT`, `CONTRIB_MQTT_USERNAME`,
   `CONTRIB_MQTT_PASSWORD` and `CONTRIB_MQTT_USE_TLS`. Only the
   `contrib` service receives the password (ARCHITECTURE.md 2.1).
4. **The migration.** `docker compose run --rm migrate </dev/null`
   applies `i178`.
5. **The services.** Rebuild `api`, which has the node page panel and
   the RF layer. Then start the dispatcher:

   ```bash
   docker compose build api contrib
   docker compose up -d --no-deps api
   docker compose --profile contrib up -d --no-deps contrib
   ```

6. **Check it.**
   - `docker compose logs contrib` shows no broker error. When
     messages arrive, it logs `contrib, last minute: {...}` at most once
     a minute, with counts such as `status`, `jobs`, `reading`,
     `refused` and `invalid`. With no contributor running, it logs
     nothing.
   - `/api/rf/noise-floor` answers `[]` until a reading comes.
   - With a contributor running, `status` counts go up within a
     minute, and `jobs` within a tick after a router is due.
7. **The Discord bot.** Update the cog, and enable and sync the
   `contributor` slash group (sonoran-cog README, "Upgrading").

To stop all mesh jobs, stop `contrib`
(`docker compose --profile contrib stop contrib`). Jobs that are out
expire. Nothing else changes. To remove one member, revoke their login
in Discord. That stops their RF too.

Roll back: stop `contrib`. Migration `i178` only adds tables, so it can
stay. `alembic downgrade` drops them, and every reading with them.

## 5. Roll back

```bash
docker tag sonoran-api:rollback-<old-sha> sonoran-api:latest
git checkout --detach <old-sha>
docker compose up -d --no-deps api
```

A migration that already ran is not undone by this. Read the
migration's `downgrade` before you roll back past one.

## 6. The database

- The database is `azmsh`. The roles are `azmsh_api` (SELECT only),
  `azmsh_ingest` (INSERT and UPDATE, no SELECT on `packet`) and
  `azmsh_jobs`. See AGENTS.md section 4.
- A one-off data job (for example `python -m sonoran.ingest.recover`)
  runs with the migration role's URL, in a throwaway container from the
  ingest image. The ingest role cannot read `packet`. Take a dump first.
- Do not start an extra database container on a small host. A test
  database next to the live stack can make the kernel stop live
  services when memory runs out.

## 7. Stop a server by its port

Never use `pkill -f sonoran-api` or a pattern like it. It stops every
server that matches, the ones of other people included, and it can
also match the shell that runs it. Stop one server by its process ID,
found from its port.

## 8. Give a coverage site its real position

The coverage map predicts from precise positions only (#315). A router
that shares a rounded position is left out, and the coverage page lists
it under "rounded positions". To bring it back, write the position that
its owner gives you in the overrides file. Do not guess a position from
the rounded one: a guess puts the footprint in the wrong valley, which
is the problem this rule removes. See `docs/COVERAGE.md` 9.1.2.1.

The overrides file is `RADIO_OVERRIDES_PATH`. The default is
`config/nodes.yaml` in the repository, which is copied into the image.
A position is a precise location of somebody's equipment, so keep it on
the host and out of the repository unless the owner agrees to publish
it.

1. On the host, as the service account, write the file outside the
   clone, for example `<deployment>/../sonoran-local/nodes.yaml`. Quote
   each node ID:

   ```yaml
   nodes:
     "!0a51b007":
       latitude: 33.4484
       longitude: -112.0740
       antenna_height_m: 20.0
       note: "Position from the owner, 2026-10."
   ```

   Copy the radio facts of any entry in `config/nodes.yaml` into this
   file as well. The setting names one file, and this one replaces it.

2. Mount it read-only into `jobs` and `api` in
   `docker-compose.override.yml`, and point the setting at it:

   ```yaml
   services:
     jobs:
       volumes:
         - ../sonoran-local/nodes.yaml:/etc/sonoran/nodes.yaml:ro
       environment:
         RADIO_OVERRIDES_PATH: /etc/sonoran/nodes.yaml
     api:
       volumes:
         - ../sonoran-local/nodes.yaml:/etc/sonoran/nodes.yaml:ro
       environment:
         RADIO_OVERRIDES_PATH: /etc/sonoran/nodes.yaml
   ```

   The coverage job and the calibration read the position. The API
   reads only the radio facts, for the node page. No page shows the
   position from this file.

3. Recreate the two services: `docker compose up -d --no-deps jobs api`.
   Read the `jobs` log. It says `read radio overrides for N nodes`, and
   it names every entry that it refused, with the reason.

4. The change shows from the next coverage run. To run one now, remove
   `coverage/attempts/coverage.txt` in the coverage cache. On the
   coverage page, the site is in the sites list and is no longer under
   "rounded positions".

**`COVERAGE_MIN_PRECISION_BITS` below 16 has no effect now.** The #318
deploy notes told s.azmsh.dev to set 13. Remove that line from `.env`.
The `jobs` log warns while it is there. To also draw the rounded
positions on a separate, dashboard-only map, set
`COVERAGE_INCLUDE_APPROXIMATE=true`. That costs one more prediction of
each map, so it roughly doubles the run.

## 9. The coverage signal floor (#334)

The signal floor needs margin tiles beside the colour tiles. Only the
coverage job writes them, so a run made before this change has none.
No migration is necessary, and the database does not change.

1. Rebuild `api` and `jobs` (section 3). Do not restart `jobs` while a
   coverage run is in progress.
2. Until the next coverage run, the page draws the old run's colour
   tiles as before. The "Signal floor" control is disabled and says
   that the run was made before the coverage job wrote signal margins.
   This is a working state, not a fault. The public embed does not
   change.
3. The floor works from the next coverage run. To make one now, remove
   `attempts/coverage.txt` in the coverage cache, or run
   `docker compose exec jobs sonoran-coverage-once`.
4. Check it. The `jobs` log says `published coverage run`. In the
   coverage cache, `runs/<stamp>/<preset>/infrastructure/usable/margin/`
   holds tiles. On the coverage page, open Settings: "Signal floor" is
   enabled, and 10 dB shows less ground than 0 dB.

A run's tiles take about 1.7 times the disk they took before, and the
render step takes about 1.3 times as long. See `docs/COVERAGE.md`
6.1.2.

Roll back: the older `api` and `jobs` ignore the `margin` directories
and the `margin_tiles` field in the manifest. Nothing has to be
removed. The two runs the cache keeps are pruned as usual.

## 11. The heard positions heatmap (PR 344)

1. The migration `pr344` adds one empty, nullable column to
   `position_metrics`. It is a change to the table definition only, and
   no row is written. Run `docker compose run --rm migrate </dev/null`.
2. Rebuild `api`, `ingest` and `jobs` (section 3). Do not restart
   `jobs` while a coverage run is in progress.
3. The heatmap is made once a UTC day, and once when `jobs` starts. To
   make it now: `docker compose exec jobs sonoran-heatmap-once`.
4. Check it. The `jobs` log says `activity heatmap: wrote N tiles`, and
   the supervisor logs the job's peak memory. On the coverage page, the
   layer list has "Heard positions, last 30 days".

Roll back: the older code ignores the column and the tiles. The
migration's downgrade drops the column and its values. The tiles stay
on disk until you remove `<COVERAGE_CACHE_DIR>/all/`.

