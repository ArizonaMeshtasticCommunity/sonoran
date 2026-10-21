"""Check that the words a newcomer may not know carry their explanation.

The rule is in AGENTS.md section 3B and docs/NEWCOMER.md. The words and
their explanations are in `src/sonoran/web/static/glossary.js`. The test
`tests/unit/test_newcomer_glossary.py` runs these checks with pytest, so
there is no extra CI job.

What it scans, and what it cannot see (docs/NEWCOMER.md section 6):

- `index.html` and `embed-coverage.html`: every text node and every
  `<option>`, with comments, `<script>`, `<style>`, `<template>`,
  `<svg>`, `<code>` and `.sr-only` text left out. Attributes such as
  `placeholder` and `aria-label` are not read.
- The interface scripts: a quoted string given to `label:` or `text:`,
  and the last quoted argument of `el('h3', {...}, '...')` for a
  heading, a table heading, a term, a legend, a label, a summary, a
  button, a paragraph, a span, a list item or a strong. Template strings
  (`${...}`) and strings built at run time are not read.
- A text is covered when the element that holds it, or a parent up to
  the nearest block such as a `div` or a `section`, has `data-term` with
  the term id. In a script, the object literal that holds the string
  must have `term: 'id'` or `'data-term': 'id'`.

Run it by hand:

    uv run python -m tools.newcomer_check               # report
    uv run python -m tools.newcomer_check --write-doc   # rebuild docs/GLOSSARY.md
    uv run python -m tools.newcomer_check --prune       # drop fixed baseline lines

`--prune` only removes lines. A baseline cannot grow without
`--write-baseline --allow-growth`, and a pull request that uses it must
say why, for a maintainer to agree to (docs/NEWCOMER.md section 6.3).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
GLOSSARY_JS = STATIC / "glossary.js"
GLOSSARY_DOC = ROOT / "docs" / "GLOSSARY.md"
BASELINE = ROOT / "tests" / "unit" / "newcomer_baseline.json"

HTML_FILES = ("index.html", "embed-coverage.html")
# Generated code, protocol code and workers draw no words of their own.
JS_SKIP = {
    "glossary.js",
    # The name tables. Whatever draws a name carries its term.
    "labels.js",
    "meshtastic-static.js",
    "meshtastic-serial-proto.js",
    "protobuf-runtime.js",
    "serial-frames.js",
    "serial-read.js",
    "serial-write.js",
    "planner.worker.js",
    "sw.js",
}

# The pseudo-term for an internal name such as ROUTER_LATE in primary text.
ENUM_RULE = "internal-name"
ENUM = re.compile(r"(?<![\w-])[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+(?![\w-])")

ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
MORE_OK = ("https://meshtastic.org/", "https://github.com/meshtastic/")
PLAIN_MAX = 320
SENTENCES_MAX = 3


@dataclass(frozen=True, order=True)
class Finding:
    """One place that uses a glossary word with no explanation."""

    file: str
    term: str
    text: str


# --------------------------------------------------------------------------
# The glossary


def load_glossary() -> dict[str, dict]:
    """The terms of glossary.js, read by running the file under node."""
    node = shutil.which("node")
    assert node, (
        "node is not on PATH, so the glossary was not read. It is not optional: "
        "the e2e suite needs node already, and a skip here looks like a pass."
    )
    script = (
        "const vm = require('vm'); const fs = require('fs');"
        "const box = { window: {} }; vm.createContext(box);"
        "vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), box);"
        "const g = box.window.SonoranGlossary;"
        "if (!g || !Object.isFrozen(g.terms)) { console.error('not frozen'); process.exit(3); }"
        "process.stdout.write(JSON.stringify(g.terms));"
    )
    if not GLOSSARY_JS.exists():
        return {}
    out = subprocess.run(
        [node, "-e", script, str(GLOSSARY_JS)], capture_output=True, text=True, timeout=30
    )
    assert out.returncode == 0, f"glossary.js did not load: {out.stderr.strip()}"
    terms: dict[str, dict] = json.loads(out.stdout)
    return terms


def entry_problems(glossary: dict[str, dict]) -> list[str]:
    """What is wrong with each entry, in words an author can act on."""
    problems = []
    for term, entry in glossary.items():
        if not ID.match(term):
            problems.append(f"{term}: the id must be lower case words joined by '-'")
        if not str(entry.get("label", "")).strip():
            problems.append(f"{term}: no label")
        plain = str(entry.get("plain", "")).strip()
        if not plain:
            problems.append(f"{term}: no plain explanation")
        else:
            sentences = len(re.findall(r"[.!?](?:\s|$)", plain))
            if len(plain) > PLAIN_MAX or sentences > SENTENCES_MAX:
                problems.append(
                    f"{term}: the explanation is {len(plain)} characters and "
                    f"{sentences} sentences; keep it to {SENTENCES_MAX} sentences "
                    f"and {PLAIN_MAX} characters, and put the rest behind 'more'"
                )
        more = entry.get("more")
        if more and not str(more).startswith(MORE_OK):
            problems.append(
                f"{term}: the learn-more link must point at meshtastic.org "
                "or the Meshtastic GitHub, never another site"
            )
        words = entry.get("words", [])
        if not isinstance(words, list) or not all(isinstance(w, str) and w for w in words):
            problems.append(f"{term}: 'words' must be a list of spellings")
    return problems


def _word_patterns(glossary: dict[str, dict]) -> list[tuple[str, re.Pattern[str]]]:
    patterns = []
    for term, entry in glossary.items():
        for word in entry.get("words", []):
            # A plural is the same word to a reader.
            body = re.escape(word) + ("s?" if word[-1].isalpha() else "")
            patterns.append((term, re.compile(rf"(?<![\w-]){body}(?![\w-])", re.IGNORECASE)))
    return patterns


def _terms_in(text: str, patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    found = []
    for term, pattern in patterns:
        if term not in found and pattern.search(text):
            found.append(term)
    if ENUM.search(text):
        found.append(ENUM_RULE)
    return found


# --------------------------------------------------------------------------
# index.html

# Text inside these is never on the screen, or is code on purpose.
_SKIP_TAGS = {"script", "style", "template", "svg", "code", "noscript", "head"}
# A data-term this far up does not explain the text: stop the walk here.
_BLOCKS = {
    "div", "section", "fieldset", "form", "ul", "ol", "dl", "table", "tbody",
    "thead", "tr", "nav", "header", "footer", "main", "aside", "details",
    "article", "body", "html",
}  # fmt: skip
_VOID = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "source", "track", "wbr",
}  # fmt: skip


class _Scanner(HTMLParser):
    def __init__(self, name: str, patterns: list[tuple[str, re.Pattern[str]]]) -> None:
        super().__init__(convert_charrefs=True)
        self.name = name
        self.patterns = patterns
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.findings: list[Finding] = []
        self.term_ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("data-term"):
            self.term_ids.extend(values["data-term"].split())
        if tag in _VOID:
            return
        self.stack.append((tag, values))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("data-term"):
            self.term_ids.extend(values["data-term"].split())

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def _hidden(self) -> bool:
        for tag, attrs in self.stack:
            if tag in _SKIP_TAGS or "sr-only" in attrs.get("class", "").split():
                return True
        return False

    def _covered(self, term: str) -> bool:
        for tag, attrs in reversed(self.stack):
            if term in attrs.get("data-term", "").split():
                return True
            if tag in _BLOCKS:
                return False
        return False

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text or self._hidden():
            return
        for term in _terms_in(text, self.patterns):
            if term == ENUM_RULE or not self._covered(term):
                self.findings.append(Finding(self.name, term, text))


def scan_html(name: str, text: str, glossary: dict[str, dict]) -> list[Finding]:
    scanner = _Scanner(name, _word_patterns(glossary))
    scanner.feed(text)
    scanner.close()
    return scanner.findings


def html_term_ids(text: str) -> list[str]:
    scanner = _Scanner("", [])
    scanner.feed(text)
    return scanner.term_ids


# --------------------------------------------------------------------------
# The interface scripts


def _mask(source: str) -> str:
    """The source with strings, templates and comments blanked out.

    The length and the line breaks stay the same, so a position in the
    mask is the same position in the source. Braces left in the mask
    are code, which is what the object finder needs.
    """
    out = list(source)
    i, n = 0, len(source)
    last = ""  # the last code character, to tell a regex from a division

    def blank(a: int, b: int) -> None:
        for k in range(a, min(b, n)):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = source[i]
        if source.startswith("//", i):
            j = source.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif source.startswith("/*", i):
            j = source.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
        elif c in "'\"`":
            j = i + 1
            while j < n and source[j] != c:
                j += 2 if source[j] == "\\" else 1
            blank(i + 1, j)
            i = j + 1
            last = c
        elif c == "/" and (last in "(,=:[!&|?{};+-*%<>~^" or last == ""):
            j = i + 1
            in_class = False
            while j < n and source[j] != "\n":
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == "[":
                    in_class = True
                elif source[j] == "]":
                    in_class = False
                elif source[j] == "/" and not in_class:
                    break
                j += 1
            blank(i + 1, j)
            i = j + 1
            last = "/"
        else:
            if not c.isspace():
                last = c
            i += 1
    return "".join(out)


def _enclosing_object(mask: str, at: int) -> tuple[int, int]:
    depth = 0
    start = at
    while start > 0:
        start -= 1
        if mask[start] == "}":
            depth += 1
        elif mask[start] == "{":
            if depth == 0:
                break
            depth -= 1
    depth = 0
    end = at
    while end < len(mask):
        if mask[end] == "{":
            depth += 1
        elif mask[end] == "}":
            if depth == 0:
                break
            depth -= 1
        end += 1
    return start, end + 1


_STRING = r"'((?:[^'\\\n]|\\.)*)'|\"((?:[^\"\\\n]|\\.)*)\""
_KEYED = re.compile(rf"\b(?:label|text)\s*:\s*(?:{_STRING})")
_HEADING = re.compile(
    r"\bel\(\s*'(?:h[1-6]|th|dt|legend|label|summary|button|p|span|li|strong)'\s*,\s*"
    rf"(\{{[^{{}}]*\}})\s*,\s*(?:{_STRING})\s*[,)]"
)
_TERM_REF = re.compile(r"(?:\bterm|'data-term'|\"data-term\")\s*:\s*['\"]([^'\"]*)['\"]")


def _unescape(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def scan_js(name: str, source: str, glossary: dict[str, dict]) -> list[Finding]:
    patterns = _word_patterns(glossary)
    mask = _mask(source)
    findings = []

    def check(text: str, scope: str) -> None:
        refs = {ref for match in _TERM_REF.finditer(scope) for ref in match.group(1).split()}
        for term in _terms_in(text, patterns):
            if term == ENUM_RULE or term not in refs:
                findings.append(Finding(name, term, " ".join(text.split())))

    for match in _KEYED.finditer(source):
        if mask[match.start()] == " ":
            continue  # inside a comment or a string
        text = _unescape(match.group(1) if match.group(1) is not None else match.group(2))
        start, end = _enclosing_object(mask, match.start())
        check(text, source[start:end])
    for match in _HEADING.finditer(source):
        if mask[match.start()] == " ":
            continue
        text = _unescape(match.group(2) if match.group(2) is not None else match.group(3))
        check(text, match.group(1))
    return findings


def js_term_ids(source: str) -> list[str]:
    mask = _mask(source)
    ids: list[str] = []
    for match in _TERM_REF.finditer(source):
        if mask[match.start()] != " ":
            ids.extend(match.group(1).split())
    return ids


def _js_files() -> list[Path]:
    return sorted(path for path in STATIC.glob("*.js") if path.name not in JS_SKIP)


# --------------------------------------------------------------------------
# All of it


def scan_all(glossary: dict[str, dict]) -> list[Finding]:
    findings = []
    for name in HTML_FILES:
        findings += scan_html(name, (STATIC / name).read_text(encoding="utf-8"), glossary)
    for path in _js_files():
        findings += scan_js(path.name, path.read_text(encoding="utf-8"), glossary)
    return sorted(findings)


def unknown_terms(glossary: dict[str, dict]) -> list[tuple[str, str]]:
    unknown = []
    for name in HTML_FILES:
        for term in html_term_ids((STATIC / name).read_text(encoding="utf-8")):
            if term not in glossary:
                unknown.append((name, term))
    for path in _js_files():
        for term in js_term_ids(path.read_text(encoding="utf-8")):
            if term not in glossary:
                unknown.append((path.name, term))
    return unknown


def read_baseline() -> list[Finding]:
    if not BASELINE.exists():
        return []
    return [Finding(**row) for row in json.loads(BASELINE.read_text(encoding="utf-8"))]


def write_baseline(findings: list[Finding]) -> None:
    # One finding a line, so a pull request's diff shows each one.
    rows = [json.dumps(asdict(f), ensure_ascii=False) for f in sorted(findings)]
    BASELINE.write_text("[\n" + ",\n".join(rows) + "\n]\n", encoding="utf-8")


def compare(found: list[Finding], baseline: list[Finding]) -> tuple[list[Finding], list[Finding]]:
    """(new, stale): what the baseline does not allow, and what it lists for nothing."""
    have, allowed = Counter(found), Counter(baseline)
    new = sorted((have - allowed).elements())
    stale = sorted((allowed - have).elements())
    return new, stale


def explain_new(new: list[Finding]) -> str:
    lines = [
        f"{len(new)} new place(s) show a word a Meshtastic newcomer may not know, "
        "with no explanation (AGENTS.md 3B, docs/NEWCOMER.md):",
    ]
    for finding in new:
        if finding.term == ENUM_RULE:
            lines.append(
                f'  {finding.file}: "{finding.text}" shows an internal name. Show a plain '
                "name (labels.js has them) and keep the exact value in the tooltip."
            )
        else:
            lines.append(
                f"  {finding.file}: \"{finding.text}\" uses '{finding.term}'. Put "
                f'data-term="{finding.term}" on the element that holds this text, or '
                f"term: '{finding.term}' on its column, field or object."
            )
    lines.append(
        "The explanation itself comes from src/sonoran/web/static/glossary.js. Add the "
        "word there first if it is missing, then run "
        "`uv run python -m tools.newcomer_check --write-doc`."
    )
    return "\n".join(lines)


def explain_stale(stale: list[Finding]) -> str:
    lines = [
        f"{len(stale)} baseline line(s) no longer happen. Good: the baseline must shrink "
        "with them. Run `uv run python -m tools.newcomer_check --prune`. These are:",
    ]
    lines += [f'  {f.file}: "{f.text}" ({f.term})' for f in stale]
    return "\n".join(lines)


def glossary_markdown(glossary: dict[str, dict]) -> str:
    lines = [
        "# GLOSSARY.md — The words Sonoran explains",
        "",
        "This file is made from `src/sonoran/web/static/glossary.js`. Do not",
        "edit it by hand. Change the glossary, then run:",
        "",
        "    uv run python -m tools.newcomer_check --write-doc",
        "",
        "Each word below has a tooltip in the dashboard. An element with",
        '`data-term="<id>"` shows it. See `docs/NEWCOMER.md` for when to use one.',
        "",
        "| Id | Word | What it means |",
        "|---|---|---|",
    ]
    for term, entry in glossary.items():
        plain = " ".join(str(entry["plain"]).split()).replace("|", "\\|")
        more = f" [Learn more]({entry['more']})" if entry.get("more") else ""
        lines.append(f"| `{term}` | {entry['label']} | {plain}{more} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write-doc", action="store_true", help="rebuild docs/GLOSSARY.md")
    parser.add_argument("--prune", action="store_true", help="drop baseline lines now fixed")
    parser.add_argument("--write-baseline", action="store_true")
    parser.add_argument("--allow-growth", action="store_true")
    args = parser.parse_args(argv)
    glossary = load_glossary()
    if args.write_doc:
        GLOSSARY_DOC.write_text(glossary_markdown(glossary), encoding="utf-8")
        print(f"wrote {GLOSSARY_DOC.relative_to(ROOT)} ({len(glossary)} terms)")
    findings = scan_all(glossary)
    baseline = read_baseline()
    new, stale = compare(findings, baseline)
    if args.write_baseline:
        if new and not args.allow_growth:
            print(explain_new(new))
            print("\nThe baseline only shrinks. Fix these, or see docs/NEWCOMER.md 6.3.")
            return 1
        write_baseline(findings)
        print(f"wrote {BASELINE.relative_to(ROOT)} ({len(findings)} lines)")
        return 0
    if args.prune:
        kept = list((Counter(baseline) - Counter(stale)).elements())
        write_baseline(kept)
        print(f"pruned {len(stale)} line(s); {len(kept)} left")
        stale = []
    problems = entry_problems(glossary)
    for line in problems:
        print(line)
    if new:
        print(explain_new(new))
    if stale:
        print(explain_stale(stale))
    print(
        f"{len(glossary)} terms, {len(findings)} places without a tooltip, "
        f"{len(new)} new, {len(stale)} stale"
    )
    return 1 if new or stale or problems else 0


if __name__ == "__main__":
    sys.exit(main())
