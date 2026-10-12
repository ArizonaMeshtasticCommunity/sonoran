# DEPLOY.md — How to deploy Sonoran

This document tells you how to put a commit on a running Sonoran
deployment, how to check it, and how to go back. It uses ASD-STE100
Simplified Technical English. See #308.

No credentials and no host names are in this file. Ask the owner of the
deployment host for access.

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
