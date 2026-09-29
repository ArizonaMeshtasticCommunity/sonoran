"""The node page draws health and history without waiting on `routes` (#304).

`/api/nodes/{id}/routes` took 7 to 29 seconds uncached on s.azmsh.dev.
It was fetched in one `getAll` with `gaps` and `history`, so the health
panel and the charts, which need neither, waited for it too.
"""

import re
from pathlib import Path

APP_JS = Path(__file__).parents[2] / "src/sonoran/web/static/app.js"


def _load_node_detail() -> str:
    source = APP_JS.read_text(encoding="utf-8")
    start = source.index("async function loadNodeDetail(")
    end = source.index("\nPAGES.node = ", start)
    return source[start:end]


def test_routes_is_not_in_the_same_request_set_as_gaps_and_history() -> None:
    body = _load_node_detail()
    together = re.search(r"await getAll\(\[(.*?)\]\)", body, re.S)
    assert together is not None
    assert "/gaps" in together.group(1)
    assert "/routes" not in together.group(1)


def test_routes_is_asked_for_before_health_is_drawn_and_waited_for_after() -> None:
    body = _load_node_detail()
    asked = body.index("/routes?hours=")
    health = body.index("healthPanel(")
    history = body.index("drawNodeHistory(")
    links = body.index("routesPanel(")
    # Asked for first, so the slow request starts at once.
    assert asked < health
    # Drawn last, and only when it arrives.
    assert health < links
    assert history < links


def test_a_late_routes_answer_does_not_draw_over_another_node() -> None:
    body = _load_node_detail()
    links = body.index("routesPanel(")
    guard = body.rfind("if (currentNodeId !== nodeId) return;", 0, links)
    health = body.index("healthPanel(")
    assert guard > health, "the Links panel needs its own check after its own wait"
