"""Turning a node into a prediction, and back into two directions.

A coverage map has to answer two questions, and they are not the same
question:

- Can I hear the mesh from here?  The node transmits, a handheld
  receives.
- Can the mesh hear me from here?  The handheld transmits, the node
  receives.

A node on a 30 m mast talking to a handheld at 1.5 m is not the same
link as the reverse. A carrier map shows the first, because that is
what sells telephones. A mesh needs both, and the honest answer is the
weaker of the two.

Both come from one engine run. The path loss between two points does
not depend on which end transmits, as long as the two antenna heights
stay where they are. That is reciprocity, and ITM obeys it.

Write the engine field at a point as

    F = EIRP_node - L

where L is the loss for the geometry the run was set up with. Then:

    down = F + G_hand - loss_hand
    up   = EIRP_hand - L + G_node - cable_node

and because EIRP_node = P_node + G_node - cable_node, the whole antenna
of the node cancels out of the difference:

    up = F + EIRP_hand - P_node
    up - down = P_hand - P_node

So the uplink is the downlink moved by the difference between the two
transmit powers, and nothing else. A node that shouts at 30 dBm is
heard 8 dB further than it hears a handheld that shouts at 22 dBm.

That is one run for two layers, and it is exact rather than an
approximation.
"""

from dataclasses import dataclass

from sonoran.config import Settings
from sonoran.coverage.clutter import terminal_loss_db
from sonoran.coverage.params import DEFAULT_FREQUENCY_MHZ, EngineParams, erp_watts
from sonoran.landcover.classes import is_diffracting
from sonoran.landcover.store import class_at, clutter_at
from sonoran.radio.presets import ModemPreset
from sonoran.radio.resolve import RadioProfile

# The transmit power of the handheld the map assumes, in dBm.
#
# A stock SX1262 device. It is the common case, and it is the radio
# somebody walking around actually has.
HANDHELD_TX_POWER_DBM = 22.0


@dataclass(frozen=True)
class Site:
    """One node, ready to predict from."""

    node_id: str
    node_num: int
    display_name: str
    latitude: float
    longitude: float
    profile: RadioProfile
    preset: ModemPreset
    # The representative height of what stands around the node, in
    # metres, and whether a signal bends over it.
    clutter_height_m: float
    clutter_diffracting: bool = False
    # What that clutter costs this node's own antenna, in dB. It is a
    # loss at this end of every path, so it is charged once here
    # rather than inside the engine. See `coverage/clutter.py`.
    clutter_loss_db: float = 0.0

    @property
    def sort_key(self) -> float:
        """Return how much of the map this site is likely to set.

        A tall site with a strong signal reaches much further than a
        short one. When a run has to leave nodes out, it must leave out
        the ones that would have changed the least.
        """
        return self.profile.effective_eirp_dbm + 20.0 * (self.profile.antenna_height_m**0.5)


def handheld_eirp_dbm(settings: Settings) -> float:
    """Return the power the assumed handheld radiates, in dBm."""
    return HANDHELD_TX_POWER_DBM + settings.coverage_rx_gain_dbi


def make_site(
    settings: Settings,
    node_id: str,
    node_num: int,
    display_name: str,
    latitude: float,
    longitude: float,
    profile: RadioProfile,
    preset: ModemPreset,
) -> Site:
    """Return a site, with the clutter around it worked out."""
    around = clutter_at(settings, latitude, longitude)
    diffracting = is_diffracting(class_at(settings, latitude, longitude))
    # An operator who says the node is above the roofs is believed.
    height = 1e9 if profile.above_clutter else profile.antenna_height_m
    return Site(
        node_id=node_id,
        node_num=node_num,
        display_name=display_name,
        latitude=latitude,
        longitude=longitude,
        profile=profile,
        preset=preset,
        clutter_height_m=around,
        clutter_diffracting=diffracting,
        clutter_loss_db=terminal_loss_db(around, height, DEFAULT_FREQUENCY_MHZ, diffracting),
    )


def engine_params(settings: Settings, site: Site) -> EngineParams:
    """Return the engine values for one site.

    The transmit power used is the effective one, which holds whatever
    the calibration job measured. The nameplate figure stays readable
    beside it on the node page.
    """
    profile = site.profile
    return EngineParams(
        latitude=site.latitude,
        longitude=site.longitude,
        tx_height_m=profile.antenna_height_m,
        rx_height_m=settings.coverage_rx_height_m,
        # The calibration correction belongs to the transmitter, so it
        # goes in here rather than on the level afterwards.
        erp_watts=erp_watts(
            profile.tx_power_dbm + profile.calibration_offset_db,
            profile.antenna_gain_dbi,
            profile.cable_loss_db,
        ),
        radius_m=settings.coverage_radius_km * 1000.0,
        # The engine is given no clutter on purpose.
        #
        # It uses the value by raising the ground, which costs nothing
        # while the antenna clears the clutter and forty to seventy dB
        # once it does not, and never charges the receiver at all. That
        # is a cliff, not a model. The loss is charged at each terminal
        # instead. See `coverage/clutter.py`.
        clutter_height_m=0.0,
    )


def downlink_offset_db(settings: Settings) -> float:
    """Return what to add to the engine field for the downlink.

    The engine reports the field that arrives. The handheld's antenna
    then adds its gain.

    The clutter at each end is charged separately: the node's own by
    `Site.clutter_loss_db`, and the handheld's by the receiver raster
    the job builds for the whole region.
    """
    return settings.coverage_rx_gain_dbi


def uplink_offset_db(settings: Settings, site: Site) -> float:
    """Return what to add to the engine field for the uplink.

    See the note at the top of this module. The whole antenna of the
    node cancels, and what is left is the handheld's radiated power
    against the node's transmit power.
    """
    return handheld_eirp_dbm(settings) - (
        site.profile.tx_power_dbm + site.profile.calibration_offset_db
    )
