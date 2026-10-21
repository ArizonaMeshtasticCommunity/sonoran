# Contributing to Sonoran

Thank you for your help. This file tells you how to set up the project,
how to check a change, and how to send it. It uses ASD-STE100
Simplified Technical English, as all the documents here do.

Read [`AGENTS.md`](AGENTS.md) before you change ingest, the database
schema, or anything that draws signal quality. Its section 9 lists the
traps this project has already found. The rules in it apply to people
too, not only to AI agents.

If you work with an AI coding agent, also read
[`docs/COLLABORATION.md`](docs/COLLABORATION.md).

## 1. Before you start

- **Start from an issue.** A new feature or a new metric starts from an
  issue that a person wrote. The issue says what it measures or does,
  where the data comes from, and what it cannot tell us. A bug fix needs
  a clear report. See `AGENTS.md` 3A.1.
- **Every number needs a source.** A threshold, a weight or a figure on
  the page links to the Meshtastic firmware, the protobufs, a published
  document, or a measurement in `docs/DECISIONS.md`. See `AGENTS.md`
  3A.2.
- **Check the project board.** An issue on the Roadmap board is not
  started until its status is `Ready`. See `AGENTS.md` 9.28.

## 2. Set up

You need Python 3.13 or newer, [uv](https://docs.astral.sh/uv/), Docker,
and Node.js for the frontend lint.

```bash
uv sync --extra dev
./tools/dev/preview.sh
```

`preview.sh` starts a TimescaleDB container, runs the migrations, fills
the database with made-up data, and serves the dashboard at
<http://127.0.0.1:8000> with hot reload. The web UI has no build step,
so a change to the HTML, the CSS or the JavaScript needs only a refresh.
See [`tools/dev/README.md`](tools/dev/README.md).

## 3. Check your change

Run all of these before you push. Each one must pass. CI runs the same
checks, but CI is not a test runner (section 5).

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest tests/unit
npm install --no-save eslint@9.39.5 globals@15.15.0
npx eslint src/sonoran/web/static
```

- `node_modules/` is ignored by git. Nothing is added to the served
  frontend.
- The integration tests (`tests/integration`) start a real TimescaleDB
  with testcontainers. They need Docker, and they skip when Docker is
  not available. Run them for any change to the database or to ingest.
- A schema change goes through Alembic, with an `upgrade` and a
  `downgrade`. Name the revision after its issue, for example `i366`.
  See `AGENTS.md` 8.

The full list of gates is in `AGENTS.md` 6 and in
[`docs/QA.md`](docs/QA.md).

### 3.1 Tests first

Write the test from the issue before the code. Run it and see it fail
for the right reason. Put that failing output in the pull request. Then
write the smallest code that makes it pass. Never change a test only to
make it pass. See `AGENTS.md` 3A.5.

Documentation, comments, configuration with no logic, and layout are
exceptions. For layout, a screenshot before and after is the evidence.

## 4. Write it down

- **Documentation uses ASD-STE100 Simplified Technical English.** Use
  short sentences, one instruction in each, and simple words. See
  `AGENTS.md` 3.
- **Update the matching document** in the same change: the schema in
  `docs/DATABASE.md`, an endpoint in `docs/API.md`, a module in
  `docs/ARCHITECTURE.md`, and a new trap in `AGENTS.md` 9.
- **Commit messages use conventional commits:** `feat:`, `fix:`,
  `refactor:`, `test:`, `docs:`, `chore:`.
- **No tool credit and no agent session links** in a commit, a pull
  request, an issue or a comment. See `AGENTS.md` 3A.4.

## 5. CI runs on a volunteer's hardware

Every CI job here runs on self-hosted runners that a community member
owns and pays for. There is no free monthly allowance. Each push to a
pull request costs that person machine time. So:

1. **Pull `main` first.** Other people change this repository too.
2. **Test locally first** (section 3). Do not push to find out whether
   a test passes.
3. **One pull request for a batch of work,** with one commit for each
   fix inside it, pushed once. A pull request costs one run, and its
   merge costs another.
4. **Keep a security fix in its own pull request,** never with
   features. A person merges a security pull request, never its author.
5. **Wait** if the runner is busy with the owner's own work. Look at
   `gh run list`.

This is the working agreement in `AGENTS.md` 6.2.

## 6. Open the pull request

Fill in every section of the template
([`.github/pull_request_template.md`](.github/pull_request_template.md)):

- **Summary**: what changed and why.
- **Basis**: the source of each new number, or "No new numbers".
- **Red evidence**: the new tests and their failing output on `main`.
- **Release notes**: one to three lines for the people who use the site.
- **Issues**: the issues this pull request completes or works towards.
- **Thanks**: the @handles of the people who reported, tested or
  helped.

`tools/release.py` reads "Release notes", "Issues" and "Thanks" when it
makes the next release. See [`docs/RELEASING.md`](docs/RELEASING.md).

### 6.1 The closing-keyword trap

GitHub closes an issue when "close", "fix" or "resolve", in any form,
stands next to its number, **even in a sentence that says the
opposite**, such as "this does not fix" followed by the number. Write
"part of #N" for every issue that must stay open. Use a closing word
only for an issue that this pull request completes.

Before you push, look at what your commits say:

```bash
git log --format=%B main..HEAD | grep -oiE '(close|fix|resolve)[a-z]*[: ]+#[0-9]+'
```

No output means that nothing will close. Check the pull request body
in the same way. See `docs/QA.md` 8.1.

## 7. Security

Do not report a security problem in a public issue. See
[`SECURITY.md`](SECURITY.md) for how to report one privately.
