"""JSON response models for the read-only API."""

from datetime import datetime

from pydantic import BaseModel


class NodeSummary(BaseModel):
    """A node returned by the node list."""

    node_id: str
    node_num: int
    long_name: str | None
    short_name: str | None
    display_name: str
    hw_model: str | None
    role: str | None
    last_heard: datetime | None
    is_mqtt_gateway: bool
    has_position: bool
    # Added for the filter panel, which has to be able to show what it
    # filtered on. `channel` was filterable before it was returned, so
    # the picker that offered it could never list a single option.
    channel: str | None = None
    is_licensed: bool = False
    position_confidence: str = "none"
