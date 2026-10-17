"""The packet page reads by kind.

There is no JavaScript test runner in this project, so these pin the
rules that a later edit could drop without the page looking broken.
See docs/ARCHITECTURE.md 3.10.1.
"""

from sonoran.api.app import STATIC_DIR


def _app() -> str:
    return (STATIC_DIR / "app.js").read_text(encoding="utf-8")


def _page() -> str:
    app = _app()
    page = app[app.index("PAGES.packet = async (page) => {") :]
    return page[: page.index("\n};\n")]


def test_who_heard_it_comes_after_the_packet_and_before_the_raw_data() -> None:
    """Logan, 2026-10-17: who heard it, with every MQTT topic, goes to the
    bottom. It was first, from the UX batch (ec69728); the raw data stays
    last (test below)."""
    page = _page()
    assert page.index("decodedPanels(packet)") < page.index("envelopePanel(")
    assert page.index("envelopePanel(") < page.index("whoHeardPanel(")
    assert page.index("whoHeardPanel(") < page.index("rawPanel(data)")


def test_who_heard_it_names_the_relay_of_each_upload() -> None:
    app = _app()
    panel = app[app.index("function whoHeardPanel(") :]
    panel = panel[: panel.index("\n}\n")]
    assert "'Relayed by'" in panel
    assert "row.relayed_by" in panel
    assert "candidates" in panel


def test_the_raw_data_starts_open_and_comes_last() -> None:
    """The JSON is always on screen, and never the first thing read.

    It used to start closed, and a closed panel titled "Raw data" read as
    an empty one. It stays a `details`, so a reader can fold it away.
    """
    app = _app()
    raw = app[app.index("function rawPanel(") :]
    raw = raw[: raw.index("\n}\n")]
    assert "el('details'" in raw
    assert "open: true" in raw
    page = _page()
    assert page.index("decodedPanels(packet)") < page.index("rawPanel(data)")


def test_every_kind_the_api_decodes_has_a_heading() -> None:
    """A kind with no heading would fall back to a generic dump."""
    app = _app()
    kinds = app[app.index("const DECODED_KIND = {") :]
    kinds = kinds[: kinds.index("};")]
    for kind in ("text", "position", "neighbors", "device", "environment", "air_quality", "power"):
        assert f"{kind}:" in kinds, kind


def test_the_envelope_says_which_key_sealed_it() -> None:
    """`pki_encrypted` is stored, so the page shows it, and unknown stays unknown."""
    app = _app()
    envelope = app[app.index("function envelopePanel(") :]
    envelope = envelope[: envelope.index("\n}\n")]
    assert "packet.pki_encrypted == null" in envelope
    assert "'not recorded'" in envelope


def test_an_ack_is_never_claimed_to_have_arrived() -> None:
    """Only the request is stored. See docs/ARCHITECTURE.md 3.10.1."""
    app = _app()
    envelope = app[app.index("function envelopePanel(") :]
    envelope = envelope[: envelope.index("\n}\n")]
    assert "Whether one came back is not recorded." in envelope
