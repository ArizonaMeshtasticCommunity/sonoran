"""Whether a node's firmware is behind the stable release (#406).

The versions here are the ones a 20-minute sample of `msh/US/AZ/#` saw
in map reports on 2026-11-19, against the stable release that
`api.meshtastic.org/github/firmware/list` named that day
(`v2.7.26.54e0d8d`). See docs/DECISIONS.md.
"""

import pytest

from sonoran.firmware import (
    clean_reported_version,
    firmware_status,
    parse_version,
    stable_from_release_list,
)

STABLE = "2.7.26.54e0d8d"


@pytest.mark.parametrize(
    ("reported", "expected"),
    [
        ("2.6.11.60ec05e", "behind"),
        ("2.6.4.b89355f", "behind"),
        ("2.7.16.a597230", "behind"),
        ("2.7.26.54e0d8d", "current"),
        # Same release, another build: still that release.
        ("2.7.26.0000000", "current"),
        ("2.8.1.8e6a88d", "newer"),
        ("2.8.0.47db0e3", "newer"),
        ("2.8.3.a8f6f58", "newer"),
    ],
)
def test_the_sampled_versions(reported: str, expected: str) -> None:
    assert firmware_status(reported, STABLE) == expected


def test_numbers_compare_as_numbers_not_text() -> None:
    """'2.7.9' sorts after '2.7.26' as text. As a version it is older."""
    assert firmware_status("2.7.9.abcdef0", STABLE) == "behind"
    assert firmware_status("2.10.0.abcdef0", STABLE) == "newer"


def test_no_report_is_unknown() -> None:
    assert firmware_status(None, STABLE) == "unknown"
    assert firmware_status("", STABLE) == "unknown"


def test_a_version_we_cannot_read_is_unknown_not_behind() -> None:
    for text in ("garbage", "2", "2.7", "v", "2.x.1"):
        assert firmware_status(text, STABLE) == "unknown", text


def test_no_stable_release_known_is_unknown() -> None:
    """Before the first fetch, or when it has always failed."""
    assert firmware_status("2.6.4.b89355f", None) == "unknown"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2.7.26.54e0d8d", (2, 7, 26)),
        ("v2.7.26.54e0d8d", (2, 7, 26)),
        ("2.7.26", (2, 7, 26)),
        # A local build can add a suffix to the hash.
        ("2.5.20.4c97351-d", (2, 5, 20)),
        (" 2.7.15.567b8ea ", (2, 7, 15)),
    ],
)
def test_parse_version(text: str, expected: tuple[int, int, int]) -> None:
    assert parse_version(text) == expected


def test_a_reported_version_is_kept_only_when_it_is_short_and_printable() -> None:
    assert clean_reported_version(" 2.7.26.54e0d8d ") == "2.7.26.54e0d8d"
    assert clean_reported_version("") is None
    assert clean_reported_version("2.7\x00.26") is None
    assert clean_reported_version("2." + "7" * 100) is None


LIST = {
    "releases": {
        "stable": [
            {
                "id": "v2.7.26.54e0d8d",
                "title": "Meshtastic Firmware 2.7.26.54e0d8d Beta",
                "page_url": "https://github.com/meshtastic/firmware/releases/tag/v2.7.26.54e0d8d",
            },
            {"id": "v2.7.15.567b8ea", "title": "Meshtastic Firmware 2.7.15.567b8ea Beta"},
        ],
        "alpha": [{"id": "v2.8.2.d5f1619", "title": "Meshtastic Firmware 2.8.2.d5f1619 Alpha"}],
    },
    "pullRequests": [],
}


def test_stable_is_the_first_stable_entry_not_the_alpha() -> None:
    release = stable_from_release_list(LIST)
    assert release is not None
    assert release.version == "2.7.26.54e0d8d"
    assert release.page_url.endswith("/v2.7.26.54e0d8d")


def test_stable_is_the_newest_even_when_the_list_is_out_of_order() -> None:
    """Would catch an implementation that trusts the list order."""
    shuffled = {"releases": {"stable": list(reversed(LIST["releases"]["stable"]))}}
    release = stable_from_release_list(shuffled)
    assert release is not None
    assert release.version == "2.7.26.54e0d8d"


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"releases": {}},
        {"releases": {"stable": []}},
        {"releases": {"stable": [{"id": "not-a-version"}]}},
        {"releases": {"stable": "nope"}},
        [],
    ],
)
def test_a_list_we_cannot_read_gives_no_stable_release(body: object) -> None:
    assert stable_from_release_list(body) is None


def test_a_page_url_off_github_is_replaced() -> None:
    """The link goes on our page. Only a meshtastic/firmware URL is kept."""
    body = {
        "releases": {
            "stable": [{"id": "v2.7.26.54e0d8d", "page_url": "https://evil.example/x"}],
        }
    }
    release = stable_from_release_list(body)
    assert release is not None
    assert release.page_url == (
        "https://github.com/meshtastic/firmware/releases/tag/v2.7.26.54e0d8d"
    )
