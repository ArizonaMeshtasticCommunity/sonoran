"""The protobuf schema is fetched when a config is read, not before.

`meshtastic-static.js` is 408 kB -- larger than `app.js` -- and it
arrived through `config-check.js`'s import graph on EVERY page, because
that module is loaded unconditionally. Most visitors never open the
Config check tab.

Compression takes it to about 27 kB on the wire, so the transfer
argument is largely gone since gzip landed. The parse cost is not, and
it is paid on a phone by everybody.

Measured against a local harness serving these files:

    on the dashboard                 0 requests
    after opening #config            0 requests
    after "Build a new config"       1 request, 18 checks rendered
    after uploading a YAML config    1 request, 22 checks rendered
    js errors: none
"""

import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "sonoran" / "web" / "static"
SOURCE = (STATIC / "config-check.js").read_text(encoding="utf-8")


def test_the_schema_is_not_a_top_level_import() -> None:
    """A static import is fetched and parsed whether or not it is used."""
    assert not re.search(r"^import .*meshtastic-static", SOURCE, re.M), (
        "meshtastic-static.js is imported at the top of config-check.js, so every page pays for it"
    )
    assert "import('./meshtastic-static.js')" in SOURCE, (
        "there is no dynamic import, so the schema is never loaded at all"
    )


def test_every_path_that_parses_waits_for_the_schema() -> None:
    """The await belongs at the entry points, not inside the override.

    The vendored parser calls `Root.fromJSON().lookupType()`
    synchronously, so the types have to be installed BEFORE parsing
    starts. There are two ways in -- reading a file, and building a
    config from scratch -- and both need it.
    """
    for entry, needs in (
        ("async function loadFile(", "ConfigParser.parse"),
        ("data-config-new", "ConfigFixer.buildNewConfig"),
    ):
        start = SOURCE.index(entry)
        body = SOURCE[start : start + 900]
        assert needs in body, f"the {entry!r} path no longer looks like it parses"
        call = body.index(needs)
        wait = body.find("await ready()")
        assert 0 <= wait < call, (
            f"the {entry!r} path parses without waiting for the schema, so "
            f"lookupType runs against the un-overridden protobuf root"
        )


def test_the_schema_is_only_fetched_once() -> None:
    """Two files dropped at once must not fetch 408 kB twice."""
    start = SOURCE.index("function ready()")
    body = SOURCE[start : start + 400]
    assert "if (!typesReady)" in body, (
        "ready() does not hold its promise, so concurrent callers each start their own import"
    )
