"""Hypertable definitions.

This list is the single source of truth for hypertables and their
retention periods. The initial migration and the tests import it.

Each entry is: (table name, partition column, retention in days).
"""

HYPERTABLES: list[tuple[str, str, int]] = [
    ("packet", "first_seen_at", 30),
    ("packet_seen", "seen_at", 30),
    ("traceroute", "seen_at", 90),
    ("text_message", "seen_at", 30),
    ("position_metrics", "time", 30),
    ("device_metrics", "time", 90),
    ("environment_metrics", "time", 90),
    ("air_quality_metrics", "time", 90),
    ("power_metrics", "time", 90),
    ("pax_metrics", "time", 90),
    ("mesh_packet_metrics", "time", 90),
    ("neighbor_metrics", "time", 90),
    ("local_stats", "time", 90),
]
