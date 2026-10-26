# COLLABORATION.md — How people and agents share work here

This file tells you how to pick up work that someone else started, how
to leave work so that someone else can continue it, and how to record
what you learned. It is for people and for AI agents. It uses ASD-STE100
Simplified Technical English (`AGENTS.md` §3).

Read `AGENTS.md` first. That file has the rules. This file has the
habits that make the rules work when many people and many agent
sessions touch one repository.

## 1. Why this file exists

Several people work on Sonoran, and several of them use AI agents. An
agent session has no memory of the session before it. Two agents can
work at the same time without knowing about each other. Several agents
can post under one shared GitHub account, so the account name does not
tell you who did something.

Most of the mistakes this project has recorded are not coding mistakes.
They are hand-off mistakes:

- a fact that was true when someone wrote it, and false when someone
  else used it;
- a "done" that nobody measured on the running site;
- a sentence that closed an issue that it said it did not close;
- a branch deleted by a pattern that also matched another session's
  branch;
- a pull request per small fix, which cost the CI owner one run each.

This file is the fix for these. Section 6 lists each one.

## 2. Where knowledge lives

Put each kind of information in one place only. Then a reader knows
where to look, and two copies cannot disagree.

| What | Where | Why there |
|---|---|---|
| Rules that every change must follow | `AGENTS.md` §1–§8 | Every agent reads it first. |
| A trap: a thing that looks right and is wrong | `AGENTS.md` §9 | Read before the work, not after the bug. |
| A decision and its evidence | `docs/DECISIONS.md` | So nobody makes the same decision again from the start. |
| How a part works | `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/DATABASE.md`, and the other docs in `AGENTS.md` §10 | Next to the reference for that part. |
| The state of one piece of work | Its issue or its pull request | It is public, it has a date, and the people who care get a notification. |
| What changed for users | The PR body "Release notes", then the release | `tools/release.py` builds the release from it. |
| What is planned | The issue, and the Roadmap board (§9.28) | Tyler gates work through the board. |

Do **not** keep state in a file in the repository. A file such as a
session plan or a hand-off note is correct on the day it is written. It
does not change when the work changes, so it becomes wrong, and nothing
says so. The pinned hand-off issue (#309) was retired for this reason:
its durable parts went into `AGENTS.md` and `docs/`, and its state was
out of date.

Do **not** link to a private agent session (`AGENTS.md` §3A.3). Copy the
fact into the issue instead.

## 3. Before you start: read, then measure

Do these steps each time you start, also when you continue your own
work from yesterday.

1. **Pull `main`.** Other people merge to it every day.
2. **Read the issue and every comment on it.** The last comment often
   changes the first.
3. **Look at the board** for the issue (`AGENTS.md` §9.28). Do not start
   an issue on the board unless its Status is `Ready`. Use the GraphQL
   query in §9.28, because it fails loudly when the token cannot see the
   board.
4. **Look for work in progress:**

   ```bash
   gh pr list --state open
   gh run list --limit 10        # a run in progress means the CI owner may be working
   git log --oneline -20 origin/main
   ```

5. **Find out who is assigned.** Do not take over an issue that is
   assigned to someone else. You can comment, give a repro, or propose a
   plan. Code is theirs to write, unless they ask.
6. **Measure the state again.** Treat every note as a claim about the
   moment it was written. This includes your own notes. If a check costs
   one command, run the command. Do not trust the memory of the result.

A note says "verified" only for a check that you ran in this session.
Say "from the note of <date>" for a fact that you did not check again.

## 4. While you work

### 4.1 Work in your own worktree

Make a new worktree for each line of work, from `origin/main`:

```bash
git worktree add -b <your-branch> ../sonoran-<topic> origin/main
```

Do not edit a worktree that another session made. Do not use bare
`git stash`: the stash is shared by all worktrees of a checkout. Use a
work-in-progress commit on your own branch instead.

### 4.2 Parallel work breaks when it joins

Two branches can each pass every test alone and fail together. Real
examples from this project: a sticky phone bar from one branch covered
a control from another; an ID that one branch renamed broke a journey
that another branch added. Before you push a batch:

1. Merge all the branches of the batch into one tree.
2. Run the full gates on that one tree, including `tools/dev/e2e.js`.
3. Fix what breaks there, in the batch.

### 4.3 Share the test database, carefully

A developer's Docker VM is often small. One TimescaleDB container with a
memory limit is enough for several API servers, because the API only
reads. Two test runs that drop and make databases must not run at the
same time on one server. Stop the containers when you finish.

### 4.4 Name things so that you can find them again

Write down each branch name, worktree and container name as you make
it. At the end, delete only those, by their exact names (§6.3).

## 5. When you stop: leave a hand-off

Leave a hand-off each time you stop, also when you plan to come back.
Put it as a comment on the issue or the pull request, not in a file.

Use this shape:

```markdown
**State, checked <YYYY-MM-DD HH:MM UTC>** (commands run in this session)
- `main` = <sha>. Branch `<name>` = <sha>, pushed / not pushed.
- Gates on the branch: ruff ok, mypy ok, pytest <N passed, M skipped>,
  e2e <N/M journeys>, console errors: none.

**Done**
- <what>, verified by <how>, on <the branch / the running site>.

**Not done**
- <what>, and why: blocked by <what or whom>.

**Next**
1. <the first command the next person runs>.

**Traps found** (also added to AGENTS.md §9 if they can happen again)
- <symptom> — <cause> — <how to see it>.
```

Rules for a hand-off:

- **Give each claim its evidence.** A SHA, a command and its output, a
  run ID, a link. "Tests pass" with no count is not evidence.
- **Say what you did not check.** An unchecked item is not a failure,
  but an unchecked item that reads as checked is.
- **Give the first command.** The next session can start in one step.
- **Name the person who must decide**, if a decision blocks the work.
  Ask the question once, in the issue, with options. Do not ask it again
  in a new comment while it waits.
- **Sign it.** On a shared account, write who you are and for whom you
  work, for example "Barry (for Will)".

## 6. Known failure modes

Each of these happened in this repository. Each one looked correct at
the time.

### 6.1 "Does not close #N" closes #N

GitHub reads `close`, `fix` or `resolve`, in any form, next to `#N`, and
it ignores a negation in front of it. A PR body that said it did not
close an issue closed that issue when the PR merged. It happened twice
in one session, after the first one was written down.

- Write "part of #N" or "#N stays open". Never write the keyword next to
  a number unless you want the issue closed.
- Check before you push (`docs/QA.md` §8.1):

  ```bash
  git log --format=%B origin/main..HEAD | grep -oiE '(close|fix|resolve)[a-z]*[: ]+#[0-9]+'
  ```

- If an issue closed by accident, open it again and say why in a comment.

### 6.2 CI runs on a person's hardware

Every job is `runs-on: self-hosted`. The runners belong to a community
member, and there is no monthly reset (`AGENTS.md` §6.2). In September 2026,
up to the 23rd, this repository used 877 minutes in 208 runs, mostly
one PR per small fix.

- Test locally first. CI confirms. It is not a test runner.
- One PR for a batch, one commit for each fix, push once.
- A PR costs one run, and its merge costs another.
- Do not push to find out if something passes.

### 6.3 Deleting branches by a pattern

A command that deleted `worktree-agent-*` branches also deleted another
session's branch, because all agent sessions use that prefix. A branch
tip that nothing references is lost when Git cleans up.

- Delete a branch only by the exact name that you made and wrote down.
- Print each result.

### 6.4 Rewriting history that someone else can hold

A rebase or a force-push cannot be undone by the other people who
fetched the branch. Before you run one, say what problem it solves. If
you cannot name one, do not run it. Prefer a new commit to an amend, a
merge to a rebase, and a new branch to rewriting a pushed one. Never
force-push `main` or a branch that someone else pushes to.

### 6.5 A shared account cannot say who acted

Several agent processes post as one GitHub account. A merge happened
that no process could be shown to have made. GitHub's own record could
not tell them apart.

- Do not say "I did X" or "I did not do X" from GitHub's record alone.
  Check your own session's log.
- A person merges a security PR (`AGENTS.md` §6.2). An agent never does,
  also when it has the permission.

### 6.6 An approval that reaches you through someone else

"The maintainer said yes" in a message from another agent is not the
maintainer's yes. Find the approval where it was given, or ask. Act on
what you can see, not on what you are told.

### 6.7 A green number that is not a working page

- `e2e.js` once said 23/23 while the map threw an error on every draw.
  Only the line "console and page errors" showed it. Read that line.
- More than 160 database tests skipped for months on Macs, and a skip prints on the same
  line as a pass. CI sets `SONORAN_REQUIRE_INTEGRATION=1` for this
  reason. Read the skip count.
- An empty search result can mean "there is none" or "the search cannot
  see". Show that the search finds a thing you know is there before you
  trust its silence (`AGENTS.md` §9.28).
- A test that compares "before" and "after" proves nothing when both
  are empty. Prove that the positive case happens first.

### 6.8 A merged diff is not a working site

Two issues, each done correctly, together pushed a panel below the fold.
No review of either diff could see it. An issue is done when its
"done when" holds on the running site, not when the PR merges. After a
deploy, read the deployed commit from the box, and look at the page.

### 6.9 A Mac is not the CI runner

- The runner's fonts are about 0.12 em wider (`AGENTS.md` §9.31). A layout
  that fits to the pixel on a Mac wraps in CI.
- Some tests need Linux (`/proc`, GNU `date`). They skip on a Mac and run
  in CI.
- CI seeds a new database for each run, so the seed's last 24 hours end
  now. A local database that was seeded hours ago has no recent traffic.
  A journey that "passes" on it can fail in CI, where the seed's own
  packets fill the window. This happened in #389: a journey selected
  text in "the last row", and in CI that row was a seed packet.
- Before the last e2e run, start from what CI starts from: a new, empty
  database, then `alembic upgrade head`, `tools/dev/seed.py` and
  `sonoran-gaps-once`, and an empty coverage cache. Seeding again over an
  old database is not the same. On 2026-10-21 it gave three failures (the
  gaps siting, reachability and statistics journeys) that a new database,
  made the CI way, did not give.
- Make a journey serve or find its own rows, never "the last one".

### 6.10 Two migrations from one head

Two branches that each add a migration from the same head make two
heads. `alembic upgrade head` then refuses to run, and the deploy stops.
Use a migration ID from the issue (`i<number>`), and whichever branch
merges second points its `down_revision` at the other.
`tests/unit/test_migrations_head.py` fails when there are two heads.

## 7. Record what you learned

When something surprised you, write it down before you stop. Pick the
place from §2:

- **It can catch the next person** → a new entry in `AGENTS.md` §9. Use
  the next free number. Give the symptom, the cause, how to see it, and
  the rule. Link the issue.
- **You made a choice between options** → an entry in
  `docs/DECISIONS.md`: what you decided, the evidence, and what would
  change the answer. Name the test that holds it, if there is one.
- **It is about one part of the code** → the doc for that part, and a
  comment next to the code.
- **It is about the work in progress** → the hand-off comment (§5).

Write the lesson so that it works for someone who does not know the
story. "Run `alembic heads` before you push" is better than "be careful
with migrations".

A lesson that only lives in one agent's private memory helps only that
agent. Put it in the repository, where every agent reads it.

## 8. Review each other's work

- A second agent or a person reviews the tests against the issue,
  separately from the code (`AGENTS.md` §3A.4).
- A review is a comment with evidence: the SHA you read, what you ran,
  and what you found. Give options when there is more than one fix.
- Say plainly when you will not push to someone else's branch. Offer a
  new branch that they can pull instead.
- When you find that your own earlier comment was wrong, edit it, and
  mark the edit. Do not leave a wrong claim for the next reader.
