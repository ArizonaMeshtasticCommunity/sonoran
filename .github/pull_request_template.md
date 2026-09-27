<!--
Fill in every section. tools/release.py reads "Release notes", "Issues"
and "Thanks" from this body when it drafts the next release.
See docs/RELEASING.md.
-->

## Summary

<!-- What changed and why. -->

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
