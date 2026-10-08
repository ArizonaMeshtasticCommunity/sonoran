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
- The static files are inside the `web` image, and they are hashed when
  the API starts. A frontend change needs a `web` rebuild.

## 2. Before you start

1. Make sure that nobody else is deploying. Read the deployment's
   reflog: `git -C <deployment> reflog -3 --date=iso`. Another person may
   have deployed since you last looked.
2. Write down the commit that runs now: `git rev-parse --short HEAD`.
   That is the rollback target.
3. Tag each image that you will rebuild, so that a rollback is one step:

   ```bash
   docker tag sonoran-web:latest sonoran-web:rollback-<old-sha>
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
docker compose build web            # only the services whose code changed
docker compose up -d --no-deps web  # the same services
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
| `src/sonoran/api/`, `src/sonoran/web/static/` | `web` |
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
   `docker inspect -f '{{.State.Health.Status}} {{.RestartCount}}' sonoran-web-1`.
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
docker tag sonoran-web:rollback-<old-sha> sonoran-web:latest
git checkout --detach <old-sha>
docker compose up -d --no-deps web
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

Never use `pkill -f sonoran-api` (the process inside the `web` container) or a pattern like it. It stops every
server that matches, the ones of other people included, and it can
also match the shell that runs it. Stop one server by its process ID,
found from its port.

## 9. Upgrade Notes

If you are upgrading an existing deployment:

1. **Service Rename:** The `api` service is now called `web`. You must update any `docker-compose.override.yml` files, deployment scripts, health alerters (which watch container names), or reverse proxies that reference `api` or `sonoran-api-1`. The first rollback across this rename must start the old `api` service and remove `web` (`docker compose rm -sf web`).
2. **Mesh-Graph Config:** The `mesh-graph` configuration file moved from the repository root to `config/mesh-graph.config.toml`. Move any local copies to the new path.
3. **Disabling Mesh-Graph:** The `mesh-graph` service is enabled by default. If you use a custom build or an external instance (e.g. on Coolify), you can disable the included service by adding the following to your `docker-compose.override.yml`:
   ```yaml
   services:
     mesh-graph:
       profiles: ["off"]
   ```
