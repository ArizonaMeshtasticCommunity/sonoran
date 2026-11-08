"""A node's name is chosen by whoever owns the radio, so it is never HTML.

Two libraries this dashboard ships take tooltip content as a string and
set `innerHTML` with it:

- Leaflet 1.9.4 `_updateContent`: ``if ("string" == typeof e) t.innerHTML = e``
- ECharts 5.5.1 tooltip:          ``if (U(t)) o.innerHTML = t + a``

Both were being handed a template literal with a node's `display_name`
interpolated into it, so a node named ``<img src=x onerror=...>`` ran
script on this origin. That origin is not a cheap one to lose: the
Config check page holds Web Serial, so script here can reach a radio
plugged into the reader's machine.

The fix is to hand those libraries a DOM node instead, built so every
value lands through `textContent`. These tests hold that line. They are
source checks rather than behaviour checks because the behaviour lives
in a browser, and a source check is what stops the *next* tooltip from
reintroducing the shape.

Both assertions were watched failing against the code before the fix.
"""

import re
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"

# The files we write. `vendor/` is somebody else's code and is checked
# by reading it, not by editing it.
OURS = sorted(p for p in STATIC.glob("*.js"))


def _strip_comments(source: str) -> str:
    """Drop block and line comments so prose about a trap is not a hit."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", source)


@pytest.mark.parametrize("path", OURS, ids=lambda p: p.name)
def test_bind_tooltip_is_never_handed_a_template_literal(path: Path) -> None:
    """`bindTooltip` with a backtick string is an innerHTML sink.

    Leaflet renders a string as HTML. Passing an element is the whole
    fix, so the argument must not start a template literal.
    """
    source = _strip_comments(path.read_text())
    offenders = re.findall(r"bindTooltip\(\s*`[^`]*`", source)
    assert not offenders, (
        f"{path.name}: bindTooltip is given a template literal "
        f"{offenders!r}. Leaflet sets innerHTML from a string, and these "
        f"strings carry a node name. Build the tooltip as an element."
    )


# ---------------------------------------------------------------------------
# Chart formatters.
#
# The first version of this check looked for `return` followed by a
# template literal. An arrow function's implicit return has no `return`
# keyword, so `formatter: (p) => `<b>${p.name}</b>`` went straight past
# it, and the dashboard's packet-type tooltip was that shape (#249).
#
# Another regex would move the blind spot rather than remove it. So the
# check below reads each formatter's whole value, whatever shape it has,
# with a small scanner that knows where JavaScript strings, template
# literals, comments and regular expressions start and end. It then holds
# three things:
#
# 1. No formatter holds markup in a literal, returned or not.
# 2. A tooltip `formatter` hands back `tooltipLines(...)` on every path.
#    That helper builds an element and puts each value in as text, so
#    escaping happens once, in one place.
# 3. The formatters on the site are counted, so a new chart cannot add
#    one that this sweep does not know about.
# ---------------------------------------------------------------------------

# Characters after which a `/` starts a regular expression, not a division.
_REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_AFTER_WORDS = {
    "return",
    "typeof",
    "case",
    "do",
    "else",
    "in",
    "of",
    "new",
    "delete",
    "void",
    "throw",
    "yield",
    "await",
}


class _Scan:
    """Blank every literal and comment out of a JavaScript source.

    `code` keeps the length of the source, so an offset in one is an
    offset in the other. Inside it, strings, template text, regular
    expressions and comments are spaces, which makes bracket counting on
    `code` safe. `literals` keeps the text of each string and of each
    static part of a template literal, with its offset.
    """

    def __init__(self, source: str) -> None:
        self.src = source
        self.out = list(source)
        self.literals: list[tuple[int, str]] = []
        end = self._code(0, closing=False)
        assert end == len(source), f"scanner stopped early at offset {end}"
        self.code = "".join(self.out)

    def _blank(self, start: int, end: int) -> None:
        for k in range(start, end):
            if self.out[k] != "\n":
                self.out[k] = " "

    def _regex_allowed(self, i: int) -> bool:
        k = i - 1
        while k >= 0 and self.src[k].isspace():
            k -= 1
        if k < 0 or self.src[k] in _REGEX_AFTER:
            return True
        word = re.search(r"[A-Za-z_$][\w$]*$", self.src[: k + 1])
        return bool(word and word.group(0) in _REGEX_AFTER_WORDS)

    def _code(self, i: int, *, closing: bool) -> int:
        """Scan code from `i`. With `closing`, stop after the `}` of a `${`."""
        src, n, depth = self.src, len(self.src), 0
        while i < n:
            c = src[i]
            two = src[i : i + 2]
            if two == "//":
                j = src.find("\n", i)
                j = n if j < 0 else j
                self._blank(i, j)
                i = j
            elif two == "/*":
                j = src.index("*/", i + 2) + 2
                self._blank(i, j)
                i = j
            elif c in "'\"":
                j = i + 1
                while src[j] != c:
                    j += 2 if src[j] == "\\" else 1
                self.literals.append((i, src[i + 1 : j]))
                self._blank(i + 1, j)
                i = j + 1
            elif c == "`":
                i = self._template(i + 1)
            elif c == "/" and self._regex_allowed(i):
                j, in_class = i + 1, False
                while in_class or src[j] != "/":
                    if src[j] == "\\":
                        j += 1
                    elif src[j] == "[":
                        in_class = True
                    elif src[j] == "]":
                        in_class = False
                    j += 1
                self._blank(i + 1, j)
                i = j + 1
            elif c == "{":
                depth += 1
                i += 1
            elif c == "}":
                if closing and depth == 0:
                    return i + 1
                depth -= 1
                i += 1
            else:
                i += 1
        return i

    def _template(self, i: int) -> int:
        """Scan a template literal's body from just after its backtick."""
        src, part = self.src, i
        while True:
            c = src[i]
            if c == "\\":
                i += 2
            elif c == "`":
                self.literals.append((part, src[part:i]))
                self._blank(part, i)
                return i + 1
            elif src[i : i + 2] == "${":
                self.literals.append((part, src[part:i]))
                self._blank(part, i)
                i = part = self._code(i + 2, closing=True)
            else:
                i += 1


_OPEN, _CLOSE = "([{", ")]}"


def _match(code: str, i: int) -> int:
    """Return the offset just past the bracket that closes the one at `i`."""
    depth = 0
    for k in range(i, len(code)):
        if code[k] in _OPEN:
            depth += 1
        elif code[k] in _CLOSE:
            depth -= 1
            if depth == 0:
                return k + 1
    raise AssertionError(f"unbalanced bracket at offset {i}")


def _enclosing_key(code: str, i: int) -> str:
    """The property name of the object literal that holds offset `i`."""
    depth = 0
    for k in range(i - 1, -1, -1):
        if code[k] in _CLOSE:
            depth += 1
        elif code[k] in _OPEN:
            if depth == 0:
                key = re.search(r"([A-Za-z_$][\w$]*)\s*:\s*$", code[:k])
                return key.group(1) if key else "?"
            depth -= 1
    return "?"


def _value_end(code: str, i: int) -> int:
    """The end of a property value that starts at `i`."""
    depth = 0
    for k in range(i, len(code)):
        if code[k] in _OPEN:
            depth += 1
        elif code[k] in _CLOSE:
            if depth == 0:
                return k
            depth -= 1
        elif code[k] == "," and depth == 0:
            return k
    return len(code)


def _results(scan: _Scan, start: int, end: int) -> list[str] | None:
    """Every expression a function formatter hands back, or None if not a function.

    An arrow with an expression body hands back that expression: this is
    the implicit return the first check could not see. A block body hands
    back each `return` of its own. The bodies of functions nested inside
    it are skipped, because their returns go to a caller, not to ECharts.
    """
    code, src = scan.code, scan.src
    head = re.match(
        r"\s*(?:async\s+)?(?:function\b[^(]*(?P<fn>\()|(?P<arrow>\(|[A-Za-z_$]))", code[start:end]
    )
    if not head:
        return None
    if head.group("fn"):
        params = start + head.start("fn")
        body = code.index("{", _match(code, params))
    else:
        if head.group("arrow") == "(":
            after = _match(code, start + head.start("arrow"))
        else:
            # A bare parameter: `head` took its first character.
            after = start + head.end()
            while after < end and (code[after].isalnum() or code[after] in "_$"):
                after += 1
        arrow = re.match(r"\s*=>\s*", code[after:end])
        if not arrow:
            return None
        body = after + arrow.end()
        if code[body] != "{":
            return [src[body:end].strip()]
    close = _match(code, body)
    inner = list(code[body + 1 : close - 1])
    text = "".join(inner)
    for nested in re.finditer(r"=>\s*\{|\bfunction\b[^{]*\{", text):
        brace = nested.end() - 1
        if inner[brace] != "{":
            continue  # already blanked as part of an outer nested body
        stop = _match(text, brace)
        inner[brace + 1 : stop - 1] = " " * (stop - 1 - brace - 1)
    text = "".join(inner)
    found = []
    for ret in re.finditer(r"\breturn\b", text):
        k, depth = ret.end(), 0
        while k < len(text):
            ch = text[k]
            if ch in _OPEN:
                depth += 1
            elif ch in _CLOSE:
                if depth == 0:
                    break
                depth -= 1
            elif ch in ";\n" and depth == 0 and text[ret.end() : k].strip():
                break
            k += 1
        found.append(src[body + 1 + ret.end() : body + 1 + k].strip())
    return found


def _formatters(name: str, source: str) -> list[dict]:
    scan = _Scan(source)
    found = []
    for hit in re.finditer(r"(?<![\w$.])(\w*[fF]ormatter)\s*:", scan.code):
        start = hit.end()
        end = _value_end(scan.code, start)
        found.append(
            {
                "file": name,
                "line": source.count("\n", 0, hit.start()) + 1,
                "name": hit.group(1),
                "within": _enclosing_key(scan.code, hit.start()),
                "value": source[start:end].strip(),
                "literals": [text for at, text in scan.literals if start <= at < end],
                "results": _results(scan, start, end),
            }
        )
    return found


def _every_formatter() -> list[dict]:
    return [each for path in OURS for each in _formatters(path.name, path.read_text())]


# Where the site's formatters are, as (file, enclosing key, property).
# A tooltip `formatter` is the one ECharts renders as HTML. A tooltip
# `valueFormatter` is escaped by ECharts itself (`re(t)` around it in
# `vendor/echarts.min.js`). `label` and `axisLabel` text is drawn on the
# canvas and is never HTML. The markup check still covers all of them.
EXPECTED_FORMATTERS = {
    ("app.js", "tooltip", "formatter"): 2,
    ("app.js", "label", "formatter"): 1,
    ("app.js", "axisLabel", "formatter"): 1,
    ("rf.js", "tooltip", "valueFormatter"): 1,
    ("rf.js", "axisLabel", "formatter"): 1,
    # The busy chart's legend on a phone (#322): drops " (ours)" from a
    # series name. Plain text; ECharts draws legend names on the canvas.
    ("rf.js", "legend", "formatter"): 1,
    # The weather charts on the RF page: the time, each series in words
    # and units, and the wind direction. Returns tooltipLines(...).
    ("rf.js", "tooltip", "formatter"): 1,
}

_MARKUP = re.compile(r"<[a-zA-Z/!]")


@pytest.mark.parametrize("path", OURS, ids=lambda p: p.name)
def test_the_scanner_reads_each_file_to_the_end(path: Path) -> None:
    """Every bracket balances once literals and comments are blanked.

    A scanner that lost its place inside a string or a regular
    expression would unbalance them, and every check below would then
    be reading the wrong text.
    """
    code = _Scan(path.read_text()).code
    for pair in ("()", "[]", "{}"):
        assert code.count(pair[0]) == code.count(pair[1]), (
            f"{path.name}: {pair} do not balance after scanning. "
            f"The scanner lost its place, so the formatter checks cannot be trusted."
        )


def test_the_scanner_sees_an_implicit_return() -> None:
    """The shape the old check missed must be read as a returned result.

    This is the positive control for the checks below. The same text
    was also put into `app.js` itself and the markup and tooltip checks
    both failed on it (#249).
    """
    probe = "chart({ tooltip: { formatter: (params) => `<b>${params.name}</b>` } });\n"
    [found] = _formatters("probe.js", probe)
    assert found["within"] == "tooltip"
    assert found["results"] == ["`<b>${params.name}</b>`"]
    assert any(_MARKUP.search(text) for text in found["literals"])


def test_every_formatter_on_the_site_is_one_this_sweep_knows() -> None:
    """A new chart formatter must be added here, and so be checked here."""
    counted: dict[tuple[str, str, str], int] = {}
    for each in _every_formatter():
        key = (each["file"], each["within"], each["name"])
        counted[key] = counted.get(key, 0) + 1
    assert counted == EXPECTED_FORMATTERS, (
        f"The chart formatters changed: found {counted}. "
        f"A tooltip formatter must return tooltipLines(...), and the rest "
        f"must not build markup. Check the new one against both, then "
        f"update EXPECTED_FORMATTERS."
    )
    pages = [p.name for p in STATIC.glob("*.html") if "ormatter" in p.read_text()]
    assert not pages, f"{pages} define a chart formatter this sweep does not read"


def test_no_formatter_builds_markup() -> None:
    """No literal inside any formatter opens a tag, returned or not.

    This reads the formatter's whole value, so an implicit return, a
    string held in a variable and a string built by `+` are all seen.
    """
    offenders = [
        f"{each['file']}:{each['line']} {text[:80]!r}"
        for each in _every_formatter()
        for text in each["literals"]
        if _MARKUP.search(text)
    ]
    assert not offenders, (
        f"A chart formatter builds markup: {offenders}. ECharts sets "
        f"innerHTML from a tooltip formatter's string, and node names come "
        f"off the mesh. Return tooltipLines(...) instead."
    )


def test_every_tooltip_formatter_returns_tooltip_lines() -> None:
    """Each path out of a tooltip formatter goes through the one helper."""
    tooltips = [
        each
        for each in _every_formatter()
        if each["within"] == "tooltip" and each["name"] == "formatter"
    ]
    assert tooltips, "no tooltip formatter was found, so this check read nothing"
    for each in tooltips:
        where = f"{each['file']}:{each['line']}"
        assert each["results"], (
            f"{where}: a tooltip formatter must be written inline as a "
            f"function, so this check can read what it returns"
        )
        for result in each["results"]:
            assert result.startswith("tooltipLines("), (
                f"{where}: a tooltip formatter returns {result[:80]!r}. "
                f"ECharts sets innerHTML from a string. Return tooltipLines(...)."
            )


def test_the_helpers_that_replace_those_strings_use_text_nodes() -> None:
    """The replacements must not quietly become innerHTML themselves."""
    app = (STATIC / "app.js").read_text()
    gaps = (STATIC / "gaps.js").read_text()

    assert "function tooltipLines(" in app, "app.js lost its tooltip helper"
    assert "function nameTooltip(" in gaps, "gaps.js lost its tooltip helper"

    body = app[app.index("function tooltipLines(") :][:900]
    assert "createTextNode" in body, "tooltipLines must put values in as text"
    assert "innerHTML" not in body, "tooltipLines must never set innerHTML"

    body = gaps[gaps.index("function nameTooltip(") :][:600]
    assert "textContent" in body, "nameTooltip must put the name in as text"
    assert "innerHTML" not in body, "nameTooltip must never set innerHTML"
