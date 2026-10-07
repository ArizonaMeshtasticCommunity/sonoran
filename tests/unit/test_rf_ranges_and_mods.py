"""Any swept range, member mods, and the server that never trusts a station (#324).

The parts that need no database: the contract, the guard's checks and
limits, what `store_batch` decides to write, the ingest's logging, and
the page's handling of text a mod sent, run under node. The database
side is in `tests/integration/test_rf.py`.
"""

import json
import logging
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from sonoran.config import Settings
from sonoran.rf.guard import NEW, QUARANTINED, TRUSTED, Bucket, Guard, Limits
from sonoran.rf.ingest import InvalidLog, decode, limits_from
from sonoran.rf.schema import (
    INVISIBLE,
    Batch,
    Custom,
    Spectrum,
    Status,
    json_schema,
    plain_text,
)
from sonoran.rf.store import Rules, range_key, shared_time, store_batch, store_custom

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "src" / "sonoran" / "web" / "static"
RF = (STATIC / "rf.js").read_text(encoding="utf-8")
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
# The Surprise station, rounded, and a point about 40 km east of it.
HOME = (33.63, -112.37)
NEAR = (33.63, -111.94)


def _status(**extra: object) -> Status:
    return Status.model_validate({"v": 1, "station": "tempe-roof", "sent": NOW, **extra})


def _sweep(**extra: object) -> dict[str, object]:
    return {
        "tool": "rtl_power",
        "f_start_hz": 902_000_000,
        "f_end_hz": 928_000_000,
        "bin_hz": 25_000,
        "gain_db": 32.8,
        **extra,
    }


def _spectrum(**extra: object) -> Spectrum:
    return Spectrum.model_validate(
        {
            "v": 1,
            "station": "tempe-roof",
            "kind": "spectrum",
            "t": NOW,
            "f_start_hz": 420_000_000,
            "bin_hz": 25_000,
            "sweeps": 12,
            "gain_db": 20,
            "p50": [-400, -410],
            "p95": [-300, -310],
            "peak": [-200, -210],
            "busy": [0, 5],
            **extra,
        }
    )


def _custom(points: list[dict[str, object]], **extra: object) -> Custom:
    return Custom.model_validate(
        {
            "v": 1,
            "station": "tempe-roof",
            "kind": "custom",
            "mod": "lightning",
            "sent": NOW,
            "points": points,
            **extra,
        }
    )


# --- The contract ------------------------------------------------------


def test_a_heartbeat_reports_its_sweeps_and_a_bad_one_is_left_out() -> None:
    """One bad sweep report must never cost the station its heartbeat."""
    status = _status(
        sweeps=[
            _sweep(command="rtl_power -f 902M:928M:25k -g 32.8 -", interval_s=5, dwell_s=60),
            _sweep(f_end_hz=1),  # ends below its start
            {"tool": "Not A Tool!"},
            "nonsense",
        ]
    )
    assert len(status.sweeps) == 1
    assert status.sweeps[0].command == "rtl_power -f 902M:928M:25k -g 32.8 -"
    assert status.sweeps[0].dwell_s == 60
    # An agent that reports nothing is as before.
    assert _status().sweeps == []


def test_a_reported_command_loses_its_invisible_characters() -> None:
    status = _status(sweeps=[_sweep(command="rtl_power‮ -f​ x", tool_version="1⁦.0")])
    assert status.sweeps[0].command == "rtl_power -f x"
    assert status.sweeps[0].tool_version == "1.0"


def test_a_spectrum_may_name_its_range() -> None:
    assert _spectrum(name="ism433").name == "ism433"
    assert _spectrum().name is None
    with pytest.raises(ValidationError):
        _spectrum(name="<b>loud</b>")


def test_a_range_is_its_source_start_bin_and_bins() -> None:
    """Two ranges of one station are two keys; so are two sources."""
    assert range_key(_spectrum()) == ("-", 420_000_000, 25_000, 2)
    assert range_key(_spectrum(source="pi5")) == ("pi5", 420_000_000, 25_000, 2)
    assert range_key(_spectrum(f_start_hz=902_000_000)) != range_key(_spectrum())


def test_a_mod_batch_is_read_from_its_own_topic() -> None:
    payload = json.dumps(
        {
            "v": 1,
            "station": "tempe-roof",
            "kind": "custom",
            "mod": "lightning",
            "sent": NOW.isoformat(),
            "points": [{"id": "Strike-1", "t": NOW.isoformat(), "heard_here": True}],
        }
    ).encode()
    message = decode("rf/v1/tempe-roof/custom", payload)
    assert isinstance(message, Custom)
    assert message.points[0].id == "strike-1"
    # It must name the station its topic names: a mod cannot post as
    # another station, any more than a decoder can.
    with pytest.raises(ValueError, match="names station"):
        decode("rf/v1/other-roof/custom", payload)


def test_a_mod_point_sends_lat_and_lon_together() -> None:
    with pytest.raises(ValidationError):
        _custom([{"id": "a", "t": NOW, "lat": 33.5}])
    point = _custom([{"id": "a", "t": NOW}]).points[0]
    assert point.lat is None and not point.heard_here


def test_hostile_mod_values_are_stored_as_short_plain_text() -> None:
    """Section 8: the data supplies values, never markup, links or tricks."""
    point = _custom(
        [
            {
                "id": "x",
                "t": NOW,
                "meta": {
                    "html": "<img src=x onerror=alert(1)>",
                    "bidi": "gnp.‮exe",
                    "hidden": "a​d‍sb",
                    "too_long": "y" * 300,
                    "nested": {"a": 1},
                    "listed": [1, 2],
                    "bad key!": 1,
                    "level_db": -42.5,
                },
            }
        ]
    ).points[0]
    assert point.meta == {
        # Kept as text: the page sets it as text, so it is never markup.
        "html": "<img src=x onerror=alert(1)>",
        "bidi": "gnp.exe",
        "hidden": "adsb",
        "level_db": -42.5,
    }


def test_the_schema_offers_a_mod_its_own_message() -> None:
    schema = json_schema()
    assert "Custom" in schema["$defs"]  # type: ignore[operator]
    assert "Sweep" in schema["$defs"]  # type: ignore[operator]


# --- The guard: plausibility --------------------------------------------


def _guard(**limits: Any) -> Guard:
    guard = Guard(Limits(**limits))
    guard.note_position("tempe-roof", *HOME, 1000)
    return guard


def test_a_point_beyond_what_its_kind_can_reach_is_doubtful() -> None:
    guard = _guard()
    assert guard.doubtful("adsb", "tempe-roof", "a1b2c3", *NEAR, NOW) is None
    # Chicago, from Arizona.
    assert "km from the station" in (
        guard.doubtful("adsb", "tempe-roof", "a1b2c3", 41.9, -87.6, NOW) or ""
    )
    # A weather sensor is heard next door, not 100 km away.
    assert guard.doubtful("ism", "tempe-roof", "acurite-1", 34.8, -112.37, NOW) is not None


def test_a_station_that_sent_no_position_is_not_checked_for_reach() -> None:
    assert Guard().doubtful("adsb", "nowhere", "a1b2c3", 41.9, -87.6, NOW) is None


def test_an_aircraft_that_jumps_is_doubtful_and_one_that_flies_is_not() -> None:
    guard = _guard()
    guard.remember("adsb", "tempe-roof", "a1b2c3", *NEAR, NOW)
    # 20 s later, 3 km on: a jet.
    later = NOW + timedelta(seconds=20)
    assert guard.doubtful("adsb", "tempe-roof", "a1b2c3", 33.657, -111.94, later) is None
    # 20 s later, 200 km away: nothing flies that fast.
    assert "faster" in (guard.doubtful("adsb", "tempe-roof", "a1b2c3", 31.83, -111.94, later) or "")


def test_a_point_no_other_station_could_have_seen_is_doubtful() -> None:
    guard = _guard()
    for station in ("mesa-hill", "glendale"):
        guard.remember("adsb", station, "a1b2c3", *NEAR, NOW)
    # Within our reach, and 40 km from where two others put it at the
    # same moment.
    reason = guard.doubtful("adsb", "tempe-roof", "a1b2c3", *HOME, NOW)
    assert reason == "disagrees with 2 other stations"
    # One other station is not a majority: no corroboration check.
    single = _guard()
    single.remember("adsb", "mesa-hill", "a1b2c3", *NEAR, NOW)
    assert single.doubtful("adsb", "tempe-roof", "a1b2c3", 33.63, -112.37, NOW) is None


def test_trust_is_the_sources_then_the_stations_then_new() -> None:
    guard = Guard()
    assert guard.trust_of("tempe-roof", "pi5") == NEW
    guard.set_trust({("tempe-roof", "*"): TRUSTED, ("tempe-roof", "mod-pi"): QUARANTINED})
    assert guard.trust_of("tempe-roof", "pi5") == TRUSTED
    assert guard.trust_of("tempe-roof", None) == TRUSTED
    assert guard.trust_of("tempe-roof", "mod-pi") == QUARANTINED
    assert guard.trust_of("other", None) == NEW


# --- The guard: limits ---------------------------------------------------


def test_a_bucket_gives_its_burst_then_its_rate() -> None:
    bucket = Bucket(rate=60, burst=100)
    assert bucket.take(150, NOW) == 100
    assert bucket.take(10, NOW) == 0
    # A minute later, sixty more.
    assert bucket.take(100, NOW + timedelta(minutes=1)) == 60


def test_points_over_the_limit_are_dropped_and_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    guard = _guard(points_per_minute=10, points_burst=10)
    with caplog.at_level(logging.WARNING, logger="sonoran.rf.guard"):
        assert guard.allow_points("tempe-roof", 15, NOW) == 10
        assert guard.allow_points("tempe-roof", 15, NOW + timedelta(seconds=1)) == 0
    assert guard.dropped["points"] == 20
    assert len([r for r in caplog.records if "over its points limit" in r.message]) == 1


def test_messages_over_the_limit_are_refused() -> None:
    guard = _guard(messages_per_minute=1, messages_burst=2)
    assert [guard.allow_message("tempe-roof", NOW) for _ in range(3)] == [True, True, False]


def test_a_station_keeps_at_most_its_ranges_and_bins_a_minute() -> None:
    guard = _guard(spectrum_max_ranges=2, spectrum_max_bins=3000)
    minute = NOW.replace(second=0)

    def allow(f_start: int, bins: int) -> str | None:
        return guard.allow_spectrum(
            "tempe-roof", ("-", f_start, 25_000, bins), f_start, bins, 25_000, minute, NOW
        )

    assert allow(902_000_000, 1040) is None
    # The same range again is a repeat, which the database ignores.
    assert allow(902_000_000, 1040) is None
    assert allow(420_000_000, 1200) is None
    assert allow(144_000_000, 10) == "more than 2 ranges in one minute"
    # The next minute starts again; the bins are counted per minute too.
    later = minute + timedelta(minutes=1)
    assert (
        guard.allow_spectrum("tempe-roof", ("-", 1, 1, 4000), 1, 4000, 1, later, NOW)
        == "more than 3000 bins in one minute"
    )


def test_a_refused_range_is_never_stored() -> None:
    guard = _guard(refused=((851_000_000, 869_000_000),))
    minute = NOW.replace(second=0)
    touching = guard.allow_spectrum(
        "tempe-roof", ("-", 850_000_000, 50_000, 100), 850_000_000, 100, 50_000, minute, NOW
    )
    assert touching == "a range this sonoran does not store"
    clear = guard.allow_spectrum(
        "tempe-roof", ("-", 902_000_000, 50_000, 520), 902_000_000, 520, 50_000, minute, NOW
    )
    assert clear is None


def test_a_mod_gets_so_many_ids_a_day() -> None:
    guard = _guard(custom_max_ids=2)
    assert guard.allow_custom("tempe-roof", "m", ["a", "b", "c", "a"], NOW) == [
        True,
        True,
        False,
        True,
    ]
    # A new day starts the count again.
    assert guard.allow_custom("tempe-roof", "m", ["c"], NOW + timedelta(days=1)) == [True]


def test_the_limits_come_from_the_settings_and_a_bad_range_stops_the_start() -> None:
    settings = Settings(
        _env_file=None,
        rf_spectrum_max_ranges=3,
        rf_spectrum_refused_ranges="851000000:869000000",
    )
    limits = limits_from(settings)
    assert limits.spectrum_max_ranges == 3
    assert limits.refused == ((851_000_000, 869_000_000),)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, rf_spectrum_refused_ranges="869M:851M")


# --- What store_batch writes -------------------------------------------


class _Recorder:
    """A session that runs nothing and remembers which tables were written."""

    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def execute(self, statement: Any) -> Any:
        self.statements.append(statement)

        class _Result:
            rowcount = 1

        return _Result()

    def tables(self) -> list[str]:
        return [s.table.name for s in self.statements]


def _adsb(lat: float, lon: float, **extra: object) -> Batch:
    return Batch.model_validate(
        {
            "v": 1,
            "station": "tempe-roof",
            "kind": "adsb",
            "sent": NOW,
            "obs": [{"id": "a1b2c3", "t": NOW, "lat": lat, "lon": lon, **extra}],
        }
    )


async def test_a_quarantined_station_adds_nothing_to_a_shared_layer() -> None:
    guard = _guard()
    guard.set_trust({("tempe-roof", "*"): QUARANTINED})
    session = _Recorder()
    tally = await store_batch(session, _adsb(*NEAR), NOW, Rules(), guard)  # type: ignore[arg-type]
    assert tally.withheld == 1 and tally.stored == 1
    # Its own view keeps it.
    assert session.tables() == ["rf_heard"]


async def test_a_doubtful_point_is_counted_as_heard_and_placed_nowhere() -> None:
    session = _Recorder()
    tally = await store_batch(session, _adsb(41.9, -87.6), NOW, Rules(), _guard())  # type: ignore[arg-type]
    assert tally.doubtful == 1
    assert session.tables() == ["rf_heard"]
    values = session.statements[0].compile().params
    assert values["lat"] is None and values["lon"] is None


async def test_a_loud_claim_does_not_decide_a_shared_point() -> None:
    """The level a station reports is a number it chose (#324)."""
    session = _Recorder()
    await store_batch(session, _adsb(*NEAR, rssi_db=50), NOW, Rules(), _guard())  # type: ignore[arg-type]
    track = [s for s in session.statements if s.table.name == "rf_track"]
    assert track, "a plausible point from a new station is shared"
    for statement in track:
        assert "rssi_db <" not in str(statement.compile())


async def test_a_shared_point_is_never_later_than_we_received_it() -> None:
    ahead = NOW + timedelta(seconds=59)
    assert shared_time(ahead, NOW) == NOW
    assert shared_time(NOW - timedelta(seconds=5), NOW) == NOW - timedelta(seconds=5)
    session = _Recorder()
    batch = _adsb(*NEAR)
    batch = batch.model_copy(update={"obs": [batch.obs[0].model_copy(update={"t": ahead})]})
    await store_batch(session, batch, NOW, Rules(), _guard())  # type: ignore[arg-type]
    latest = next(s for s in session.statements if s.table.name == "rf_latest")
    assert latest.compile().params["t"] == NOW


async def test_a_mod_point_is_kept_under_its_station_and_mod() -> None:
    session = _Recorder()
    custom = _custom(
        [
            {"id": "here", "t": NOW, "heard_here": True, "lat": 1.0, "lon": 1.0},
            {"id": "there", "t": NOW, "lat": 33.5, "lon": -112.0},
            {"id": "nowhere", "t": NOW},
            {"id": "Not An Id", "t": NOW},
        ]
    )
    tally = await store_custom(session, custom, NOW, Rules(), _guard())  # type: ignore[arg-type]
    assert tally.stored == 3 and tally.rejected == 1
    assert set(session.tables()) == {"rf_custom"}
    rows = [s.compile().params for s in session.statements]
    assert [(r["placement"], r["lat"]) for r in rows] == [
        ("heard_here", None),
        ("reported", 33.5),
        ("none", None),
    ]
    assert {r["mod"] for r in rows} == {"lightning"}


# --- The ingest's log ----------------------------------------------------


def test_an_invalid_message_is_logged_once_an_hour_per_station(
    caplog: pytest.LogCaptureFixture,
) -> None:
    log = InvalidLog()
    with caplog.at_level(logging.INFO, logger="sonoran.rf.ingest"):
        assert log.note("rf/v1/tempe-roof/adsb", "bad", NOW)
        assert not log.note("rf/v1/tempe-roof/adsb", "bad", NOW + timedelta(minutes=5))
        assert log.note("rf/v1/other-roof/adsb", "bad", NOW)
        assert log.note("rf/v1/tempe-roof/adsb", "bad", NOW + timedelta(hours=1))
    assert "1 more since the last line" in caplog.records[-1].message


# --- The page, under node ------------------------------------------------


def _node() -> str:
    node = shutil.which("node")
    assert node, "node is not on PATH, so the page went unchecked. A skip looks like a pass."
    return node


# A document just big enough for `el()`. It records every element made,
# and has no `innerHTML`: setting one would be a finding.
FAKE_DOM = r"""
var made = [];
function Node(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.text = ''; }
Node.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
Node.prototype.append = function (...kids) { for (const k of kids) this.children.push(k); };
Object.defineProperty(Node.prototype, 'textContent', {
  set(v) { this.text = String(v); },
  get() { return this.text + this.children.map((c) => c.textContent).join(''); },
});
Object.defineProperty(Node.prototype, 'innerHTML', { set() { throw new Error('innerHTML set'); } });
Node.prototype.nodeType = 1;
var document = {
  createElement(tag) { const n = new Node(tag); made.push(n); return n; },
  createTextNode(t) { return { nodeType: 3, textContent: String(t) }; },
};
var window = globalThis;
"""


def _page(expression: str) -> Any:
    """Evaluate an expression against rf.js's text, range and mod helpers."""

    def part(start: str, end: str) -> str:
        return RF[RF.index(start) : RF.index(end)]

    script = "\n".join(
        [
            FAKE_DOM,
            part("  function el(tag", "  function altitudeColour("),
            part("  const ago = ", "  /* A point this far along"),
            part("  /* --- Spectrum (design 7.4, #324)", "  function drawWaterfall("),
            part("  /* A time in the reader's own clock", "  /* `datetime-local` wants"),
            part("  const MOD_CAP = ", "  function drawMods("),
            part("  /* A long value is shortened", "  function drawModTable("),
            f"console.log(JSON.stringify({expression}));",
        ]
    )
    done = subprocess.run(
        [_node(), "-e", script], capture_output=True, text=True, timeout=30, check=False
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_page_removes_exactly_what_sonoran_removes() -> None:
    """One list of invisible characters, kept in two languages, must agree."""
    removed_js = _page(
        "Array.from({length: 0x10000}, (_, i) => i)"
        ".filter((i) => i < 0xd800 || i > 0xdfff)"
        ".filter((i) => plainText(String.fromCharCode(i)) === '')"
    )
    removed_py = [
        i for i in range(0x10000) if not 0xD800 <= i <= 0xDFFF and INVISIBLE.match(chr(i))
    ]
    assert removed_js == removed_py
    assert plain_text("a‮b") == "ab"


def test_hostile_mod_text_shows_as_short_plain_text() -> None:
    """HTML, a script, a link, direction tricks, a built-in name, a long value."""
    result = _page(
        """(() => {
          const row = {
            station: 'tempe-roof', mod: 'adsb', id: '<img src=x onerror=alert(1)>',
            placement: 'reported', lat: 33.5, lon: -112,
            sent_t: '2026-10-05T12:00:00Z', received_at: new Date().toISOString(),
            meta: {
              script: '<script>alert(1)</script>',
              link: 'https://evil.example/login',
              bidi: 'gnp.\\u202eexe',
              long: 'x'.repeat(500),
              level_db: -42.25,
              label_db: 'loud',
            },
          };
          const tip = modTooltip(row);
          const cell = longText(modLines(row).join(' · '));
          return {
            text: tip.textContent,
            tags: [...new Set(made.map((n) => n.tagName))].sort(),
            attrs: made.flatMap((n) => Object.keys(n.attrs)),
            cell: cell.tagName,
            summary: cell.children[0].text.length,
          };
        })()"""
    )
    text = result["text"]
    assert "From a member's mod: adsb at tempe-roof" in text
    assert "Unverified" in text
    # Markup is shown as the characters it is.
    assert "<script>alert(1)</script>" in text
    assert "‮" not in text
    # Shortened on screen; the table keeps the whole value a click away.
    assert "x" * 100 not in text and "…" in text
    assert result["cell"] == "details" and result["summary"] <= 60
    # Units from the fixed list, never from the data.
    assert "level_db: -42.25 dB" in text
    assert "label_db: loud" in text and "loud dB" not in text
    # Nothing that could load, link or run.
    assert set(result["tags"]) <= {"div", "strong", "details", "summary", "span"}
    assert not {"href", "src", "style", "onerror"} & set(result["attrs"])


def test_a_range_is_titled_from_sonorans_numbers() -> None:
    assert _page("[rangeText(902e6, 928e6), rangeText(420e6, 1.2e9), rangeText(24e6, 6e9)]") == [
        "902\u2013928 MHz",
        "420 MHz\u20131.2 GHz",
        "24 MHz\u20136 GHz",
    ]
    assert _page("rangeTitle({f_start_hz: 420e6, f_end_hz: 450e6, name: 'evil<b>'})") == (
        "420\u2013450 MHz"
    )


def test_mesh_marks_are_drawn_only_over_the_mesh_band() -> None:
    channels = "band.channels = [{name: 'LongFast', low_hz: 906.75e6, high_hz: 907.0e6}];"
    assert (
        _page(
            f"(() => {{ {channels} return channelsIn("
            "{f_start_hz: 420e6, bin_hz: 25e3, bins: 1200}); })()"
        )
        == []
    )
    assert _page(
        f"(() => {{ {channels} return channelsIn({{f_start_hz: 902e6, bin_hz: 25e3, bins: 1040}})"
        ".map((c) => c.name); })()"
    ) == ["LongFast"]


def test_member_mods_start_hidden_with_their_own_mark() -> None:
    assert "shown: { stations: true, mods: false }" in RF
    assert "'data-option-default': String(layer.key !== 'mods')" in RF
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    assert ".rf-mod-mark" in css
    # Every mod is drawn with the one mark: the icon is never built from data.
    draw = RF[RF.index("  function drawMods(") : RF.index("  /* A switch per station")]
    assert "node.className = 'rf-mod-mark';" in draw
    assert "meta" not in draw.split("node.className")[0].split("for (const row of rows)")[-1]


def test_a_row_not_swept_is_grey_never_quiet() -> None:
    assert _page("[swept({minutes: 0, t: 'x'}), swept({minutes: 1, p50: [1]})]") == [False, True]
    assert "image.data.set(NOT_SWEPT, at)" in RF
