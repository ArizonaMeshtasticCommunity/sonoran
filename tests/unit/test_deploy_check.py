"""`tools/deploy_check.py` fails the deploy of 2026-10-07, and passes a good one."""

from typing import Any

from tools.deploy_check import compare


def _snapshot(ranges: dict[str, int], swept_6h: int, status: int = 200) -> dict[str, Any]:
    return {
        "status": {"/health": 200, "/api/rf/spectrum/surprise-white-tanks?hours=6": status},
        "counts": {"rf.stations": 1, "stats.packet_count": 729_619},
        "spectrum": {"surprise-white-tanks": {"ranges": ranges, "swept_6h": swept_6h}},
    }


BEFORE = _snapshot({"-:902000000:25000:1040": 4074}, 180)


def _failures(after: dict[str, Any]) -> list[str]:
    return [message for level, message in compare(BEFORE, after) if level == "FAIL"]


def test_the_history_hidden_behind_a_new_range_fails() -> None:
    """What revision 0020 did: the history under `-`, new minutes under `pi5`.

    Nothing was deleted, so the minutes in all ranges hold. The page opens
    on the newest range, one minute long, and that is what fails.
    """
    after = _snapshot({"pi5:902000000:25000:1040": 1, "-:902000000:25000:1040": 4074}, 1)
    results = compare(BEFORE, after)
    assert _failures(after) == ["spectrum surprise-white-tanks swept_6h: was 180, now 1"]
    assert any(level == "warn" and "split in two" in text for level, text in results)


def test_the_same_history_under_its_real_source_passes() -> None:
    after = _snapshot({"pi5:902000000:25000:1040": 4075}, 180)
    assert _failures(after) == []


def test_an_endpoint_that_stops_answering_fails() -> None:
    after = _snapshot({"pi5:902000000:25000:1040": 4075}, 180, status=500)
    assert _failures(after) == ["/api/rf/spectrum/surprise-white-tanks?hours=6: was 200, now 500"]


def test_a_station_or_a_count_that_disappears_fails() -> None:
    after = _snapshot({}, 180)
    after["spectrum"] = {}
    after["counts"] = {"stats.packet_count": 729_700}
    assert sorted(_failures(after)) == [
        "rf.stations: was 1, now missing",
        "spectrum surprise-white-tanks: no longer listed",
    ]
