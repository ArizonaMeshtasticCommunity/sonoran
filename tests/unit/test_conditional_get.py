"""Unchanged long-window answers are a 304 with no body (#371)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from sonoran.api.conditional import CACHE_CONTROL, ConditionalGetMiddleware, etag_of, matches


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/api/graph")
    def graph() -> dict[str, object]:
        return {"links": [1, 2, 3]}

    @app.get("/api/stats/broken")
    def broken() -> dict[str, object]:
        raise ValueError("boom")

    @app.get("/api/nodes")
    def nodes() -> list[int]:
        return [1]

    app.add_middleware(ConditionalGetMiddleware)
    return TestClient(app, raise_server_exceptions=False)


def test_a_listed_answer_carries_a_tag_and_asks_to_be_checked() -> None:
    response = _client().get("/api/graph")
    assert response.status_code == 200
    assert response.headers["etag"] == etag_of(response.content)
    assert response.headers["cache-control"] == CACHE_CONTROL
    assert response.json() == {"links": [1, 2, 3]}


def test_the_same_answer_again_is_a_304_with_no_body() -> None:
    client = _client()
    tag = client.get("/api/graph").headers["etag"]
    again = client.get("/api/graph", headers={"If-None-Match": tag})
    assert again.status_code == 304
    assert again.content == b""
    assert again.headers["etag"] == tag


def test_a_different_tag_gets_the_whole_answer() -> None:
    response = _client().get("/api/graph", headers={"If-None-Match": 'W/"other"'})
    assert response.status_code == 200
    assert response.json() == {"links": [1, 2, 3]}


def test_other_paths_and_errors_are_left_alone() -> None:
    client = _client()
    assert "etag" not in client.get("/api/nodes").headers
    failed = client.get("/api/stats/broken")
    assert failed.status_code == 500
    assert "etag" not in failed.headers


def test_tags_compare_weakly_and_in_lists() -> None:
    tag = 'W/"abc"'
    assert matches('"abc"', tag)
    assert matches('W/"x", W/"abc"', tag)
    assert matches("*", tag)
    assert not matches(None, tag)
    assert not matches('W/"abcd"', tag)
