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

Several presets at once (#383): `preset=MediumFast,LongFast` keeps the
rows carried on any of them. One name runs the same equality as before;
two or more run

    coalesce(modem_preset, channel) IN (:presets)

Every name is checked, and one name that is not a preset refuses the
whole request.
"""

from collections.abc import Sequence
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


# The separator of several presets in one `preset=`. No preset name holds it.
SEPARATOR = ","

Presets = tuple[str, ...]


def require_presets(value: str | None) -> Presets | None:
    """Return the canonical names of one or more presets, or None for none.

    `value` is one name, or several with commas between them. Each is
    matched like `require_preset`, a repeat is kept once, and the order
    given is kept. An empty part or a name that is not a preset is a bad
    request, for the same reason as there.
    """
    if value is None or value == "":
        return None
    names: list[str] = []
    for part in value.split(SEPARATOR):
        name = require_preset(part.strip())
        if name is None:
            raise HTTPException(status_code=422, detail=f"empty modem preset in: {value}")
        if name not in names:
            names.append(name)
    return tuple(names)


def preset_filter(tag: Any, channel: Any, preset: str | Sequence[str]) -> ColumnElement[bool]:
    """Return the rows tagged `preset`, and the untagged rows on its channel.

    Written as `coalesce(tag, channel) = :preset`, which is the same test
    as the two lines in the module docstring. One form, so that `tag` is
    named once: for a chat message it is a correlated read of the
    packet's tag, and the OR form would run that read twice.

    `preset` may be several names (#383). One name keeps the equality, so
    a request for one preset runs the SQL it ran before; two or more use
    `IN`.
    """
    names = (preset,) if isinstance(preset, str) else tuple(preset)
    value = func.coalesce(tag, channel)
    if len(names) == 1:
        return value == names[0]
    return value.in_(names)
