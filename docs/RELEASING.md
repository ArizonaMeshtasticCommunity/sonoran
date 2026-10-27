# RELEASING.md — How to publish a release

This document tells you how to publish a Sonoran release.
It uses ASD-STE100 Simplified Technical English.

## 1. Why releases exist

A person who reports a bug wants to know when it is repaired.
A release names each issue that it completes and each person who reported,
wrote or tested the work, with an @handle. GitHub then notifies them.
The releases also make a log of every change, in `CHANGELOG.md`.

## 2. The rule

**After you merge to `main`, you must publish a release.**

- One release can hold many merges. If you merge three pull requests in
  one session, publish one release after the last one.
- Do not end a session with merged work that is not in a release.
  `python tools/release.py check` tells you. It exits 1 when work is
  waiting.
- If you cannot publish, say so in your report. Do not skip it silently.

## 3. The names of releases

A release is named for the date in Arizona: `vYYYY.MM.DD`.
A second release on the same day is `vYYYY.MM.DD.2`, then `.3`.

The project deploys from `main` and has no API versions to promise, so a
date tells a reader more than a semantic version number.
The script calculates the name. Do not type it yourself.

### 3.1 The version that the API reports

`/health` and `/api/version` report `version`, which is the package
version in `pyproject.toml` and `src/sonoran/__init__.py`. It is
`0.1.0`, and a release does not change it, because a release makes no
commit (section 5). So it does not tell you which release runs.

To know what a deployment runs, read its commit:
`git rev-parse --short HEAD` in the deployment (`docs/DEPLOY.md` 4).
Then, in a clone that has the tags, `git describe --tags <sha>` names the
newest release before that commit.

## 4. How to publish

1. Pull `main`.
2. Read the draft. This step changes nothing:

   ```bash
   python tools/release.py draft
   ```

3. Examine the draft. Every line is a claim to the people it names.
   - Make sure no "Done" issue is still open.
   - Make sure each person is thanked for the correct thing.
4. Publish:

   ```bash
   python tools/release.py publish
   ```

   This makes the tag and the GitHub release. It makes no commit.
5. In your **next** pull request, run `python tools/release.py changelog`
   and include the changed `CHANGELOG.md`.

For the first release only, no tag exists yet. Start it at the merge of
PR #221, the last merge of 2026-09-25, so that the fixes of that week and
their reporters are credited:

    python tools/release.py draft --since 52a63266d818dfc37eef15a4db42229f885203f4

## 5. What each release costs in CI

Nothing. This is a requirement, not an accident.

- `ci.yml` runs on `push` to `main` and on `pull_request`. A tag is not
  a push to `main`, so `publish` starts no workflow.
- `CHANGELOG.md` is not changed by a commit of its own. A commit to
  `main` would start a full CI run on self-hosted hardware for each
  release. The file travels in the next pull request, which runs CI
  anyway.
- Never add a workflow that runs on `release` or on a tag push. Every
  job in this repository is `runs-on: [self-hosted, sonoran-microvm]`,
  and that hardware belongs to a community member.

## 6. How the notes are made

`tools/release.py` reads the pull requests merged since the last tag.

| Part of the notes | Where it comes from |
|---|---|
| Section | The conventional commit prefix of the PR title (`feat:`, `fix:`, `docs:`). A `security` label wins. No prefix gives "Other". |
| One line for each PR | The title, the PR number, and the author. |
| Extra lines under a PR | The PR body's `## Release notes` section. |
| "Done" | An issue that the PR closed **and that is closed now**. A reopened issue is not done. |
| "Worked on" | An issue named in the PR title or in the `## Issues` section, and a closed-then-reopened one. |
| "Reported" thanks | The author of each issue in "Done" or "Worked on". |
| "Code" thanks | The PR authors. |
| "Tested and helped" thanks | The @handles in the PR body's `## Thanks` section. |

The script does not thank a shared or automated account. `rancur` is
shared by several agents and says nothing about who did the work. Name
the people in the `## Thanks` section instead.

## 7. Traps

- **A closing keyword closes an issue even when the sentence denies it.**
  GitHub reads `does not fix #117` as `fix #117`. The notes never use
  close, fix or resolve beside a number. Write "part of #N" in a PR body
  for an issue that must stay open.
- **A link from a PR to an issue is not proof that the issue is done.**
  PR #226 still links to #117, and #117 was reopened. The script reads
  the issue's state when it drafts.
- **An @handle in a release notifies that person.** That is the purpose.
  Read the draft before you publish.
