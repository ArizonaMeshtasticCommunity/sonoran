"""Draft and publish a Sonoran release from the pull requests merged since the last one.

See docs/RELEASING.md for the process. In short:

    python tools/release.py draft               # print the notes, change nothing
    python tools/release.py draft --since REF   # first release: no tag exists yet
    python tools/release.py publish             # create the tag and the GitHub release
    python tools/release.py check               # exit 1 if merged work is not released
    python tools/release.py changelog           # rewrite CHANGELOG.md from the releases

`draft` is the default and it is read-only. Only `publish` writes to GitHub,
and it writes a tag and a release, never a commit. A tag does not match the
`branches: [main]` filter in ci.yml, so a release starts no CI run.

The script reads GitHub through the `gh` CLI. It needs nothing else.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# The mesh is in Arizona, so a release is named for the date there.
# Arizona keeps no daylight saving time, so the date never jumps.
RELEASE_ZONE = ZoneInfo("America/Phoenix")

# Accounts that are not a person to thank. `rancur` is a shared identity that
# several agents use. It says nothing about who did the work, so the PR's own
# "Thanks" section names the people instead.
SKIP_LOGINS = frozenset({"rancur", "github-actions", "github-actions[bot]", "dependabot[bot]"})

# Section order in the notes. The first match wins.
CATEGORIES = (
    ("security", "Security"),
    ("feat", "New features"),
    ("fix", "Fixes"),
    ("perf", "Fixes"),
    ("docs", "Documentation"),
    ("test", "Maintenance"),
    ("refactor", "Maintenance"),
    ("chore", "Maintenance"),
    ("ci", "Maintenance"),
    ("build", "Maintenance"),
)
SECTION_ORDER = ("Security", "New features", "Fixes", "Documentation", "Maintenance", "Other")
LABEL_SECTIONS = {"security": "Security", "bug": "Fixes", "enhancement": "New features"}

TAG_PATTERN = re.compile(r"^v(\d{4})\.(\d{2})\.(\d{2})(?:\.(\d+))?$")
PREFIX_PATTERN = re.compile(r"^(\w+)(?:\([^)]*\))?!?:\s*")
ISSUE_REF = re.compile(r"(?<![\w/])#(\d+)\b")
HANDLE = re.compile(r"(?<![\w/])@([A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))\b")
PR_SECTION = re.compile(r"^#{2,3}\s*(.+?)\s*$", re.MULTILINE)


@dataclass
class Issue:
    number: int
    title: str
    author: str
    is_open: bool = False


@dataclass
class PullRequest:
    number: int
    title: str
    author: str
    body: str = ""
    labels: list[str] = field(default_factory=list)
    closes: list[int] = field(default_factory=list)
    merge_sha: str = ""


# ---------------------------------------------------------------- pure logic


def next_tag(existing: list[str], today: datetime) -> str:
    """Return the tag for a release made on `today`.

    The first release of a day is `vYYYY.MM.DD`. A second one on the same
    day is `vYYYY.MM.DD.2`, then `.3`, and so on.
    """
    base = f"v{today:%Y.%m.%d}"
    taken = {
        1 if m.group(4) is None else int(m.group(4))
        for t in existing
        if (m := TAG_PATTERN.match(t)) and t.split(".")[:3] == base.split(".")
    }
    if not taken:
        return base
    return f"{base}.{max(taken) + 1}"


def latest_tag(existing: list[str]) -> str | None:
    """Return the newest release tag, or None when there is none."""

    def key(tag: str) -> tuple[int, ...]:
        m = TAG_PATTERN.match(tag)
        assert m is not None
        return (int(m[1]), int(m[2]), int(m[3]), int(m[4] or 1))

    tags = [t for t in existing if TAG_PATTERN.match(t)]
    return max(tags, key=key) if tags else None


def section_of(pr: PullRequest) -> str:
    """Put a pull request in one section of the notes."""
    for label in pr.labels:
        if label in LABEL_SECTIONS and LABEL_SECTIONS[label] == "Security":
            return "Security"
    match = PREFIX_PATTERN.match(pr.title)
    if match:
        for prefix, section in CATEGORIES:
            if match.group(1).lower() == prefix:
                return section
    for label in pr.labels:
        if label in LABEL_SECTIONS:
            return LABEL_SECTIONS[label]
    return "Other"


def clean_title(title: str) -> str:
    """Remove the conventional commit prefix. The section already says it."""
    stripped = PREFIX_PATTERN.sub("", title, count=1)
    return stripped[:1].upper() + stripped[1:]


def pr_section(body: str, name: str) -> str:
    """Return the text under a `## name` heading of a PR body, or ""."""
    headings = list(PR_SECTION.finditer(body or ""))
    for i, heading in enumerate(headings):
        if heading.group(1).strip().lower() == name.lower():
            end = headings[i + 1].start() if i + 1 < len(headings) else len(body)
            text = body[heading.end() : end]
            text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
            return text.strip()
    return ""


def referenced_numbers(pr: PullRequest) -> list[int]:
    """Every `#N` in the title and the body's "Issues" section, in order.

    The rest of a body is not read: it mentions old issues in passing, and
    naming those in a release would tell their reporters something moved.
    """
    seen: list[int] = []
    for text in (pr.title, pr_section(pr.body, "Issues")):
        for match in ISSUE_REF.finditer(text or ""):
            n = int(match.group(1))
            if n != pr.number and n not in seen:
                seen.append(n)
    return seen


def thanked_handles(pr: PullRequest) -> list[str]:
    """The @handles in the PR's "Thanks" section."""
    return list(dict.fromkeys(HANDLE.findall(pr_section(pr.body, "Thanks"))))


def credit(login: str) -> bool:
    return bool(login) and login not in SKIP_LOGINS and not login.endswith("[bot]")


def render_notes(
    tag: str,
    previous: str | None,
    prs: list[PullRequest],
    issues: dict[int, Issue],
    repo: str,
) -> str:
    """Build the release notes as Markdown.

    The notes never use a GitHub closing keyword (close, fix, resolve, in any
    form) next to an issue number. A release body closes nothing, but these
    notes get pasted into PR bodies and CHANGELOG commits, and there the
    keyword parser closes the issue even when the sentence says it must not.
    """
    lines: list[str] = []
    # A link to an issue is a claim. The issue's state now is the fact: an
    # issue that a merge closed and a person then reopened is not done.
    closed = [n for pr in prs for n in pr.closes if n in issues and not issues[n].is_open]
    lines.append(
        f"{len(prs)} pull request{'s' if len(prs) != 1 else ''} merged"
        + (
            f", {len(set(closed))} issue{'s' if len(set(closed)) != 1 else ''} closed."
            if closed
            else "."
        )
    )
    lines.append("")

    grouped: dict[str, list[PullRequest]] = {}
    for pr in prs:
        grouped.setdefault(section_of(pr), []).append(pr)
    for section in SECTION_ORDER:
        if section not in grouped:
            continue
        lines.append(f"### {section}")
        lines.append("")
        for pr in sorted(grouped[section], key=lambda p: p.number):
            entry = f"- {clean_title(pr.title)} (#{pr.number})"
            if credit(pr.author):
                entry += f" by @{pr.author}"
            if pr.closes:
                done = [n for n in pr.closes if n in closed]
                if done:
                    entry += " — done: " + ", ".join(f"#{n}" for n in done)
            lines.append(entry)
            note = pr_section(pr.body, "Release notes")
            if note:
                for note_line in note.splitlines():
                    lines.append(f"  {note_line}" if note_line.strip() else "")
        lines.append("")

    related = [
        n
        for pr in prs
        for n in pr.closes + referenced_numbers(pr)
        if n in issues and n not in closed
    ]
    if closed or related:
        lines.append("### Issues")
        lines.append("")
        for n in dict.fromkeys(closed):
            lines.append(f"- Done: #{n} {issues[n].title}{_reporter(issues[n])}")
        for n in dict.fromkeys(related):
            lines.append(f"- Worked on: #{n} {issues[n].title}{_reporter(issues[n])}")
        lines.append("")

    reporters = [issues[n].author for n in dict.fromkeys(closed + related)]
    authors = [pr.author for pr in prs]
    helpers = [h for pr in prs for h in thanked_handles(pr)]
    thanks = [
        (label, [h for h in dict.fromkeys(group) if credit(h)])
        for label, group in (
            ("Reported", reporters),
            ("Code", authors),
            ("Tested and helped", helpers),
        )
    ]
    thanks = [(label, group) for label, group in thanks if group]
    if thanks:
        lines.append("### Thank you")
        lines.append("")
        for label, group in thanks:
            lines.append(f"- {label}: " + ", ".join(f"@{h}" for h in group))
        lines.append("")

    if previous:
        lines.append(f"**Full changes:** https://github.com/{repo}/compare/{previous}...{tag}")
    return "\n".join(lines).rstrip() + "\n"


def _reporter(issue: Issue) -> str:
    return f" (reported by @{issue.author})" if credit(issue.author) else ""


def render_changelog(releases: list[dict[str, str]]) -> str:
    """Build CHANGELOG.md from the published releases, newest first."""
    out = [
        "# Changelog",
        "",
        "Every release of Sonoran, newest first.",
        "The GitHub Releases page is the source of this file.",
        "Do not edit it by hand. Run `python tools/release.py changelog`.",
        "See `docs/RELEASING.md`.",
        "",
    ]
    for release in releases:
        # The tag is named for the Arizona date (`RELEASE_ZONE`), so the
        # heading must be too. `publishedAt` is UTC, and a release published
        # in the Arizona evening is already tomorrow in UTC: the first one,
        # v2026.09.26, printed as "2026-09-27" under its own name.
        published = datetime.fromisoformat(release["publishedAt"].replace("Z", "+00:00"))
        date = published.astimezone(RELEASE_ZONE).date().isoformat()
        out.append(f"## {release['tagName']} — {date}")
        out.append("")
        body = release["body"].replace("\r\n", "\n").strip()
        # Keep the file's own headings at level two.
        body = re.sub(r"^### ", "#### ", body, flags=re.MULTILINE)
        out.append(body)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------- GitHub and git


def run(*cmd: str) -> str:
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def gh_json(*args: str) -> object:
    return json.loads(run("gh", *args))


def repo_name() -> str:
    data = gh_json("repo", "view", "--json", "nameWithOwner")
    assert isinstance(data, dict)
    return str(data["nameWithOwner"])


def tags() -> list[str]:
    run("git", "fetch", "--quiet", "--tags", "origin")
    return run("git", "tag", "--list", "v*").split()


def is_ancestor(commit: str, of: str) -> bool:
    return (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, of], capture_output=True
        ).returncode
        == 0
    )


def merged_since(since: str, target: str) -> list[PullRequest]:
    """PRs whose merge commit is in `target` and not in `since`."""
    date = run("git", "log", "-1", "--format=%cs", since).strip()
    raw = gh_json(
        "pr",
        "list",
        "--state",
        "merged",
        "--limit",
        "500",
        "--search",
        f"merged:>={date}",
        "--json",
        "number,title,author,body,labels,closingIssuesReferences,mergeCommit",
    )
    assert isinstance(raw, list)
    prs = []
    for item in raw:
        sha = (item.get("mergeCommit") or {}).get("oid", "")
        if not sha or not is_ancestor(sha, target) or is_ancestor(sha, since):
            continue
        prs.append(
            PullRequest(
                number=item["number"],
                title=item["title"],
                author=(item.get("author") or {}).get("login", ""),
                body=item.get("body") or "",
                labels=[label["name"] for label in item.get("labels", [])],
                closes=[ref["number"] for ref in item.get("closingIssuesReferences", [])],
                merge_sha=sha,
            )
        )
    return sorted(prs, key=lambda p: p.number)


def fetch_issues(repo: str, numbers: list[int]) -> dict[int, Issue]:
    """Look up each number. A pull request is not an issue and is dropped."""
    found: dict[int, Issue] = {}
    for n in dict.fromkeys(numbers):
        try:
            data = gh_json("api", f"repos/{repo}/issues/{n}")
        except subprocess.CalledProcessError:
            continue
        assert isinstance(data, dict)
        if "pull_request" in data:
            continue
        found[n] = Issue(
            n,
            data["title"],
            (data.get("user") or {}).get("login", ""),
            is_open=data.get("state") == "open",
        )
    return found


def build(args: argparse.Namespace) -> tuple[str, str | None, str, str]:
    """Return (tag, previous tag or ref, target sha, notes)."""
    existing = tags()
    previous = latest_tag(existing)
    since = args.since or previous
    if since is None:
        sys.exit("No release tag exists yet. Name the start with --since REF.")
    target = run("git", "rev-parse", args.target).strip()
    repo = repo_name()
    prs = merged_since(since, target)
    numbers = [n for pr in prs for n in pr.closes + referenced_numbers(pr)]
    issues = fetch_issues(repo, numbers)
    tag = args.tag or next_tag(existing, datetime.now(RELEASE_ZONE))
    return tag, previous, target, render_notes(tag, previous, prs, issues, repo)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "command", nargs="?", default="draft", choices=("draft", "publish", "check", "changelog")
    )
    parser.add_argument("--since", help="start ref; defaults to the latest release tag")
    parser.add_argument("--target", default="origin/main", help="end ref (default origin/main)")
    parser.add_argument("--tag", help="override the computed tag name")
    parser.add_argument("--output", type=Path, help="also write the notes to this file")
    args = parser.parse_args(argv)

    if args.command == "changelog":
        releases = gh_json(
            "release", "list", "--limit", "1000", "--json", "tagName,publishedAt,isDraft"
        )
        assert isinstance(releases, list)
        full = []
        for rel in releases:
            if rel["isDraft"]:
                continue
            body = gh_json("release", "view", rel["tagName"], "--json", "body")
            assert isinstance(body, dict)
            full.append({**rel, "body": body["body"]})
        Path("CHANGELOG.md").write_text(render_changelog(full))
        print(f"CHANGELOG.md: {len(full)} releases")
        return 0

    if args.command == "check":
        run("git", "fetch", "--quiet", "origin")
        previous = latest_tag(tags())
        if previous is None:
            print("No release exists yet. Cut the first one with --since.")
            return 1
        pending = merged_since(previous, run("git", "rev-parse", args.target).strip())
        if pending:
            print(f"{len(pending)} merged PR(s) are not in a release since {previous}:")
            for pr in pending:
                print(f"  #{pr.number} {pr.title}")
            return 1
        print(f"Everything merged is released ({previous}).")
        return 0

    tag, previous, target, notes = build(args)
    if args.output:
        args.output.write_text(notes)
    if args.command == "draft":
        print(f"# DRY RUN: would publish {tag} at {target[:7]} (since {args.since or previous})\n")
        print(notes)
        return 0

    if tag in tags():
        sys.exit(f"{tag} already exists. Nothing was published.")
    notes_file = Path(".git") / "RELEASE_NOTES.md"
    notes_file.write_text(notes)
    run(
        "gh",
        "release",
        "create",
        tag,
        "--target",
        target,
        "--title",
        tag,
        "--notes-file",
        str(notes_file),
    )
    print(f"Published {tag}. Now run `python tools/release.py changelog` in your next PR.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
