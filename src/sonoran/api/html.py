"""Putting values into a page safely.

Both documents this service serves — the dashboard and the embed — take
their configuration as a JSON object written into an inline `<script>`.
That is a small hole unless the JSON is escaped for the place it lands
in, and this module is the one function that does it.
"""

import json
from typing import Any

# What has to be escaped, and why each one.
#
# An HTML parser reading a `<script>` element looks for `</script`, and
# it does not care that the sequence is inside a JavaScript string. A
# configured value holding one would close the element, and everything
# after it would be markup on the page. `<` alone is enough to stop
# that; `>` and `&` cost nothing and remove the whole class.
#
# The result is still valid JSON, because a JavaScript string may hold
# any character as a `\uXXXX` escape.
_ESCAPES = {"<": "\\u003c", ">": "\\u003e", "&": "\\u0026"}


def as_script_json(value: Any) -> str:
    """Return a value as JSON that is safe inside a `<script>` element."""
    text = json.dumps(value)
    for character, escape in _ESCAPES.items():
        text = text.replace(character, escape)
    return text
