"""A reported neighbour is named, not numbered (#240).

A neighbour report says which nodes the sender heard, and
`neighbor_metrics` stores each one as a node number because that is all
the packet carried. The packet page printed those numbers -- `!0a51a002`
-- in a table sitting a few centimetres below "Who heard it", which
printed "Usery Pass Relay" for the same node. Two answers to the same
question, on one screen.

The fix is one join in the API and one cell in the browser, so the tests
come in two halves:

* The API half runs `_decoded_payload` against a stand-in session. It
  proves the names are added for a neighbour report, that the stored
  columns survive, and that no other decoded family pays for the extra
  query.
* The browser half runs `tests/unit/js/neighbour_names_cases.mjs` under
  node, with mutation controls. Source text cannot tell you that a cell
  reads `neighbor_name` and then uses it: the bug this fixes was a cell
  that built the ID correctly and handed it over as the display name.

The spelling is the other half of the issue. "Neighbour" was deliberate
once -- `labels.js` recorded the reason -- so the sentences that a reader
sees now say "neighbor" and the names that a machine reads
(`neighbor_metrics`, `neighbor_node_num`, `NEIGHBORINFO_APP`) keep the
protocol's own spelling.
"""

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from sonoran.api.routes.packets import _decoded_payload, _named_neighbours
from sonoran.db.models import DeviceMetrics, NeighborMetrics, Packet
from sonoran.meshtastic import portnums_pb2

ROOT = Path(__file__).resolve().parents[2]
APP_JS = ROOT / "src" / "sonoran" / "web" / "static" / "app.js"
CASES = ROOT / "tests" / "unit" / "js" / "neighbour_names_cases.mjs"

REPORTER = 173121537
NEIGHBOUR = 173121538
STRANGER = 3735928559  # Above 2^31, so a signed 32-bit read of it is negative.
PACKET_ID = 100074


# --- The API half --------------------------------------------------


class _Result:
    """What `session.scalars` and `session.execute` both return here."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    """Enough of an `AsyncSession` for the read under test.

    `_decoded_payload` makes exactly two kinds of call: `scalars` for the
    decoded rows of one family, and -- through `resolve_names` --
    `execute` for the node table. Counting the second one is the point:
    a family that points at no other node must not buy a name query.
    """

    def __init__(self, decoded: list[Any], nodes: list[tuple[int, str | None, str | None]]) -> None:
        self._decoded = decoded
        self._nodes = nodes
        self.name_queries = 0

    async def scalars(self, statement: Any) -> _Result:
        return _Result(self._decoded)

    async def execute(self, statement: Any) -> _Result:
        self.name_queries += 1
        return _Result(list(self._nodes))


def _packet(portnum: int) -> Packet:
    return Packet(from_node_num=REPORTER, packet_id=PACKET_ID, portnum=portnum)


def _report(neighbor: int, snr: float) -> NeighborMetrics:
    return NeighborMetrics(
        node_num=REPORTER,
        packet_id=PACKET_ID,
        neighbor_node_num=neighbor,
        channel="LongFast",
        snr=snr,
    )


async def _reported(
    nodes: list[tuple[int, str | None, str | None]],
) -> list[dict[str, object]]:
    """The rows `/api/packets/{from}/{id}` would return for one report.

    Two reported neighbours: the one the caller describes in `nodes`, and
    one no node-info packet has ever named.
    """
    session = _Session([_report(NEIGHBOUR, -6.25), _report(STRANGER, -18.5)], nodes)
    payload = await _decoded_payload(session, _packet(portnums_pb2.NEIGHBORINFO_APP))  # type: ignore[arg-type,attr-defined]
    assert payload is not None, "a neighbour report with stored rows decoded to nothing"
    assert payload["kind"] == "neighbors"
    values = payload["values"]
    assert isinstance(values, list) and len(values) == 2
    for row in values:
        assert isinstance(row, dict)
        assert "neighbor_name" in row and "neighbor_id" in row, (
            f"the API sent a reported neighbour with no name to print: {row}"
        )
    return values


@pytest.mark.asyncio
async def test_a_reported_neighbour_carries_its_long_name() -> None:
    """The whole of #240 in one assertion."""
    named, _ = await _reported([(NEIGHBOUR, "Usery Pass Relay", "USRY")])
    assert named["neighbor_name"] == "Usery Pass Relay"
    assert named["neighbor_id"] == "!0a51a002"


@pytest.mark.asyncio
async def test_a_neighbour_with_no_long_name_falls_back_to_the_short_one() -> None:
    """`display_name` prefers the long name and then the short one.

    The issue asks for the long name "if available". A node that sent a
    short name and no long one has a readable name too, and the ID is
    the last resort rather than the second one.
    """
    named, _ = await _reported([(NEIGHBOUR, None, "USRY")])
    assert named["neighbor_name"] == "USRY"


@pytest.mark.asyncio
async def test_an_unknown_neighbour_falls_back_to_its_node_id() -> None:
    """The other half of the request: no name, so print the ID.

    A neighbour this dashboard has never seen a node-info packet from is
    absent from the node table. `name_of` answers with the ID form, so
    the browser needs no fallback rule of its own.
    """
    _, stranger = await _reported([(NEIGHBOUR, "Usery Pass Relay", "USRY")])
    assert stranger["neighbor_name"] == "!deadbeef", (
        "an unnamed neighbour must read as its ID, and a node number above "
        "2^31 must still format as eight hex digits"
    )
    assert stranger["neighbor_id"] == "!deadbeef"


@pytest.mark.asyncio
async def test_naming_a_neighbour_does_not_drop_what_it_measured() -> None:
    """The SNR is the reason the table exists. It must survive the join."""
    named, _ = await _reported([(NEIGHBOUR, "Usery Pass Relay", "USRY")])
    assert named["snr"] == pytest.approx(-6.25), f"the reading did not survive: {named}"
    assert named["channel"] == "LongFast"
    # The raw panel shows the row as the database holds it, so the number
    # stays beside the name rather than replacing it.
    assert named["neighbor_node_num"] == NEIGHBOUR


@pytest.mark.asyncio
async def test_no_other_decoded_family_pays_for_the_name_query() -> None:
    """Device telemetry points at no second node, so it asks for no name.

    Without this, the tidy-looking refactor is to name every decoded row
    and add a query to every telemetry packet page on the site.
    """
    session = _Session(
        [DeviceMetrics(node_num=REPORTER, packet_id=PACKET_ID, battery_level=80)], []
    )
    payload = await _decoded_payload(session, _packet(portnums_pb2.TELEMETRY_APP))  # type: ignore[arg-type,attr-defined]
    assert payload is not None
    assert payload["kind"] == "device"
    assert session.name_queries == 0, (
        f"a device telemetry packet asked the node table {session.name_queries} time(s) "
        "for a name it has nothing to name"
    )
    values = payload["values"]
    assert isinstance(values, list)
    assert "neighbor_name" not in values[0], (
        f"a device reading was given a neighbour name: {values[0]}"
    )


def test_a_row_without_the_number_is_passed_through_not_dropped() -> None:
    """The column is NOT NULL, so this cannot happen from the database.

    It is guarded anyway, and the guard turned out to earn its place
    twice. `_node_id(None)` is `^all` and `name_of(names, None)` is
    "Everyone", so without the guard a row with no number would not raise
    -- it would quietly claim the node reported hearing *the broadcast
    address*. A crash is visible; that is not.
    """
    rows = _named_neighbours([{"snr": -6.25}], {})
    assert rows == [{"snr": -6.25}], (
        f"a row with no node number came back as {rows} instead of untouched"
    )


# --- The browser half ----------------------------------------------


@contextmanager
def _temporarily(path: Path, text: str) -> Iterator[None]:
    original = path.read_text(encoding="utf-8")
    path.write_text(text, encoding="utf-8")
    try:
        yield
    finally:
        path.write_text(original, encoding="utf-8")


def _node() -> str:
    node = shutil.which("node")
    assert node, (
        "node is not on PATH, so the packet page went unchecked. It is not "
        "optional: this repo already requires node for the e2e suite and "
        "the dev server, and a skip here looks exactly like a pass."
    )
    return node


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [_node(), str(CASES)], capture_output=True, text=True, timeout=60, cwd=ROOT
    )


def test_the_cases_and_the_page_are_both_there() -> None:
    """The control, so a missing file fails as itself."""
    assert APP_JS.exists(), f"{APP_JS} is missing"
    assert CASES.exists(), f"{CASES} is missing"


def test_the_browser_names_each_reported_neighbour() -> None:
    """The positive arm: the cell reads the name and prints it."""
    done = _run()
    assert done.returncode == 0, done.stdout + done.stderr


def test_printing_the_id_as_the_name_would_be_caught() -> None:
    """The exact bug #240 reported, put back on purpose.

    This is what the cell did before: build the ID, then pass it as the
    display name, so the name the API sends is read and discarded. It is
    also the shape a careless merge would restore.
    """
    source = APP_JS.read_text(encoding="utf-8")
    anchor = "        return nodeChip({ node_id: id, display_name: row.neighbor_name || id });"
    assert anchor in source, (
        "the neighbour cell has moved, so this control is checking nothing. "
        "A mutation that does not apply is indistinguishable from one the "
        "cases survive."
    )
    broken = source.replace(
        anchor, "        return nodeChip({ node_id: id, display_name: id });", 1
    )
    with _temporarily(APP_JS, broken):
        done = _run()
    assert done.returncode != 0, (
        "the cases pass with the neighbour cell printing the node ID as the "
        "display name, which is the bug #240 reported"
    )


def test_dropping_the_id_fallback_would_be_caught() -> None:
    """The guard behind the guard.

    `neighbor_name` always arrives today, so a row that carries none is
    a cached or hand-made one. Trusting the field blindly turns such a
    row into an empty chip, which reads as a rendering failure rather
    than as a node.
    """
    source = APP_JS.read_text(encoding="utf-8")
    anchor = """        const id = row.neighbor_id
          || `!${(row.neighbor_node_num >>> 0).toString(16).padStart(8, '0')}`;"""
    assert anchor in source, "the ID fallback has moved; this control is checking nothing"
    broken = source.replace(anchor, "        const id = row.neighbor_id;", 1)
    with _temporarily(APP_JS, broken):
        done = _run()
    assert done.returncode != 0, (
        "the cases pass with the ID fallback gone, so a row the API sent "
        "without one would render a chip with no text in it"
    )


def test_the_british_spelling_coming_back_would_be_caught() -> None:
    """The second half of #240, and the half most likely to regress.

    Most of this file's neighbour identifiers are still British, because
    they are names and not words. That makes "Neighbours it reported"
    look like it belongs, which is exactly why it needs a test.
    """
    source = APP_JS.read_text(encoding="utf-8")
    anchor = "  neighbors: 'Neighbors it reported',"
    assert anchor in source, "the panel heading has moved; this control is checking nothing"
    broken = source.replace(anchor, "  neighbors: 'Neighbours it reported',", 1)
    with _temporarily(APP_JS, broken):
        done = _run()
    assert done.returncode != 0, (
        "the cases pass with the packet page heading spelled 'Neighbours', "
        "so the spelling half of #240 is not tested"
    )
