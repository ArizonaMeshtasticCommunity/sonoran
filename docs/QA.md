# QA.md — Quality assurance process

This document describes the quality assurance process for this project.
The process is mandatory for every change.
LLM agents do most of the work on this project.
This process exists so that their work stays correct and consistent.
It uses ASD-STE100 Simplified Technical English.

## 1. The quality gates

A change is complete only when all gates pass.
No exceptions.

| Gate | Tool | Requirement |
|------|------|-------------|
| Lint | `ruff check` | zero errors |
| Format | `ruff format` | applied to all changed files |
| Types | `mypy` | no new errors |
| Tests | `pytest` | all pass |
| Coverage | `pytest --cov` | 80 percent or more on `decode`, `crypto`, `ingest` |
| Migrations | `alembic` | upgrade and downgrade both work |
| Documentation | human or agent review | the matching doc is updated |
| Commit message | review | conventional commit format |

## 2. Local workflow

Do these steps for every change:

1. Create a branch.
2. Make the change.
3. Run the gates locally:

```bash
ruff check src tests
ruff format src tests
mypy src
pytest
```

4. Fix all failures.
5. Update the documentation.
6. Commit with a conventional commit message.
7. Open a pull request.

## 3. Continuous integration

The GitHub Actions workflow runs on every pull request.
It runs these jobs in order:

1. `ruff check` and `ruff format --check`.
2. `mypy`.
3. `pytest` with a real TimescaleDB service container.
4. Alembic check: `alembic upgrade head` and `alembic downgrade -1`.
5. Docker image build.

A pull request can merge only when all jobs pass.

## 4. Test policy

### 4.1 Unit tests

- Required for all new functions in `decode`, `crypto`, `dedup`, and the handlers.
- Unit tests never touch the network or the database.
- Use recorded fixtures from `tests/fixtures`.

### 4.2 Integration tests

- Required for database code and for the ingest pipeline.
- Use testcontainers to start a real TimescaleDB.
- The replay test loads recorded MQTT messages.
  It checks the final row counts in `packet` and `packet_seen`.

### 4.3 API tests

- Required for every endpoint.
- Use the FastAPI test client with a test database.
- Check the response shape against the pydantic models.
- Check that no endpoint accepts POST, PUT, PATCH, or DELETE.

### 4.3.1 The coverage map

1. The engine must answer the same in Python and in the browser.
   `tests/unit/test_coverage_engine.py` pins a fixed scenario by hash,
   and `tools/dev/engine_parity.js` makes that hash again. If it fails,
   the engine changed. Do not paste the new value in. Find out what
   changed.
2. Every state a new deployment starts in is a working state: no
   nodes, no positions, no preset, no terrain, no land cover, no
   calibration. `tests/integration/test_coverage_job.py` runs each one
   against a real database.
3. A change to the colour ramp must change `web/static/app.css` and
   `coverage/render.py` together. A test asserts the two agree, because
   the legend on the page is a CSS gradient and the tiles are not.

### 4.4 Fixtures

- Record real MQTT payloads from the azmsh.net broker.
- Store them as files in `tests/fixtures`.
- One file per packet family.
- Use `tools/record_fixture.py` to record encrypted protobuf messages.
- Never put private channel keys in fixtures.
  Use packets encrypted with the default public key.

## 5. Database change policy

1. Edit the SQLAlchemy models first.
2. Generate the migration with Alembic autogenerate.
3. Review the generated file by hand. Autogenerate makes mistakes on hypertables.
4. Add hypertable and retention commands by hand where needed.
5. Test upgrade and downgrade on a real database.
6. Update `docs/DATABASE.md`.
7. Never edit a migration that is applied anywhere.

## 6. Protobuf update policy

1. The protobuf definitions are pinned to an upstream commit.
2. The pin lives in `proto/UPSTREAM_REV.txt`.
3. The script `proto/update.sh` regenerates the Python modules.
   It uses the pinned `grpcio-tools` version in the script.
4. After an update, run the full test suite.
5. Record the change in the commit message.

## 7. Documentation policy

1. All documentation uses ASD-STE100 Simplified Technical English.
2. Use short sentences. One idea per sentence.
3. A code change is not complete until its documentation is updated.
4. The mapping is:
   - schema change -> `docs/DATABASE.md`
   - endpoint change -> `docs/API.md`
   - module change -> `docs/ARCHITECTURE.md`
   - process change -> `docs/QA.md`
   - direction change -> `docs/PLAN.md`
   - new gap, or work left for later -> `docs/ISSUES.md`
   - a trap that cost debugging time -> `AGENTS.md` section 9
5. Keep `AGENTS.md` current. It is the entry point for AI agents.

## 8. Commit message policy

Use conventional commits:

- `feat:` a new feature
- `fix:` a bug fix
- `refactor:` a change with no behavior change
- `test:` test changes only
- `docs:` documentation changes only
- `chore:` tooling and dependency changes

Example: `feat: add neighbor metrics handler`

## 9. Security review checklist

Check these items on every pull request:

1. No new write endpoints.
2. No string SQL with user input. Use the ORM.
3. No secrets in the repository.
4. Security headers still apply to static files.
5. New dependencies come from trusted sources. Pin versions.
6. The dashboard still refuses to be framed. `X-Frame-Options` is
   `DENY` and `frame-ancestors` is `'none'` on every path but the
   embed. See `tests/unit/test_embed.py`.
7. Nothing new leaves the server to a public viewer without going
   through `sonoran/embed/sanitise.py`.
8. A value read off disk that becomes part of a path is checked for
   shape first.

## 10. Release policy

1. Version numbers follow semantic versioning.
2. Tag releases in git.
3. The CI builds the Docker image for each tag.
4. Deploy with Docker Compose on the azmsh.net host.
5. After a deploy, check `/health` and the ingest logs.
6. Run `docker compose config --quiet` before deployment.
7. Confirm that mesh-graph subscribes to the configured MQTT topic.
