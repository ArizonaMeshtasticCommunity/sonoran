"""The RF tab says what an APRS packet carries, in words.

APRS puts most of what it says in codes: a two-character symbol, a
destination that names the sending software, a path of callsigns. The
tooltip showed them raw (`symbol: S#`, `destination: APN382`), which
nobody reads. `rf.js` now names them from two lists aprs.fi maintains,
vendored by `tools/vendor_aprs_tables.py`.

The naming functions run under node against the vendored tables, the
same way `test_config_backup.py` runs its cases. The inputs are packets
the Surprise receiver really heard on 2026-09-25.
"""

import json
import shutil
import subprocess
from pathlib import Path

from tools.vendor_aprs_tables import build, device_name, specificity, symbols, tocalls

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
RF = (STATIC / "rf.js").read_text(encoding="utf-8")
TABLES = (STATIC / "vendor" / "aprs" / "aprs-tables.js").read_text(encoding="utf-8")
# The weather lines go through the units formatter (#291). With no
# settings loaded it answers in its defaults: imperial and Fahrenheit.
UNITS = (STATIC / "units.js").read_text(encoding="utf-8")


def _node() -> str:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the APRS names went unchecked. A skip looks like a pass."
    return node


def _call(expression: str) -> object:
    """Evaluate one expression against the tooltip's naming functions."""
    start = RF.index("  const APRS_TABLES = ")
    end = RF.index("  /* Keys the APRS tooltip turns into words.")
    script = (
        "var window = globalThis;\n"
        f"{UNITS}\n{TABLES}\n{RF[start:end]}\nconsole.log(JSON.stringify({expression}));"
    )
    done = subprocess.run(
        [_node(), "-e", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_symbols_are_named_with_their_overlay() -> None:
    assert _call("['/#', 'S#', 'I&', '/_', '/>', 'b#', '\\\\#'].map(symbolName)") == [
        "Digipeater",
        "State SSn-N digipeater",
        "I-gate",
        "Weather station",
        "Car",
        # Compressed positions write overlay digits 0-9 as a-j.
        "WIDE1-1 fill-in digipeater",
        "Digipeater, green star",
    ]


def test_a_symbol_that_is_not_one_names_nothing() -> None:
    assert _call("[null, '', '#', 'abc'].map(symbolName)") == [None, None, None, None]


def test_the_destination_names_the_software_that_sent_it() -> None:
    assert _call(
        "['APMI06', 'APN382', 'APAT51', 'APDW19', 'APZBOT', 'APOG77', 'APRS', 'NOTHING']"
        ".map(deviceName)"
    ) == [
        "Microsat WX3in1 Plus 2.0",
        "Kantronics KPC-3",
        "AnyTone AT-D578",
        "WB2OSZ DireWolf",
        "Experimental",
        "OpenGD77",
        None,
        None,
    ]


def test_weather_is_read_with_units_and_a_missing_reading_is_not_invented() -> None:
    lines = _call(
        "weatherLines({wind_dir_deg: 154, wind_kn: 1.7, gust_kn: 2.6, temperature_f: 70,"
        " pressure_hpa: 1014.1, rain_1h_in: 0, rain_today_in: 0})"
    )
    assert lines == [
        "Wind from SSE (154°) at 2.0 mph, gusts 3.0 mph",
        # One unit, the reader's. It showed both, whichever was chosen.
        "Temperature 70 °F",
        # Inches of mercury in imperial mode (Will, #291).
        "Pressure 29.95 inHg",
        "Rain 0.00 in in the last hour, 0.00 in since midnight",
    ]
    # No humidity was sent, so no humidity line: never a 0 %.
    assert not any("Humidity" in line for line in lines)


def test_sunlight_and_snow_are_read_with_units() -> None:
    assert _call("weatherLines({luminosity_wm2: 0, snow_24h_in: 1.5})") == [
        "Snow 1.50 in in 24 hours",
        "Sunlight 0 W/m²",
    ]


def test_a_sensor_in_celsius_reads_the_same_way() -> None:
    assert _call("weatherLines({temperature_c: 21.44, humidity: 40, battery_ok: 0})") == [
        "Temperature 70.6 °F",
        "Humidity 40 %",
        "Battery low",
    ]


def test_the_path_is_read_as_the_stations_that_repeated_it() -> None:
    assert _call(
        "[hearingLines({direct: false, via: 'w7mot-3', path: 'UNION*,W7MOT-3*,WIDE2'}),"
        " hearingLines({direct: true, path: 'WIDE2-2'}),"
        " hearingLines({direct: false, path: 'WIDE1-1*,WIDE2-1'}),"
        " hearingLines({object: 'object', owner: 'km7aqb-2', direct: true, via: 'km7aqb-2'})]"
    ) == [
        ["Repeated by UNION, then W7MOT-3"],
        ["Heard directly, with no digipeater"],
        # An alias names nobody, so nobody is named.
        ["Repeated by a digipeater that did not sign the path"],
        ["An object placed by KM7AQB-2, not a transmitter"],
    ]


def test_the_tables_load_before_the_page_that_reads_them() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert html.index("static/vendor/aprs/aprs-tables.js") < html.index("static/rf.js")


def test_the_lists_are_credited_as_their_licence_asks() -> None:
    """CC BY-SA: credit in the small print, as the maintainer asks."""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "OH7LZB" in html and "CC BY-SA" in html
    assert "OH7LZB" in TABLES
    provenance = (STATIC / "vendor" / "aprs" / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "CC BY-SA 4.0" in provenance and "CC BY-SA 2.0" in provenance


def test_the_generator_names_and_orders_devices() -> None:
    listing = {
        "tocalls": [
            {"tocall": "APZ*", "vendor": "Unknown", "model": "Experimental"},
            {"tocall": "APOG??", "vendor": "OpenGD77", "model": "OpenGD77"},
            {"tocall": "APOG77", "vendor": "OpenGD77", "model": "OpenGD77"},
            {"tocall": "APRS", "vendor": "Unknown", "model": "Unknown"},
        ]
    }
    # Exact before wildcard, and a catch-all with no name is dropped.
    assert tocalls(listing) == [
        ["APOG77", "OpenGD77"],
        ["APOG??", "OpenGD77"],
        ["APZ*", "Experimental"],
    ]
    assert device_name({"vendor": "Microsat", "model": "WX3in1 Plus", "version": "2.0"}) == (
        "Microsat WX3in1 Plus 2.0"
    )


def test_the_generator_leaves_out_unused_symbols() -> None:
    index = {
        "symbols": {
            "/#": {"description": "Digipeater"},
            "/D": {"unused": 1},
        }
    }
    assert symbols(index) == {"/#": "Digipeater"}
    assert build(index, {"tocalls": []}).startswith("/*")


def test_the_vendored_tables_are_what_the_generator_writes() -> None:
    """A hand edit to the generated file would drift from its sources."""
    body = TABLES[TABLES.index("= ") + 2 : TABLES.rindex(";")]
    tables = json.loads(body)
    assert tables["symbols"]["/#"] == "Digipeater"
    assert tables["tocalls"] == sorted(
        tables["tocalls"], key=lambda pair: (specificity(pair[0]), pair[0])
    )


# --- icons ----------------------------------------------------------------


def test_the_aprs_sprite_sheets_are_the_grid_the_page_reads() -> None:
    """16 wide, 6 high, 48 px cells drawn at 24: `spriteCell` assumes it."""
    for table in range(3):
        png = (STATIC / "vendor" / "aprs" / f"aprs-symbols-24-{table}@2x.png").read_bytes()
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        width = int.from_bytes(png[16:20], "big")
        height = int.from_bytes(png[20:24], "big")
        assert (width, height) == (16 * 48, 6 * 48)
    assert "background-size: 384px 144px" in (STATIC / "app.css").read_text(encoding="utf-8")
    assert "(index % 16) * 24" in RF and "Math.floor(index / 16) * 24" in RF


def test_an_aircraft_is_drawn_as_what_its_category_says() -> None:
    """A7 is a rotorcraft in DO-260B. It must not be drawn as a jet."""
    for category, shape in (("A7", "rotor"), ("B1", "glider"), ("B2", "balloon"), ("B6", "drone")):
        assert f"{category}: ['{shape}'," in RF, category
    assert "A7: 'Helicopter'" in RF


def test_icons_are_built_node_by_node_never_from_markup() -> None:
    """The icons add no markup path: SVG by createElementNS, no divIcon html."""
    start = RF.index("function aircraftIcon(")
    body = RF[start : RF.index("\n  }\n", start)]
    assert "createElementNS" in body
    assert "L.divIcon" not in RF


def test_the_icon_set_is_credited() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "hessu/aprs-symbols" in html
    provenance = (STATIC / "vendor" / "aprs" / "PROVENANCE.md").read_text(encoding="utf-8")
    assert "f2286a9cd4" in provenance and "COPYRIGHT.md" in provenance


def test_an_icon_keeps_its_own_classes_after_leaflet_styles_it() -> None:
    """Leaflet's `_setIconStyles` replaces className outright.

    `rf-aprs` is what sizes an APRS symbol's sprite layers; losing it made
    every APRS icon an empty, invisible box on the live map (2026-09-26).
    Runs the real icon class against Leaflet's real method under node.
    """
    start = RF.index("  const ElementIcon = L.Icon.extend({")
    end = RF.index("  const SVG = ", start)
    leaflet = (STATIC / "vendor" / "leaflet.js").read_text(encoding="utf-8")
    method = leaflet[leaflet.index("_setIconStyles:function") :]
    method = method[: method.index("},_createImg")] + "}"
    script = (
        "const node = { className: 'rf-aprs relayed', style: {}, classList: { add(...c) {"
        " node.className += ' ' + c.join(' '); } } };\n"
        "function m(p) { return p && { x: p[0], y: p[1],"
        " divideBy: (d) => ({ x: p[0] / d, y: p[1] / d }) }; }\n"
        "const L = { Icon: { extend(proto) { return function (options) {"
        f" const self = Object.assign({{ options, {method} }}, proto);"
        " return self; }; } } };\n"
        f"{RF[start:end]}\n"
        "new ElementIcon({ element: node, className: 'rf-icon', iconSize: [24, 24] })"
        ".createIcon();\n"
        "console.log(JSON.stringify(node.className.split(' ')));"
    )
    done = subprocess.run(
        [_node(), "-e", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    classes = json.loads(done.stdout)
    assert {"rf-aprs", "relayed", "rf-icon", "leaflet-marker-icon"} <= set(classes)


def test_the_aprs_icon_css_leaves_leaflets_positioning_alone() -> None:
    """app.css loads after leaflet.css; a `position` on `.rf-aprs` would win
    and take every APRS symbol out of the place Leaflet put it."""
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    rule = css[css.index(".rf-aprs {") :]
    rule = rule[: rule.index("}")]
    assert "position" not in rule
