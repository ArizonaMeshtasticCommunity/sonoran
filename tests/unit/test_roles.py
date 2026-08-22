"""Tests for what counts as mesh infrastructure.

The coverage map draws a permanent footprint around every site it
predicts from. A node that moves cannot earn one, so the role decides.

The trap these tests exist for is that Meshtastic numbers `CLIENT` as
zero, and ingest turns a zero enum into NULL. A plain client and a node
that never introduced itself are the same row. See `sonoran/roles.py`.
"""

import pytest

from sonoran.roles import (
    EVERY_ROLE,
    INFRASTRUCTURE_ROLES,
    NO_ROLE,
    is_diagnostic_role_set,
    is_infrastructure,
    is_site_role,
    parse_site_roles,
    role_name,
)


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
    """One table, and now one rule.

    The embed used to add MQTT gateways on top, on the reasoning that
    running one is a deliberate act. It is not: the flag is set for any
    node that publishes and never cleared, so a client with the uplink
    switched on carried its home onto a public map. Both rules now ask
    the same question.
    """
    from sonoran.embed.sanitise import PUBLIC_ROLES, is_public_node

    assert PUBLIC_ROLES is INFRASTRUCTURE_ROLES
    for role in ("CLIENT", "CLIENT_MUTE", None):
        assert not is_public_node(role, True), role
        assert not is_infrastructure(role), role
    assert is_public_node("ROUTER", False)


# --- the diagnostic set ------------------------------------------------
#
# Logan asked on the pull request that an explicit "all nodes" run stay
# available beside the filter. It is genuinely useful for answering
# "why is this ridge empty?". It is also the one setting in this
# service that can make an honest-looking map dishonest, so the tests
# below are about what it must never reach.


def test_the_default_setting_is_the_infrastructure_set() -> None:
    assert parse_site_roles("ROUTER,ROUTER_LATE,REPEATER") == INFRASTRUCTURE_ROLES


def test_a_typo_falls_back_to_the_safe_answer() -> None:
    """A deployment must not lose its filter to an empty string.

    The failure has to be to the narrow set. Falling open would turn a
    published map into a diagnostic one without anybody asking.
    """
    assert parse_site_roles("") == INFRASTRUCTURE_ROLES
    assert parse_site_roles("   ,  ,") == INFRASTRUCTURE_ROLES


def test_all_means_every_role_including_the_missing_one() -> None:
    allowed = parse_site_roles(EVERY_ROLE)
    assert allowed is None
    for role in ("CLIENT", "CLIENT_MUTE", "TRACKER", None, ""):
        assert is_site_role(role, allowed), role


def test_a_named_set_is_taken_as_written() -> None:
    """An operator may widen it a little without going all the way."""
    allowed = parse_site_roles("router, client_base")
    assert allowed == frozenset({"ROUTER", "CLIENT_BASE"})
    assert is_site_role("CLIENT_BASE", allowed)
    assert not is_site_role("CLIENT", allowed)
    assert not is_site_role(None, allowed)


def test_an_infrastructure_subset_is_safe_to_publish() -> None:
    """A router-only map cannot expose a personal node."""
    assert not is_diagnostic_role_set(frozenset({"ROUTER"}))
    assert not is_diagnostic_role_set(INFRASTRUCTURE_ROLES)


def test_a_wider_role_set_is_diagnostic() -> None:
    """Every role and a named client role can expose a personal node."""
    assert is_diagnostic_role_set(None)
    assert is_diagnostic_role_set(frozenset({"ROUTER", "CLIENT_BASE"}))


def test_a_diagnostic_run_can_never_widen_the_public_map() -> None:
    """The landmine this setting would otherwise be.

    `COVERAGE_SITE_ROLES=ALL` predicts from handhelds, which is what it
    is for. If the public embed read the same setting, one environment
    variable would put every client node in the mesh — homes, mostly —
    onto a public page at a kilometre. The embed asks its own question
    and takes no setting at all.
    """
    import inspect

    from sonoran.embed import sanitise

    assert sanitise.PUBLIC_ROLES is INFRASTRUCTURE_ROLES
    source = inspect.getsource(sanitise)
    assert "parse_site_roles" not in source
    assert "coverage_site_roles" not in source
    # And the function takes no settings argument to read one from.
    assert list(inspect.signature(sanitise.is_public_node).parameters) == [
        "role",
        "is_mqtt_gateway",
    ]


def test_a_role_that_does_not_exist_is_said_out_loud(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A typo matches nothing, and nothing is a silent answer.

    `COVERAGE_SITE_ROLES=ROUTR,REPEATER` parses to a set that no node
    can be in. The run then finds no site and reports that the mesh has
    no routers on it, which sends the reader out to look at the radios.
    """
    with caplog.at_level("WARNING"):
        allowed = parse_site_roles("ROUTR,REPEATER")
    assert allowed == frozenset({"ROUTR", "REPEATER"})
    assert "ROUTR" in caplog.text
    # And it names the real ones, so the reader does not have to search.
    assert "ROUTER_LATE" in caplog.text


def test_a_role_the_firmware_adds_later_still_works(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warned about, never refused.

    This list will fall a release behind the firmware. A deployment
    must not stop because of that.
    """
    with caplog.at_level("WARNING"):
        allowed = parse_site_roles("ROUTER,SOME_NEW_ROLE")
    assert allowed is not None
    assert is_site_role("SOME_NEW_ROLE", allowed)
    assert "SOME_NEW_ROLE" in caplog.text


def test_the_default_setting_names_only_real_roles() -> None:
    """The shipped default must not trip its own warning."""
    from sonoran.config import Settings
    from sonoran.roles import KNOWN_ROLES

    shipped = Settings(_env_file=None).coverage_site_roles
    assert {part.strip().upper() for part in shipped.split(",")} <= KNOWN_ROLES
    assert parse_site_roles(shipped) == INFRASTRUCTURE_ROLES
