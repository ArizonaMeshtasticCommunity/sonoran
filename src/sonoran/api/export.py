"""Write the node list as a CSV or JSON file (#350).

This module only formats rows. It reads nothing. The rows come from
`routes/nodes.py`, which builds them with the same query as the list,
so the file holds what the screen shows.

**No column adds a field.** Each export column is a column the node
list draws, and each one writes fields of `NodeSummary`, the model the
list already returns. A column the list does not draw cannot be asked
for. The list shows no coordinates, so the file holds none.

**A cell cannot become a formula.** A node name is typed by whoever
owns the node. Excel, LibreOffice and Google Sheets run a cell that
starts with `=`, `+`, `-` or `@` as a formula, and a tab or a carriage
return at the start can hide one. `safe_cell` puts `'` before such a
cell. This is the OWASP advice for CSV injection. The JSON file is not
changed, because nothing evaluates it and its values must equal the
values of the list.
"""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from datetime import datetime

from sonoran.api.schemas import NodeSummary

# The most rows one file holds. The whole Arizona mesh was 2,372 nodes
# when this was written, so this ceiling is far above any real export.
# Over it, the route refuses and does not cut the file: a file that
# stops at a cap and does not say so is a file that lies about the mesh.
EXPORT_LIMIT = 10_000

# The columns of the node list, by the key the page sends, and what each
# one writes: a heading for the CSV and a `NodeSummary` field. A screen
# column that holds two facts writes two file columns. "Node" shows the
# name and the short name. "Flags" shows a gateway tag and a position
# tag.
COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "name": (("Name", "display_name"), ("Short name", "short_name")),
    "node_id": (("Node ID", "node_id"),),
    "hw": (("Hardware", "hw_model"),),
    "role": (("Role", "role"),),
    "flags": (("Gateway", "is_mqtt_gateway"), ("Position", "has_position")),
    "last_heard": (("Last heard", "last_heard"),),
}

# The order of the screen, used when the caller names no columns.
DEFAULT_COLUMNS: tuple[str, ...] = tuple(COLUMNS)

# The characters that make a spreadsheet read a cell as a formula.
FORMULA_LEADS = ("=", "+", "-", "@", "\t", "\r")

# A byte order mark, so Excel opens the file as UTF-8. Without it, Excel
# reads a name with an emoji or an accent as nonsense, and node names
# often have both.
BOM = "﻿"


def parse_columns(raw: str | None) -> tuple[str, ...]:
    """Read the `columns` parameter. Raise ValueError for a bad one.

    The order is kept: the page sends its columns in the order it draws
    them. An unknown name and a repeated name are refused, not dropped,
    so a caller is never given a file that differs from what it asked
    for without being told.
    """
    if not raw:
        return DEFAULT_COLUMNS
    names = tuple(part.strip() for part in raw.split(","))
    for name in names:
        if name not in COLUMNS:
            raise ValueError(f"columns must be from: {', '.join(COLUMNS)}")
    if len(set(names)) != len(names):
        raise ValueError("a column is named twice")
    return names


def fields(columns: Sequence[str]) -> list[tuple[str, str]]:
    """Return the (heading, field) pairs of the columns, in order."""
    return [pair for name in columns for pair in COLUMNS[name]]


def safe_cell(value: str) -> str:
    """Return a text cell that a spreadsheet cannot run as a formula."""
    return "'" + value if value.startswith(FORMULA_LEADS) else value


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return safe_cell(str(value))


def _values(row: NodeSummary, pairs: Sequence[tuple[str, str]]) -> dict[str, object]:
    """The fields of one row as the list's JSON writes them.

    `mode="json"` is the serialisation `/api/nodes` uses, so a time in
    the file is the same text as the time in the list's answer.
    """
    dumped = row.model_dump(mode="json")
    return {field: dumped[field] for _, field in pairs}


def to_csv(rows: Sequence[NodeSummary], columns: Sequence[str]) -> str:
    """Return the rows as RFC 4180 CSV, with a heading row."""
    pairs = fields(columns)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow([heading for heading, _ in pairs])
    for row in rows:
        values = _values(row, pairs)
        writer.writerow([_cell(values[field]) for _, field in pairs])
    return BOM + out.getvalue()


def to_json(rows: Sequence[NodeSummary], columns: Sequence[str]) -> str:
    """Return the rows as a JSON array of objects, fields in column order."""
    pairs = fields(columns)
    return json.dumps([_values(row, pairs) for row in rows], ensure_ascii=False)


def filename(extension: str, now: datetime) -> str:
    """The name the browser saves the file under, stamped in UTC."""
    return f"sonoran-nodes-{now:%Y%m%d-%H%M%S}Z.{extension}"
