"""Newcomer first: every technical word on the screen can explain itself.

AGENTS.md section 3B and docs/NEWCOMER.md hold the rule. The reader is
somebody in their first weeks of Meshtastic. They know what a node and a
message are. They do not know SNR, a hop limit or a modem preset.

`web/static/glossary.js` holds one plain explanation for each such word,
and an element with `data-term="snr"` gets a button that opens it. This
file is the guard that keeps the rule true for every later change:

* every glossary entry has a label and a plain explanation;
* every `data-term` and `term:` in the interface names a real entry;
* `docs/GLOSSARY.md` is the glossary, word for word;
* new on-screen text that uses a glossary word must carry its tooltip.

The last check is a ratchet. `tests/unit/newcomer_baseline.json` lists
the places that used a word without its tooltip on the day the rule
came in. Those may stay. A new one fails here, with the fix in the
message. A fixed one must leave the baseline too, so the list can only
get shorter.

`tools/newcomer_check.py` does the work. Its limits are in its own
docstring and in docs/NEWCOMER.md section 6.
"""

from __future__ import annotations

from tools import newcomer_check as check


def test_the_glossary_loads_and_holds_the_words_sonoran_shows() -> None:
    glossary = check.load_glossary()
    # The control: a glossary that failed to load reads as "no words to
    # check", which would pass everything below.
    for term in (
        "snr",
        "rssi",
        "hop-limit",
        "modem-preset",
        "gateway",
        "traceroute",
        "role-router-late",
        "channel-utilization",
        "position-precision",
    ):
        assert term in glossary, f"glossary.js has no entry for {term}"


def test_every_entry_explains_itself_in_plain_words() -> None:
    problems = check.entry_problems(check.load_glossary())
    assert not problems, "\n".join(problems)


def test_a_bad_entry_is_caught() -> None:
    """A plausible broken entry fails the check (AGENTS.md 3A.4 item 9)."""
    bad = {
        "SNR": {"label": "SNR", "plain": "x", "words": []},
        "rssi": {"label": "RSSI", "plain": "", "words": ["RSSI"]},
        "hop": {"label": "Hop", "plain": "One relay. " * 40, "words": []},
        "dbm": {"label": "dBm", "plain": "Power. It is a unit.", "more": "http://example.com"},
    }
    problems = "\n".join(check.entry_problems(bad))
    assert "SNR: the id" in problems
    assert "rssi: no plain explanation" in problems
    assert "hop: the explanation is" in problems
    assert "dbm: the learn-more link" in problems


def test_every_term_the_interface_names_is_in_the_glossary() -> None:
    unknown = check.unknown_terms(check.load_glossary())
    assert not unknown, "\n".join(
        f"{where}: data-term or term names '{term}', and glossary.js has no such entry"
        for where, term in unknown
    )


def test_the_glossary_document_is_the_glossary() -> None:
    wanted = check.glossary_markdown(check.load_glossary())
    have = check.GLOSSARY_DOC.read_text(encoding="utf-8") if check.GLOSSARY_DOC.exists() else ""
    assert have == wanted, (
        "docs/GLOSSARY.md does not match web/static/glossary.js. "
        "Run: uv run python -m tools.newcomer_check --write-doc"
    )


def test_new_text_with_a_glossary_word_carries_its_tooltip() -> None:
    findings = check.scan_all(check.load_glossary())
    new, stale = check.compare(findings, check.read_baseline())
    assert not new, check.explain_new(new)
    assert not stale, check.explain_stale(stale)


def test_the_html_scan_sees_a_new_word_and_its_tooltip() -> None:
    """The scan catches the shape it exists for, and passes the fix."""
    glossary = {"snr": {"label": "SNR", "plain": "p", "words": ["SNR"]}}
    bare = '<div><p class="sub">Best SNR today</p></div>'
    marked = '<div><p class="sub"><span data-term="snr">Best SNR</span> today</p></div>'
    on_parent = (
        '<div><label data-term="snr">Floor <select><option>SNR 5</option></select></label></div>'
    )
    found = check.scan_html("x.html", bare, glossary)
    assert [(f.term, f.text) for f in found] == [("snr", "Best SNR today")]
    assert check.scan_html("x.html", marked, glossary) == []
    assert check.scan_html("x.html", on_parent, glossary) == []


def test_the_html_scan_ignores_what_is_not_on_the_screen() -> None:
    glossary = {"snr": {"label": "SNR", "plain": "p", "words": ["SNR"]}}
    hidden = (
        "<!-- SNR in a comment --><script>const a = 'SNR';</script>"
        '<style>.snr{}</style><code>rx_snr</code><span class="sr-only">SNR</span>'
        "<template><p>SNR</p></template>"
    )
    assert check.scan_html("x.html", hidden, glossary) == []


def test_a_term_far_up_the_page_does_not_count() -> None:
    """A whole page marked with data-term must not excuse every paragraph."""
    glossary = {"snr": {"label": "SNR", "plain": "p", "words": ["SNR"]}}
    far = '<section data-term="snr"><div><p>SNR here</p></div></section>'
    assert len(check.scan_html("x.html", far, glossary)) == 1


def test_the_js_scan_reads_labels_text_and_headings() -> None:
    glossary = {"snr": {"label": "SNR", "plain": "p", "words": ["SNR"]}}
    source = "\n".join(
        [
            "const a = { label: 'SNR', num: true };",
            "const b = { label: 'SNR', term: 'snr', num: true };",
            "el('span', { text: 'Best SNR' });",
            "el('span', { text: 'Best SNR', 'data-term': 'snr' });",
            "el('h3', {}, 'SNR over time');",
            "el('h3', { 'data-term': 'snr' }, 'SNR over time');",
            "const c = { hint: 'The SNR is a ratio.' };",  # an explanation, not a label
        ]
    )
    found = check.scan_js("x.js", source, glossary)
    assert sorted(f.text for f in found) == ["Best SNR", "SNR", "SNR over time"]


def test_an_internal_enum_name_in_primary_text_is_flagged() -> None:
    glossary: dict[str, dict] = {}
    found = check.scan_html("x.html", "<div><p>Set it to ROUTER_LATE</p></div>", glossary)
    assert [f.term for f in found] == [check.ENUM_RULE]
    js = check.scan_js("x.js", "el('p', { text: 'Use CLIENT_MUTE here' });", glossary)
    assert [f.term for f in js] == [check.ENUM_RULE]


def test_the_ratchet_fails_both_ways() -> None:
    one = check.Finding("index.html", "snr", "Best SNR")
    two = check.Finding("app.js", "rssi", "RSSI")
    new, stale = check.compare([one, two], [one])
    assert new == [two] and stale == []
    new, stale = check.compare([one], [one, two])
    assert new == [] and stale == [two]
    # A second copy of a known finding is still a new finding.
    new, _ = check.compare([one, one], [one])
    assert new == [one]


def test_the_failure_says_what_to_add() -> None:
    message = check.explain_new([check.Finding("index.html", "snr", "Best SNR")])
    assert 'data-term="snr"' in message
    assert "glossary.js" in message
    assert "docs/NEWCOMER.md" in message


# --------------------------------------------------------------------------
# The tooltip itself. The e2e journey "a glossary word explains itself by
# tap and by keyboard" opens one in a browser; these hold the source shape.

APP = (check.STATIC / "app.js").read_text(encoding="utf-8")
INDEX = (check.STATIC / "index.html").read_text(encoding="utf-8")


def _body(name: str) -> str:
    start = APP.index(f"function {name}(")
    return APP[start : APP.index("\n}\n", start)]


def test_the_glossary_loads_before_app_js() -> None:
    glossary = INDEX.index('src="static/glossary.js')
    assert glossary < INDEX.index('src="static/app.js'), "app.js would find no glossary"


def test_a_term_opens_the_one_hint_popover_and_never_a_title() -> None:
    """One popover pattern on the site: the term button is a hint button."""
    terms = _body("revealTerms")
    assert "fitHint(host, 'word'" in terms
    assert APP.count("function wireHint(") == 1
    assert "wireHint(button, panel);" in _body("fitHint")
    assert "role: 'tooltip'" not in APP and "'role', 'tooltip'" not in APP
    assert "revealTerms(root);" in _body("revealHints"), "render never builds the term buttons"


def test_a_term_on_a_control_goes_beside_it() -> None:
    """A button cannot hold a button, and a label must keep its control's name."""
    terms = _body("revealTerms")
    assert "host.matches('button, a, select, input, textarea, summary, [id]')" in terms
    assert "keepControlName(host)" in terms
    assert "host.after(button, panel)" in _body("fitHint")


def test_every_role_the_meshtastic_docs_name_has_an_entry() -> None:
    glossary = check.load_glossary()
    for role in (
        "CLIENT", "CLIENT_MUTE", "CLIENT_HIDDEN", "CLIENT_BASE", "ROUTER", "ROUTER_LATE",
        "ROUTER_CLIENT", "REPEATER", "TRACKER", "SENSOR", "TAK", "TAK_TRACKER", "LOST_AND_FOUND",
    ):  # fmt: skip
        term = "role-" + role.lower().replace("_", "-")
        assert term in glossary, f"{role} has no glossary entry {term}"


def test_the_node_page_shows_the_plain_role_and_keeps_the_exact_one() -> None:
    rows = _body("identityRows")
    assert "text: node.role ? roleLabel(node.role) : 'Unknown'" in rows
    assert "exact: node.role || null" in rows
    assert "`${roleLabel(node.role)} (${node.role})`" not in rows
