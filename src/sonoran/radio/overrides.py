"""The radio facts an operator knows and the mesh cannot report.

A node says what it is. It does not say what antenna is on it, how high
that antenna stands, or what power it transmits with. Somebody knows,
and this file is where they write it down.

The file is in the repository, so every change to it has an author, a
date, and a review. Nothing here needs a login or a write endpoint. The
API stays read-only. See `AGENTS.md` 4.

The format is YAML:

    nodes:
      "!a1b2c3d4":
        antenna_gain_dbi: 5.8
        antenna_height_m: 12.0
        tx_power_dbm: 30
        cable_loss_db: 1.5
        above_clutter: true
        lock_calibration: false
        note: "Rooftop omni, measured 2026-03."

Every key is optional. A key that is absent falls back to the hardware
default. A file that is absent gives no overrides at all, which is a
working state and not an error.

A `latitude` and `longitude` place a coverage site (#315). They are
read by the coverage job and the calibration fit only; no page shows
them. Each entry is checked when the file is read: a node ID that is
not `!` and eight hexadecimal digits, half a position, and a position
that is not a place are refused, each with a log line that names the
node.
"""

import re
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from sonoran.logging import get_logger
from sonoran.positions import is_usable

logger = get_logger(__name__)

# The bounds each value must sit in.
#
# The bounds are wide. They exist to catch a typed mistake, such as a
# height in feet or a power in watts, and not to hold an opinion about
# how a node should be built.
_BOUNDS: dict[str, tuple[float, float]] = {
    "antenna_gain_dbi": (-10.0, 30.0),
    "antenna_height_m": (0.0, 500.0),
    "tx_power_dbm": (-10.0, 40.0),
    "cable_loss_db": (0.0, 20.0),
    "latitude": (-90.0, 90.0),
    "longitude": (-180.0, 180.0),
}


@dataclass(frozen=True)
class NodeOverride:
    """What an operator says about one node.

    Every field is optional. None means "no opinion, use the default".
    """

    # Where the node really is.
    #
    # The public Meshtastic broker reduces the precision of a position
    # it relays, and most of a mesh backbone arrives at 13 bits, which
    # is about 2.9 km. A footprint drawn around that describes ground
    # that may have no radio on it, so such a node is not a site.
    #
    # An operator knows where their own router is. A position given
    # here is treated as exact, whatever the broker said, and the node
    # becomes a site again. Both values are needed; one alone is
    # ignored. See `sonoran/positions.py`.
    latitude: float | None = None
    longitude: float | None = None
    antenna_gain_dbi: float | None = None
    antenna_height_m: float | None = None
    tx_power_dbm: float | None = None
    cable_loss_db: float | None = None
    # True when the antenna stands above the roofs and the trees around
    # it. A node on a tower or a ridge does not take the clutter loss
    # that a node at street level takes.
    above_clutter: bool | None = None
    # True holds the profile against the calibration job. Use it for a
    # node whose build is known exactly, or one whose measurements are
    # known to be misleading.
    #
    # The fit holds such a node at zero while it solves, so it anchors
    # the other offsets and the model bias is measured against it. It is
    # not an offset that is fitted and then dropped. See
    # `sonoran/coverage/calibrate.py`.
    lock_calibration: bool = False
    note: str = ""


@dataclass(frozen=True)
class Overrides:
    """Every override in the file, by node ID."""

    nodes: dict[str, NodeOverride]

    def for_node(self, node_id: str) -> NodeOverride:
        """Return the override for a node, or an empty one."""
        return self.nodes.get(node_id, NodeOverride())

    def position_of(self, node_id: str) -> tuple[float, float] | None:
        """Return the position an operator gave for a node, if any.

        Both values are needed. A latitude with no longitude is a typing
        mistake, not a place, and using half of it would put the node on
        the Greenwich meridian.
        """
        override = self.for_node(node_id)
        if override.latitude is None or override.longitude is None:
            return None
        return (override.latitude, override.longitude)


EMPTY = Overrides(nodes={})

_FIELD_NAMES = {field.name for field in fields(NodeOverride)}


def _number(node_id: str, key: str, value: object) -> float | None:
    """Return a checked number, or None when it cannot be used."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        logger.warning("override %s.%s is not a number, ignored: %r", node_id, key, value)
        return None
    low, high = _BOUNDS[key]
    if not low <= float(value) <= high:
        logger.warning(
            "override %s.%s is %s, outside %s to %s, ignored", node_id, key, value, low, high
        )
        return None
    return float(value)


def _flag(node_id: str, key: str, value: object) -> bool | None:
    """Return a checked boolean, or None when it cannot be used."""
    if not isinstance(value, bool):
        logger.warning("override %s.%s is not true or false, ignored: %r", node_id, key, value)
        return None
    return value


def _one_node(node_id: str, raw: object) -> NodeOverride:
    """Return the override for one node from its part of the file."""
    if not isinstance(raw, dict):
        logger.warning("override %s is not a mapping, ignored", node_id)
        return NodeOverride()

    values: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in _FIELD_NAMES:
            logger.warning("override %s has an unknown key, ignored: %s", node_id, key)
            continue
        checked: object
        if key in _BOUNDS:
            checked = _number(node_id, key, value)
        elif key in {"above_clutter", "lock_calibration"}:
            checked = _flag(node_id, key, value)
        else:
            checked = str(value)
        if checked is not None:
            values[key] = checked

    _check_position(node_id, values)
    # `lock_calibration` is not optional on the dataclass, so a bad
    # value must not reach it as None.
    values.setdefault("lock_calibration", False)
    return NodeOverride(**values)


def _check_position(node_id: str, values: dict[str, Any]) -> None:
    """Take a position that is not a place out of one entry.

    A position here makes a node a coverage site (#315), so a mistake in
    one is refused when the file is read, with a line that names the
    node. The rest of the entry is a set of radio facts and is kept.

    Half a position is refused. That includes the half a bad value
    leaves behind: a longitude out of range is dropped above, and the
    latitude must then go with it. So is a pair that `is_usable` refuses,
    such as Null Island, which is what an unset position reads as.
    """
    latitude = values.get("latitude")
    longitude = values.get("longitude")
    if latitude is None and longitude is None:
        return
    if latitude is None or longitude is None:
        logger.warning(
            "override %s gives a latitude or a longitude but not both, so its position is ignored",
            node_id,
        )
    elif not is_usable(latitude, longitude):
        logger.warning(
            "override %s position %s, %s is not a place a node can be, so it is ignored",
            node_id,
            latitude,
            longitude,
        )
    else:
        return
    values.pop("latitude", None)
    values.pop("longitude", None)


# What a node ID looks like: `!` and eight hexadecimal digits, the form
# the node page prints and every table keys a node by.
NODE_ID = re.compile(r"![0-9a-f]{8}")


def _node_id(raw: object) -> str | None:
    """Return a node ID in the form the job looks it up by, or None.

    Capitals are accepted and lowered, because a person types them. Any
    other form is refused with a line that names it: an entry under a
    name no node has would never be used, and nothing would say so.
    """
    text = str(raw).strip().lower()
    if NODE_ID.fullmatch(text):
        return text
    logger.warning(
        "override %r is not a node ID such as !9d0f9a75, so the entry is ignored."
        " Quote the ID in the file: YAML reads a bare ! as a tag",
        raw,
    )
    return None


def parse_overrides(text: str) -> Overrides:
    """Return the overrides in a YAML document.

    A document that cannot be read gives no overrides. A single bad
    value is dropped with a warning and the rest of the file is kept.
    One typed mistake must not empty the whole map.
    """
    try:
        document = yaml.safe_load(text)
    # `RecursionError` is not a `YAMLError`. A deeply nested document
    # raises it out of the parser, and the API builds its overrides at
    # start up, so an unguarded one takes the whole service down over a
    # file somebody hand-edits.
    except (yaml.YAMLError, RecursionError, ValueError) as error:
        logger.error("the radio overrides file could not be read, ignored: %s", error)
        return EMPTY

    if document is None:
        return EMPTY
    if not isinstance(document, dict):
        logger.error("the radio overrides file must hold a mapping, ignored")
        return EMPTY

    raw_nodes = document.get("nodes")
    if raw_nodes is None:
        return EMPTY
    if not isinstance(raw_nodes, dict):
        logger.error("the `nodes` key must hold a mapping, ignored")
        return EMPTY

    nodes: dict[str, NodeOverride] = {}
    for raw_id, raw in raw_nodes.items():
        node_id = _node_id(raw_id)
        if node_id is not None:
            nodes[node_id] = _one_node(node_id, raw)
    return Overrides(nodes=nodes)


def load_overrides(path: str | Path) -> Overrides:
    """Return the overrides in a file.

    A file that is not there gives no overrides. That is the normal
    state of a new deployment, so it is logged at debug level and not as
    a fault.
    """
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.debug("no radio overrides file at %s", file)
        return EMPTY
    except OSError as error:
        logger.error("cannot read the radio overrides file at %s: %s", file, error)
        return EMPTY

    overrides = parse_overrides(text)
    logger.info("read radio overrides for %s nodes from %s", len(overrides.nodes), file)
    return overrides
