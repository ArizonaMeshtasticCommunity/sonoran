"""The helpers that keep user input out of the query's grammar.

A node ID that cannot be parsed is a bad request. A search term is a
string to look for, not a pattern to run.
"""

import pytest
from fastapi import HTTPException

from sonoran.api.dependencies import LIKE_ESCAPE, contains, require_node_num


class TestRequireNodeNum:
    def test_it_parses_the_documented_forms(self) -> None:
        assert require_node_num("!00002501") == 9473
        assert require_node_num("0x2501") == 9473
        assert require_node_num("9473") == 9473

    @pytest.mark.parametrize("value", ["nonsense", "!zzzz", "", "!", "!!!"])
    def test_it_answers_422_rather_than_raising(self, value: str) -> None:
        """ValueError out of a handler reaches the client as a 500."""
        with pytest.raises(HTTPException) as caught:
            require_node_num(value)
        assert caught.value.status_code == 422


class TestContains:
    def test_a_plain_term_matches_anywhere(self) -> None:
        assert contains("ridge") == "%ridge%"

    def test_a_percent_is_a_character_to_find(self) -> None:
        """`%` alone matched every row, which is a full scan on request."""
        assert contains("%") == "%\\%%"

    def test_an_underscore_is_a_character_to_find(self) -> None:
        """`a_b` matched `axb`: wrong, and quietly so."""
        assert contains("a_b") == "%a\\_b%"

    def test_a_backslash_is_escaped_before_the_wildcards(self) -> None:
        """Escaping in the wrong order turns one backslash into an escape."""
        assert contains("a\\b") == "%a\\\\b%"
        assert contains("\\%") == "%\\\\\\%%"

    def test_the_escape_character_is_a_single_backslash(self) -> None:
        assert LIKE_ESCAPE == "\\"
