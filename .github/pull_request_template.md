<!--
Fill in every section. tools/release.py reads "Release notes", "Issues"
and "Thanks" from this body when it drafts the next release.
See docs/RELEASING.md.
-->

## Summary

<!-- What changed and why. -->

## Basis

<!--
AGENTS.md §3A.2. For each new number, threshold, weight, floor or score:
the number, and its source (firmware file and line at a tag, protobuf
field, published document, or the docs/DECISIONS.md entry with the query
and its result). Or write "No new numbers."
-->

## Red evidence

<!--
AGENTS.md §3A.5. The new tests, and their failing output on `main` before
this change. For a bug fix, the test that reproduces the bug. Or the
reason no test applies (documentation only, layout with screenshots).
-->

## Release notes

<!--
One to three lines for the people who use Sonoran, not for developers.
Say what they will see. Leave empty for a change nobody will notice.
-->

## Issues

<!--
Closes #N      — only when this PR finishes the issue. Merging closes it.
Part of #N     — work towards an issue that stays open.

GitHub closes an issue for "close", "fix" or "resolve" in ANY form next to
its number, even inside "this does not fix #N". Use "part of #N" for every
issue this PR must not close.
-->

## Thanks

<!--
@handles of people who reported, tested or helped, who are not the PR
author. They are thanked by name in the release.
-->

## Checklist

- [ ] `ruff check`, `ruff format`, `mypy` and `pytest` pass locally (docs/QA.md)
- [ ] The matching doc in `docs/` is updated
- [ ] "Release notes" and "Issues" above are filled in
- [ ] "Basis" and "Red evidence" above are filled in (AGENTS.md §3A)
- [ ] No tool or model credit and no agent session link anywhere in this PR or its commits (§3A.4)
