"""Tests for what counts as mesh infrastructure.

The coverage map draws a permanent footprint around every site it
predicts from. A node that moves cannot earn one, so the role decides.

The trap these tests exist for is that Meshtastic numbers `CLIENT` as
zero, and ingest turns a zero enum into NULL. A plain client and a node
that never introduced itself are the same row. See `sonoran/roles.py`.
"""

import pytest

from sonoran.roles import INFRASTRUCTURE_ROLES, NO_ROLE, is_infrastructure, role_name


@pytest.mark.parametrize("role", sorted(INFRASTRUCTURE_ROLES))
def test_a_sited_asset_may_transmit(role: str) -> None:
    """Somebody chose the place and left the radio there."""
    assert is_infrastructure(role)


def test_a_null_role_is_not_infrastructure() -> None:
    """The one that matters.

    `ingest/handlers/nodeinfo.py` returns None for a zero enum value,
    and `CLIENT` is zero. So NULL means "a client, or a node we know
    nothing about". Reading it as "unknown, so include it" is what put
    639 client nodes on a coverage map.
    """
    assert not is_infrastructure(None)
    assert not is_infrastructure("")


@pytest.mark.parametrize(
    "role",
    ["CLIENT", "CLIENT_MUTE", "CLIENT_BASE", "CLIENT_HIDDEN", "TRACKER", "SENSOR", "TAK"],
)
def test_a_client_never_transmits(role: str) -> None:
    assert not is_infrastructure(role)


def test_a_router_client_is_not_infrastructure() -> None:
    """It reads like infrastructure and is not.

    `ROUTER_CLIENT` repeats traffic, so the name invites including it.
    It is usually a personal node with the setting turned on, and it
    moves like one.
    """
    assert not is_infrastructure("ROUTER_CLIENT")


def test_the_test_does_not_care_about_case() -> None:
    assert is_infrastructure("router")


def test_a_missing_role_is_counted_under_a_name_of_its_own() -> None:
    """A report counts by role, and NULL needs a name to count under."""
    assert role_name(None) == NO_ROLE
    assert role_name("") == NO_ROLE
    assert role_name("router") == "ROUTER"
    assert NO_ROLE not in INFRASTRUCTURE_ROLES


def test_the_public_embed_shares_this_table() -> None:
    """One table, two rules.

    The embed adds MQTT gateways on top, because running one is a
    deliberate act. The coverage job must not: a gateway is often a
    client radio in a house that happens to have wifi.
    """
    from sonoran.embed.sanitise import PUBLIC_ROLES, is_public_node

    assert PUBLIC_ROLES is INFRASTRUCTURE_ROLES
    assert is_public_node("CLIENT", True)
    assert not is_infrastructure("CLIENT")
