"""The `preset=` filter of the list pages (#313).

Ingest tags each packet with the modem preset that carried it, and each
node with the preset of its newest tagged packet. A list page reads that
tag. It does not guess from the topic channel, because a topic channel
such as `azmsh` runs on more than one preset.

A row written before the tag existed holds NULL. Such a row is read by
its topic channel, which is exactly what the page did before:

    modem_preset = :preset
    OR (modem_preset IS NULL AND channel = :preset)

which is `coalesce(modem_preset, channel) = :preset`.

So history does not vanish on the day this ships. The fallback fades as
retention expires the old rows, and it then matches nothing.

`preset` is separate from `channel`. A caller may pass both, and gets
both: `channel=azmsh&preset=LongFast` is the azmsh traffic on LongFast.
A request without `preset` runs the SQL it always ran.
"""

from typing import Any

from fastapi import HTTPException
from sqlalchemy import ColumnElement, func

from sonoran.radio.presets import preset_for_channel


def require_preset(value: str | None) -> str | None:
    """Return the canonical preset name, or None when none was asked for.

    An unknown name is a bad request. Answering it with an empty page
    would read as a quiet mesh.
    """
    if value is None or value == "":
        return None
    preset = preset_for_channel(value)
    if preset is None:
        raise HTTPException(status_code=422, detail=f"unknown modem preset: {value}")
    return preset.name


def preset_filter(tag: Any, channel: Any, preset: str) -> ColumnElement[bool]:
    """Return the rows tagged `preset`, and the untagged rows on its channel.

    Written as `coalesce(tag, channel) = :preset`, which is the same test
    as the two lines in the module docstring. One form, so that `tag` is
    named once: for a chat message it is a correlated read of the
    packet's tag, and the OR form would run that read twice.
    """
    return func.coalesce(tag, channel) == preset
