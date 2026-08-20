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
"""

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

from sonoran.logging import get_logger

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
}


@dataclass(frozen=True)
class NodeOverride:
    """What an operator says about one node.

    Every field is optional. None means "no opinion, use the default".
    """

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
    lock_calibration: bool = False
    note: str = ""


@dataclass(frozen=True)
class Overrides:
    """Every override in the file, by node ID."""

    nodes: dict[str, NodeOverride]

    def for_node(self, node_id: str) -> NodeOverride:
        """Return the override for a node, or an empty one."""
        return self.nodes.get(node_id, NodeOverride())


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

    # `lock_calibration` is not optional on the dataclass, so a bad
    # value must not reach it as None.
    values.setdefault("lock_calibration", False)
    return NodeOverride(**values)


def parse_overrides(text: str) -> Overrides:
    """Return the overrides in a YAML document.

    A document that cannot be read gives no overrides. A single bad
    value is dropped with a warning and the rest of the file is kept.
    One typed mistake must not empty the whole map.
    """
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        logger.error("the radio overrides file is not valid YAML, ignored: %s", error)
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

    nodes = {str(node_id): _one_node(str(node_id), raw) for node_id, raw in raw_nodes.items()}
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
