"""_enum_name must survive an enum value the vendored proto never named.

Newer firmware reports newer hardware models and roles than the compiled
descriptors carry. The nodeinfo handler used to look the value up with a
bare subscript, which raised KeyError and failed the whole packet. The
fix drops the single unknown field instead.
"""

import pytest

from sonoran.ingest.handlers.nodeinfo import _enum_name
from sonoran.meshtastic import mesh_pb2


def _first_known_hw_model() -> tuple[int, str]:
    """A defined, nonzero HardwareModel, taken from the descriptors."""
    field = mesh_pb2.User.DESCRIPTOR.fields_by_name["hw_model"]
    return next((n, d.name) for n, d in field.enum_type.values_by_number.items() if n != 0)


def test_unknown_hw_model_is_dropped_not_raised() -> None:
    # 60000 is not a HardwareModel the vendored proto defines. This is
    # the case that used to raise KeyError and lose the packet.
    user = mesh_pb2.User()
    user.hw_model = 60000
    assert _enum_name(user, "hw_model") is None


def test_known_hw_model_returns_its_name() -> None:
    number, name = _first_known_hw_model()
    user = mesh_pb2.User()
    user.hw_model = number
    assert _enum_name(user, "hw_model") == name


def test_zero_stays_none() -> None:
    # Unset is the zero value, and an absent field is not a name.
    assert _enum_name(mesh_pb2.User(), "hw_model") is None


@pytest.mark.parametrize("field_name", ["hw_model", "role"])
def test_unknown_value_never_raises(field_name: str) -> None:
    user = mesh_pb2.User()
    setattr(user, field_name, 60000)
    # The point is that this returns rather than raising.
    assert _enum_name(user, field_name) is None
