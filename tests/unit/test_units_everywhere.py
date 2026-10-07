"""Every distance, speed, temperature and so on goes through `SonoranUnits`.

Will's report (#291): "The statistics page isn't showing the distances
and metrics in what is set in the settings. Seems stuck in km. Review the
whole site to make sure anything that is distance or temp gets converted
based on settings."

The cause was one line. The link leaderboard printed the API's
`"unit": "km"` as it came, and the setting never reached it. An audit
then found twenty more places with a unit written into the text. So this
test does not check the one line. It reads every page script for a unit
written after a number, and for a unit the server sent printed as it
came, and fails on any that is not on the list below with a reason.

It reads the source rather than running it, which means it can be
fooled by a unit built in some other way. It is the net under the
formatter, not a replacement for looking at the page.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"

# Files that are not page scripts that print for a reader.
SKIPPED = {
    # The formatter itself: the one place units are allowed.
    "units.js",
    # Generated protobuf code.
    "meshtastic-static.js",
    "meshtastic-serial-proto.js",
    "protobuf-runtime.js",
}

# A unit written straight after a number or an interpolation. The
# look-ahead stops "min" matching "m" and "m²" matching "m".
_UNITS = r"(?:km/h|km²|km2|km|m/s|mi²|mi|mph|ft|mm|inHg|hPa|°C|°F|m)"
FIXED_UNIT = re.compile(r"(?:\}|\d)\s?" + _UNITS + r"(?![\w/²])")
# A unit the server sent, printed as it came.
RAW_UNIT = re.compile(r"\$\{[\w.]*\bunit\}")

# Each entry is a file and a piece of the line that is allowed, with the
# reason. Keep this list short. Every entry is a place where the reader's
# setting is not followed, so every entry needs a reason a reader would
# accept.
ALLOWED: dict[tuple[str, str], str] = {
    ("rf.js", "return `${text}${unit ? ` ${unit}` : ''}`;"): (
        "A member mod's value, shown in the unit the mod sent it in, from a fixed "
        "list by key (#324). Converting it would claim a reading the mod never made."
    ),
    ("app.js", "/ 60)}m`"): "Minutes in a short age such as 5m, not metres.",
    ("config-check.js", "Use 30m, 1.5h, 2d"): "Minutes in a typed duration, not metres.",
    ("gaps.js", ": `${Math.round(value)} m`"): (
        "The fallback when the formatter is not loaded, which is only the node test harness."
    ),
    ("coverage.js", "m out"): (
        "An exported YAML file for another tool. Its reader is a program that expects metres."
    ),
    ("embed-coverage.js", "summary.rx_height_m} m above"): (
        "The public embed loads no settings and has no control to change them."
    ),
    ("planner.js", "ft of ${cable.name}"): (
        "The cable length box is typed in feet in both modes, and cable loss is sold per "
        "100 ft. Whether it follows the setting is an open question on #291."
    ),
}


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Return the numbered lines of a script that are code, not comment."""
    text = path.read_text(encoding="utf-8")
    # Blank out block comments but keep the line count.
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
    return [
        (number, line)
        for number, line in enumerate(text.splitlines(), start=1)
        if line.strip() and not line.strip().startswith("//")
    ]


def _allowed(name: str, line: str) -> bool:
    return any(file == name and piece in line for (file, piece) in ALLOWED)


def _offences(name: str, lines: list[tuple[int, str]]) -> list[str]:
    found = []
    for number, line in lines:
        if not (FIXED_UNIT.search(line) or RAW_UNIT.search(line)):
            continue
        # Only text a reader sees: a string or a template. A bare `1000 m`
        # in arithmetic has no quote on the line.
        if not any(quote in line for quote in ("'", '"', "`")):
            continue
        if _allowed(name, line):
            continue
        found.append(f"{name}:{number}: {line.strip()}")
    return found


def _scripts() -> list[Path]:
    return sorted(path for path in STATIC.glob("*.js") if path.name not in SKIPPED)


def test_no_page_script_prints_a_unit_the_reader_did_not_choose() -> None:
    offences = [item for path in _scripts() for item in _offences(path.name, _code_lines(path))]
    assert not offences, (
        "These lines print a unit without going through SonoranUnits. Convert them, or add "
        "them to ALLOWED with a reason:\n" + "\n".join(offences)
    )


def test_every_allowance_still_matches_a_line() -> None:
    """A stale allowance would wave through the next line that matched it."""
    for (name, piece), reason in ALLOWED.items():
        assert reason, f"{name}: {piece} has no reason"
        lines = [
            line
            for _, line in _code_lines(STATIC / name)
            if piece in line and (FIXED_UNIT.search(line) or RAW_UNIT.search(line))
        ]
        assert lines, f"{name}: no line the scanner flags matches {piece!r}"


def test_the_scanner_finds_what_it_is_for() -> None:
    """Positive control: each shape the scanner must catch is caught."""
    lines = [
        (1, "el('span', { text: `${count(row.value)} ${row.unit}` })"),
        (2, "wind_speed: ['Wind speed', (v) => `${round(v, 1)} m/s`],"),
        (3, "`about ${biggest.width_km} km wide.`"),
        (4, "label: 'under 1,500 m'"),
        (5, "`Temperature ${x} °C`"),
        (6, "`${area.toFixed(0)} km2`"),
    ]
    assert len(_offences("test.js", lines)) == len(lines)
    # And the shapes it must leave alone.
    quiet = [
        (1, "`every ${n} min`"),
        (2, "const limit = 1000 m;"),
        (3, "`${SonoranUnits.distanceFromKm(x)} away`"),
    ]
    assert _offences("test.js", quiet) == []
