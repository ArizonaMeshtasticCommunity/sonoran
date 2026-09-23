"""Two advisories are open against the vendored JavaScript, and neither
applies to how this dashboard uses it. These tests are what keeps that
true.

The Python side is clean: 66 packages across the lock and every extra,
queried against OSV on 2026-09-23, **0 advisories** — with a positive
control in the same batch (`urllib3==1.24.1` returned 24,
`jinja2==2.10` returned 12) so the zero is a measured zero and not a
broken query.

The vendored browser libraries are a different matter, because nothing
audits them: they are files in the tree, not entries in a lock.

    leaflet 1.9.4      0 advisories
    echarts 5.6.0      GHSA-fgmj-fm8m-jvvx / CVE-2026-45249  MODERATE
    protobufjs 7.6.3   GHSA-j3f2-48v5-ccww / CVE-2026-59877  MODERATE
    js-yaml            no version string in the minified file

Both advisories are real and both are **conditional on a usage this
repo does not have**. That is a much weaker kind of safety than "not
affected", because the condition is one ordinary feature away in each
case — so each has a test rather than a sentence in a document nobody
re-reads.

`js-yaml` carries no version string to check. It lives inside the
vendored config-checker, which is pinned to an upstream commit and
watched by `vendor-pin.yml`; its dependencies are upstream's to bump.
Recorded as unknown rather than guessed, because a version inferred
from a minified file would look exactly like one that was read.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
VENDOR = STATIC / "vendor"

# The version this dashboard ships, and the version each advisory is
# fixed in. Below the fix, the guard applies; at or above it, the
# corresponding test relaxes by itself rather than having to be
# remembered.
ECHARTS_FIXED_IN = (6, 1, 0)
PROTOBUFJS_FIXED_IN = (7, 6, 5)


def _version(text: str, pattern: str) -> tuple[int, ...]:
    found = re.search(pattern, text)
    assert found, f"no version matched {pattern!r}; the vendored file's header changed"
    return tuple(int(part) for part in found.group(1).split("."))


def _echarts_version() -> tuple[int, ...]:
    head = (VENDOR / "echarts.min.js").read_text(encoding="utf-8", errors="replace")[:400_000]
    return _version(head, r'version:"(\d+\.\d+\.\d+)"')


def _protobufjs_version() -> tuple[int, ...]:
    head = (VENDOR / "config-checker" / "js" / "vendor" / "protobuf.min.js").read_text(
        encoding="utf-8", errors="replace"
    )[:4000]
    return _version(head, r"protobuf\.js v(\d+\.\d+\.\d+)")


def _our_scripts() -> dict[str, str]:
    """Every script this repo wrote, which is where a usage would appear."""
    return {path.name: path.read_text(encoding="utf-8") for path in sorted(STATIC.glob("*.js"))}


def test_the_versions_are_actually_readable() -> None:
    """The control.

    Every test below is of the form "this dangerous usage is absent".
    If the version could not be read, or the scripts could not be
    found, all of them would pass while measuring nothing.
    """
    assert _echarts_version() >= (5, 0, 0)
    assert _protobufjs_version() >= (7, 0, 0)
    scripts = _our_scripts()
    assert len(scripts) > 5, f"only found {sorted(scripts)}; the tree moved"
    assert "app.js" in scripts


def test_no_echarts_lines_series_while_the_xss_is_unfixed() -> None:
    """CVE-2026-45249, fixed in ECharts 6.1.0. Vendored: 5.6.0.

    In the `lines` series, with a tooltip and **no** custom
    `tooltip.formatter`, a `series.data[i].name` reaches `innerHTML`.
    The built-in formatters escape everywhere else, so this one breaks
    the convention and nobody would expect it.

    That matters more here than the moderate rating suggests: names on
    this dashboard are typed by whoever owns the radio, and this repo
    has already shipped one stored XSS through exactly that channel —
    a `display_name` interpolated into a template literal. The origin
    also holds Web Serial for the config page.

    A `lines` series is a plausible next feature — link paths drawn on
    a geographic map is the obvious one for a mesh. This fails if
    somebody adds it before the upgrade, instead of shipping the hole.
    """
    if _echarts_version() >= ECHARTS_FIXED_IN:
        return
    for name, source in _our_scripts().items():
        assert "type: 'lines'" not in source and 'type: "lines"' not in source, (
            f"{name} adds an ECharts `lines` series, and the vendored ECharts "
            f"{'.'.join(map(str, _echarts_version()))} renders a data point's "
            f"name through innerHTML in that series' default tooltip "
            f"(CVE-2026-45249, fixed in 6.1.0). Node names here are typed by "
            f"strangers. Either upgrade ECharts or pass a tooltip.formatter "
            f"that returns an element, as the graph page does."
        )


def test_protobufjs_is_only_ever_given_a_descriptor_it_already_has() -> None:
    """CVE-2026-59877, fixed in protobuf.js 7.6.5. Vendored: 7.6.3.

    An option declaration in `.proto` SCHEMA TEXT that ends early makes
    the option parser loop for ever. The advisory is explicit that
    "applications that only encode or decode protobuf binary data with
    trusted schemas are not directly affected", and that is this one:
    every call site uses `Root.fromJSON` on the static descriptor in
    `meshtastic-proto.js`, whose own header says it exists so the page
    decodes "without needing to fetch .proto files".

    So the reachable sinks -- `parse`, `Root.load`, `Root.loadSync` --
    are never called. This fails if one appears.
    """
    if _protobufjs_version() >= PROTOBUFJS_FIXED_IN:
        return
    checker = VENDOR / "config-checker" / "js"
    sinks = re.compile(
        r"\b(?:protobuf|pb)\s*\.\s*(?:parse|Root\s*\.\s*loadSync|Root\s*\.\s*load)\b"
    )
    for path in sorted(checker.rglob("*.js")):
        if path.name == "protobuf.min.js":
            continue  # The library itself, which of course contains them.
        source = path.read_text(encoding="utf-8", errors="replace")
        found = sinks.search(source)
        assert not found, (
            f"{path.relative_to(ROOT)} drives protobuf.js from .proto schema "
            f"text ({found.group(0)!r}). The vendored "
            f"{'.'.join(map(str, _protobufjs_version()))} loops for ever on a "
            f"truncated option declaration (CVE-2026-59877, fixed in 7.6.5). "
            f"Everything else here uses Root.fromJSON on the static descriptor."
        )
    # And the descriptor path is genuinely the one in use, so the sweep
    # above is not passing because the library went unused.
    assert any(
        "Root.fromJSON" in path.read_text(encoding="utf-8", errors="replace")
        for path in checker.rglob("*.js")
    ), "nothing calls Root.fromJSON any more, so this test no longer describes the code"
