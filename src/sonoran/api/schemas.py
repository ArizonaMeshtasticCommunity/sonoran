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
