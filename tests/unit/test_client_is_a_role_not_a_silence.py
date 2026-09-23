"""`CLIENT` is a role, and it was being stored as silence (#197).

Meshtastic numbers device roles from zero and `CLIENT` is zero.
`store_nodeinfo` read every enum with `if not value: return None`, so a
client and a node that had never introduced itself were stored
identically, as NULL.

The live map then drew the commonest kind of node on the mesh in the
grey it keeps for "no role reported": 170 nodes on MediumFast, 167 of
which carried a long name and had therefore plainly introduced
themselves.

This is the same shape as #157 (a sentinel sharing a value with real
data) and #149 (an unmeasured thing labelled as a measured one), which
is why the fix is the same: record what was actually received, and keep
the one inference about old rows in one place with its limits written
down.
"""

from typing import Any

import pytest

from sonoran.ingest.handlers.nodeinfo import _enum_name, _role_name
from sonoran.meshtastic import mesh_pb2
from sonoran.roles import DEFAULT_ROLE, resolve_role


def _user(**fields: Any) -> Any:
    """Build a real User protobuf, not a stand-in.

    The bug lived in how a protobuf's defaults read, so a mock with a
    `role` attribute would reproduce the reasoning and not the bug.
    """
    user: Any = mesh_pb2.User()  # type: ignore[attr-defined]
    for name, value in fields.items():
        setattr(user, name, value)
    return user


def test_a_user_message_that_names_no_role_is_a_client() -> None:
    """The bug, stated as the case that produced it.

    proto3 gives a scalar no presence, so "unset" and "CLIENT" are the
    same bytes. They also mean the same thing: config.proto calls
    CLIENT the Default Role.
    """
    assert _role_name(_user(long_name="Someone")) == "CLIENT"


def test_an_explicit_client_is_a_client() -> None:
    """And setting it explicitly must not read differently."""
    assert _role_name(_user(long_name="Someone", role=0)) == "CLIENT"


def test_a_real_role_is_unchanged() -> None:
    """The non-regression half: named roles keep their names."""
    for number, name in ((1, "CLIENT_MUTE"), (2, "ROUTER"), (4, "REPEATER")):
        assert _role_name(_user(role=number)) == name


def _first_unvendored_role() -> int:
    """The lowest role number this repository's protobuf does not know.

    Computed, not written down. The first draft of the test below used
    12 as "a role we do not know" and 12 is `CLIENT_BASE` -- vendored,
    named, and already deployed on this mesh. Firmware adds roles and
    this repository vendors them, so any literal here is a test that
    will one day fail for the wrong reason.
    """
    field = mesh_pb2.User().DESCRIPTOR.fields_by_name["role"]  # type: ignore[attr-defined]
    return max(field.enum_type.values_by_number) + 1


def test_a_role_this_proto_does_not_know_keeps_its_digits() -> None:
    """A newer firmware role must not become NULL.

    Turning an unknown role into NULL would feed it straight back into
    the bug this fixes: it would land in the same bucket as CLIENT and
    as "never introduced itself". Firmware ships roles faster than this
    repository vendors them, so this is a real case and not a
    hypothetical -- CLIENT_BASE (12) was one until recently.
    """
    number = _first_unvendored_role()
    name = _role_name(_user(role=number))
    assert name == f"ROLE_{number}"


def test_the_unvendored_probe_is_really_unvendored() -> None:
    """Positive control for the helper above.

    If `_first_unvendored_role` ever returned a number the proto DOES
    know, the test above would silently become an assertion about a
    named role and stop protecting anything.
    """
    field = mesh_pb2.User().DESCRIPTOR.fields_by_name["role"]  # type: ignore[attr-defined]
    assert _first_unvendored_role() not in field.enum_type.values_by_number
    assert 12 in field.enum_type.values_by_number, "CLIENT_BASE is vendored; see above"


def test_role_is_never_null_for_a_node_that_introduced_itself() -> None:
    """The invariant, over every value the field can hold.

    This is the claim the map depends on, so it is asserted as a claim
    rather than as three examples.
    """
    for number in [*range(15), 99, 255]:
        assert _role_name(_user(role=number)), f"role {number} came back falsy"


def test_hardware_model_still_treats_zero_as_unreported() -> None:
    """`_enum_name` keeps its old behaviour, and should.

    `UNSET` really is "no hardware reported", so zero is correctly NULL
    there. Fixing role by changing the shared helper would have made
    every unset hardware model read as whatever enum name zero has.
    """
    assert _enum_name(_user(), "hw_model") is None
    assert _enum_name(_user(hw_model=9), "hw_model") is not None


# --- the historical half -------------------------------------------


def test_an_old_null_with_a_name_reads_as_a_client() -> None:
    """A stored name means a User message was processed."""
    assert resolve_role(None, "Some Node", "SN") == DEFAULT_ROLE
    assert resolve_role(None, "Some Node", None) == DEFAULT_ROLE
    assert resolve_role(None, None, "SN") == DEFAULT_ROLE


def test_an_old_null_with_no_name_stays_unknown() -> None:
    """The three genuinely-unknown nodes must not be invented into clients.

    This is the half that keeps the fix honest. Without it, resolve_role
    is just "call everything a client", which would be a different lie
    in place of the old one.
    """
    assert resolve_role(None, None, None) is None


def test_a_real_role_is_never_overridden() -> None:
    """Resolution only ever fills a blank."""
    assert resolve_role("ROUTER", "Some Node", "SN") == "ROUTER"
    assert resolve_role("ROLE_12", None, None) == "ROLE_12"


@pytest.mark.parametrize("blank", ["", None])
def test_an_empty_string_is_not_a_role(blank: str | None) -> None:
    """`""` must behave as NULL, not as a role named nothing."""
    assert resolve_role(blank, "Some Node", None) == DEFAULT_ROLE
