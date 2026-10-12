"""Put a made-up mesh into a local development database.

The dashboard shows nothing when the database is empty. This script
fills it, so you can see a new feature while you build it.

The data is not real. The node numbers, the names, the positions, and
the packets are all invented. The script writes only the columns that
ingest writes. It does not write `packet.payload_json`. See AGENTS.md
9.11.

Do not run this against a production database.

Run it against a migrated development database:

    uv run python tools/dev/seed.py

Add `--live` to keep adding packets at the present moment instead, so
the live map animation has something to draw. See `live` below.

The script empties the tables before it fills them. You can run it
again as many times as you want.
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# The random seed is constant. Two runs give the same data. A
# screenshot after a change is thus different only because of the
# change.
RNG = random.Random(1337)

NOW = datetime.now(UTC)

# Port numbers, from the Meshtastic protobufs.
PORT_TEXT = 1
PORT_POSITION = 3
PORT_NODEINFO = 4
PORT_TELEMETRY = 67
PORT_TRACEROUTE = 70
PORT_NEIGHBORINFO = 71

BROADCAST = 0xFFFFFFFF

# What the firmware writes for a hop it could not measure. It is
# INT8_MIN, and it means "not measured", never -32 dB. See AGENTS.md 9.6.
UNMEASURED_SNR = -128

# Nodes in Arizona. There are clients in Phoenix, Tucson, Flagstaff,
# and Prescott. There are routers on the high ground between them.
NODES = [
    (
        0x0A51A001,
        "SBPK",
        "South Mountain Router",
        "STATION_G2",
        "ROUTER",
        33.339,
        -112.0999,
        802,
        True,
    ),
    (
        0x0A51A002,
        "USRY",
        "Usery Pass Relay",
        "HELTEC_V3",
        "ROUTER",
        33.472,
        -111.606,
        640,
        True,
    ),
    (
        0x0A51A003,
        "MTLM",
        "Mount Lemmon",
        "RAK4631",
        "ROUTER",
        32.443,
        -110.788,
        2791,
        True,
    ),
    (
        0x0A51A004,
        "MNGS",
        "Mingus Mountain",
        "STATION_G2",
        "ROUTER",
        34.706,
        -112.123,
        2287,
        True,
    ),
    (
        0x0A51A005,
        "HMBL",
        "Humphreys Base",
        "HELTEC_V3",
        "ROUTER_CLIENT",
        35.346,
        -111.678,
        2804,
        False,
    ),
    (
        0x0A51B001,
        "TEMP",
        "Tempe Rooftop",
        "TBEAM",
        "CLIENT",
        33.4255,
        -111.94,
        356,
        True,
    ),
    (
        0x0A51B002,
        "MESA",
        "Mesa Backyard",
        "HELTEC_V3",
        "CLIENT",
        33.4152,
        -111.8315,
        388,
        True,
    ),
    (
        0x0A51B003,
        "GLND",
        "Glendale Garage",
        "TBEAM",
        "CLIENT",
        33.5387,
        -112.186,
        340,
        True,
    ),
    (
        0x0A51B004,
        "CHAN",
        "Chandler Shed",
        "RAK4631",
        "CLIENT",
        33.3062,
        -111.8413,
        370,
        True,
    ),
    (
        0x0A51B005,
        "TUCS",
        "Tucson Foothills",
        "HELTEC_V3",
        "CLIENT",
        32.32,
        -110.9,
        800,
        True,
    ),
    (
        0x0A51B006,
        "ORVL",
        "Oro Valley Porch",
        "TBEAM",
        "CLIENT",
        32.391,
        -110.966,
        780,
        False,
    ),
    (
        0x0A51B007,
        "FLAG",
        "Flagstaff Downtown",
        "RAK4631",
        "CLIENT",
        35.198,
        -111.651,
        2106,
        False,
    ),
    (
        0x0A51B008,
        "PRES",
        "Prescott Hillside",
        "HELTEC_V3",
        "CLIENT",
        34.54,
        -112.4685,
        1636,
        False,
    ),
    (
        0x0A51B009,
        "PAYS",
        "Payson Cabin",
        "TBEAM",
        "CLIENT_MUTE",
        34.2309,
        -111.3251,
        1493,
        False,
    ),
    (
        0x0A51B00A,
        "YUMA",
        "Yuma Flats",
        "HELTEC_V3",
        "CLIENT",
        32.6927,
        -114.6277,
        43,
        False,
    ),
    (
        0x0A51C001,
        "TRKR",
        "Trail Tracker",
        "TBEAM",
        "TRACKER",
        33.6,
        -111.92,
        500,
        False,
    ),
    (
        0x0A51C002,
        "WXST",
        "Sensor Weather Station",
        "RAK4631",
        "SENSOR",
        33.5,
        -111.7,
        450,
        False,
    ),
    # The two nodes below exist so that the coverage gaps page has
    # something true to show in a preview. A feature nobody can see in a
    # preview is a feature nobody can check.
    #
    # Both are MQTT gateways, because only a gateway can ever be found
    # "present through MQTT and not heard on the air": a node that is
    # not a gateway could not have reached the database at all unless a
    # radio heard it. See `sonoran/gaps/signals.py`.
    (
        0x0A51D001,
        "ORPH",
        "Orphan Hill Gateway",
        "STATION_G2",
        "CLIENT_BASE",
        33.6019,
        -112.3512,
        520,
        True,
    ),
    (
        0x0A51D002,
        "FLKY",
        "Flaky Ridge Gateway",
        "HELTEC_V3",
        "CLIENT_BASE",
        33.2044,
        -111.6031,
        700,
        True,
    ),
    # A neighbourhood of struggling nodes, so that the siting half of
    # the coverage gaps page has something true to show in a preview.
    #
    # Two struggling nodes fifty kilometres apart are two nodes. The
    # siting half only speaks about an **area**, which is at least
    # `GAPS_MIN_CLUSTER` places wanting help within
    # `GAPS_CLUSTER_LINK_KM` of each other, so a preview with only ORPH
    # and FLKY in it showed the page working and answering "no area".
    # That is a true answer and it is not the answer worth looking at.
    #
    # They stand in the valley east of the White Tank Mountains, which
    # is real ground with a real ridge six to eight kilometres west of
    # it rising about 780 m above the valley floor. The positions are
    # made up, as every position in this file is. The terrain is not:
    # the candidate the screen and the engine pick out is a hill that
    # exists, and that is the point of putting them here rather than in
    # the middle of a flat basin.
    #
    # Each of them is an MQTT gateway whose traffic reaches us only
    # through its own internet link, which is `radio_isolated`. That is
    # the honest reason to want a node nearby: nothing on the air can
    # hear any of them.
    (
        0x0A51E001,
        "WTV1",
        "White Tank Valley North",
        "STATION_G2",
        "CLIENT_BASE",
        33.6300,
        -112.5100,
        470,
        True,
    ),
    (
        0x0A51E002,
        "WTV2",
        "White Tank Valley Mid",
        "RAK4631",
        "CLIENT_BASE",
        33.6100,
        -112.4900,
        462,
        True,
    ),
    (
        0x0A51E003,
        "WTV3",
        "Citrus Road Gateway",
        "HELTEC_V3",
        "CLIENT_BASE",
        33.5900,
        -112.4700,
        455,
        True,
    ),
    (
        0x0A51E004,
        "WTV4",
        "Deer Valley West Gateway",
        "TBEAM",
        "CLIENT_BASE",
        33.5650,
        -112.4450,
        448,
        True,
    ),
    (
        0x0A51E005,
        "WTV5",
        "Perryville Gateway",
        "RAK4631",
        "CLIENT_BASE",
        33.5750,
        -112.5000,
        460,
        True,
    ),
]

# The two nodes the gap signals are seeded to demonstrate.
#
# They are kept out of the random traffic loop on purpose. That loop
# gives every sender one to three random gateways, which would make
# every packet radio-evidenced and leave these two looking healthy. Their
# traffic is written by hand below instead, so that what the page shows
# is a consequence of the rows and not of a label.
GAP_ISOLATED = 0x0A51D001
GAP_INTERMITTENT = 0x0A51D002

# The neighbourhood the siting half is seeded to find. Every one of them
# is an MQTT gateway nothing on the air has heard, which is the demand
# an area is made of.
GAP_CLUSTER = (0x0A51E001, 0x0A51E002, 0x0A51E003, 0x0A51E004, 0x0A51E005)

GAP_DEMO = (GAP_ISOLATED, GAP_INTERMITTENT, *GAP_CLUSTER)

# The positions in a NODES row.
NUM, SHORT, LONG, HW, ROLE, LAT, LON, ALT, GATEWAY = range(9)

# The gateways the random traffic loop uploads through. Nine of them.
#
# There used to be four, all of them ridge-top routers, and a packet then
# arrived from one to three gateways. The live map draws at most three
# arcs per packet and puts the rest behind a "+N" numeral beside the
# sender, so a preview with four gateways never draws that numeral and
# never exercises the cap. AGENTS.md 9.5.1 measured a live packet with 22
# uploads from 15 gateways, so the real shape of this data is a wide fan
# and a preview that hides it hides the thing the renderer exists for.
#
# A rooftop or backyard client running MQTT is the commonest gateway
# there is, so promoting five of them is the realistic way to widen it.
#
# The two gap-demo gateways stay out of this list. Their traffic is
# written by hand, so what the gaps page shows is a consequence of the
# rows rather than of a label.
GATEWAYS = [n for n in NODES if n[GATEWAY] and n[NUM] not in GAP_DEMO]

# The neighbour links, as (node, neighbour, snr).
LINKS = [
    (0x0A51A001, 0x0A51A002, 4.5),
    (0x0A51A001, 0x0A51B001, 8.25),
    (0x0A51A001, 0x0A51B003, 6.0),
    (0x0A51A001, 0x0A51B004, 7.75),
    # A001 is the busy one on purpose. The node page caps its long
    # tables at five rows and offers the rest behind a button, and a
    # preview where no node has more than five neighbours never draws
    # that button, so the behaviour goes unchecked.
    (0x0A51A001, 0x0A51B002, 2.75),
    (0x0A51A001, 0x0A51B005, -1.5),
    (0x0A51A001, 0x0A51B006, 5.25),
    (0x0A51A002, 0x0A51B002, 9.5),
    (0x0A51A002, 0x0A51C001, 3.25),
    (0x0A51A002, 0x0A51A004, -2.5),
    (0x0A51A002, 0x0A51C002, 5.5),
    (0x0A51A003, 0x0A51B005, 10.75),
    (0x0A51A003, 0x0A51B006, 9.0),
    (0x0A51A003, 0x0A51A001, -6.25),
    (0x0A51A004, 0x0A51B008, 7.0),
    (0x0A51A004, 0x0A51A005, -4.75),
    (0x0A51A005, 0x0A51B007, 11.5),
    (0x0A51A005, 0x0A51B009, 1.25),
]

# The Arizona mesh runs MediumFast, not the Meshtastic default.
#
# Measured: the WisMesh Station gateway has MediumFast as its primary
# channel, and Arizona-region nodes on the public broker run 174
# MediumFast against 41 LongFast. A seed that claims to be an Arizona
# mesh and shows LongFast sends a reader to the wrong preset picker
# before they have looked at anything.
#
# Some LongFast is kept on purpose. A mesh really does carry both, the
# preset picker only means something with more than one, and AGENTS.md
# 9.7 is the rule the picker exists to keep: a node on one preset
# cannot hear a node on another, so the two must never be drawn
# together.
PRIMARY_PRESET = "MediumFast"
SECONDARY_PRESET = "LongFast"
# `Trivia` and `trivia` are both here on purpose. They are two channels
# to the database and one subject to a human, and the chat page files the
# lowercase one under Custom so a name typed wrong stays visible. Seeding
# both is what makes that behaviour checkable in a preview.
CHANNELS = [
    PRIMARY_PRESET,
    PRIMARY_PRESET,
    PRIMARY_PRESET,
    "azmsh",
    "MediumSlow",
    "AZ-Weather",
    "Traffic",
    "Trivia",
    "trivia",
]

MESSAGES = [
    "Morning net check-in from the south valley.",
    "Anyone else seeing the Mingus router drop out around noon?",
    "New solar node up on the ridge, running about 4.1V after dark.",
    "Testing hop count from Tucson, please ack if heard.",
    "Weather station reporting 41C on the flats today.",
    "Rebooted the Usery relay, firmware 2.5.4 now.",
    "Heard you 5 by 5, SNR was 8.25.",
    "Weekly check-in thread is open.",
    "Lost GPS lock on the tracker, still routing fine.",
    "Antenna swap done, gained about 3 dB.",
]


def node_id(num: int) -> str:
    return f"!{num:08x}"


# --- Modem presets (#313) -------------------------------------------
#
# Ingest tags each upload with a modem preset, and each packet with the
# majority of its uploads. The seed writes its rows directly, so it tags
# them the same way afterwards, in SQL, with no draw from `RNG`: every
# random value the seed wrote before stays the same.
#
# - A gateway is on the preset of its node row (GLND is on LongFast).
# - An upload on a preset-named topic is on that preset. Any other upload
#   is on its gateway's preset. So azmsh is on both presets.
# - A packet takes the majority of its uploads. A tie keeps the first.
#
# A node's `last_preset` is written with the node row, as the preset the
# node is on, rather than worked out from its packets. The random traffic
# goes through any gateway, so working it out would move routers between
# the node lists at random, and every journey that looks for one there.

# The default channel names of the presets, by their normalised key.
PRESET_NAMES = {
    "shortturbo": "ShortTurbo",
    "shortfast": "ShortFast",
    "shortslow": "ShortSlow",
    "mediumfast": "MediumFast",
    "mediumslow": "MediumSlow",
    "longfast": "LongFast",
    "longmoderate": "LongModerate",
    "longslow": "LongSlow",
    "verylongslow": "VeryLongSlow",
}
_PRESET_VALUES = ", ".join(f"('{key}', '{name}')" for key, name in PRESET_NAMES.items())

TAG_UPLOADS = f"""
    UPDATE packet_seen AS s SET modem_preset = coalesce(
        (SELECT p.name FROM (VALUES {_PRESET_VALUES}) AS p(key, name)
         WHERE p.key = lower(regexp_replace(s.channel, '[^A-Za-z0-9]+', '', 'g'))),
        (SELECT g.uplink_preset FROM node AS g WHERE g.node_num = s.gateway_node_num))
    WHERE s.modem_preset IS NULL AND s.seen_at >= :since
"""

TAG_PACKETS = """
    UPDATE packet AS p SET modem_preset = v.preset
    FROM (
        SELECT DISTINCT ON (from_node_num, packet_id)
            from_node_num, packet_id, modem_preset AS preset
        FROM (
            SELECT from_node_num, packet_id, modem_preset,
                count(*) OVER w AS votes, min(id) OVER w AS first_id
            FROM packet_seen
            WHERE modem_preset IS NOT NULL AND seen_at >= :since
            WINDOW w AS (PARTITION BY from_node_num, packet_id, modem_preset)
        ) AS t
        ORDER BY from_node_num, packet_id, votes DESC, first_id
    ) AS v
    WHERE p.from_node_num = v.from_node_num AND p.packet_id = v.packet_id
        AND p.modem_preset IS NULL
"""


async def tag_presets(conn, since: datetime) -> None:
    """Tag the uploads and packets written since a moment, as ingest would."""
    await conn.execute(text(TAG_UPLOADS), {"since": since})
    await conn.execute(text(TAG_PACKETS), {"since": since})


# Two azmsh messages the preset journeys look for (#313). Written by
# hand, after every random row, so they draw nothing from `RNG` and do
# not become the message the seeded reactions answer.
#
# PRES is a LongFast node and GLND a LongFast gateway, so its message is
# on LongFast. TEMP and SBPK are on MediumFast. The old `channel=` filter
# showed neither on either preset, because neither topic names a preset.
PRESET_MESSAGES = [
    # (sender, gateway, packet id, preset, body)
    (0x0A51B008, 0x0A51B003, 950_001, SECONDARY_PRESET, "Long Fast check-in on azmsh."),
    (0x0A51B001, 0x0A51A001, 950_002, PRIMARY_PRESET, "Medium Fast check-in on azmsh."),
]


async def write_preset_messages(conn) -> None:
    """Write the two azmsh messages, tagged as ingest would tag them."""
    for minutes, (sender, gateway, packet_id, preset, body) in enumerate(PRESET_MESSAGES):
        at = NOW - timedelta(minutes=2 + minutes)
        values = {"f": sender, "g": gateway, "p": packet_id, "mp": preset, "body": body, "t": at}
        await conn.execute(
            text(
                "INSERT INTO packet_key (from_node_num, packet_id, first_seen_at) "
                "VALUES (:f, :p, :t) ON CONFLICT DO NOTHING"
            ),
            values,
        )
        await conn.execute(
            text(
                """
                INSERT INTO packet (from_node_num, packet_id, to_node_num, portnum,
                    channel, hop_start, hop_limit, want_ack, first_seen_at, modem_preset)
                VALUES (:f, :p, 4294967295, 1, 'azmsh', 3, 2, false, :t, :mp)
                """
            ),
            values,
        )
        await conn.execute(
            text(
                """
                INSERT INTO packet_seen (from_node_num, packet_id, gateway_node_num,
                    mqtt_topic, channel, rx_rssi, rx_snr, hop_limit, hop_start,
                    seen_at, modem_preset)
                VALUES (:f, :p, :g, 'msh/US/AZ/2/e/azmsh/' || :gid, 'azmsh', -97, 4.5,
                    2, 3, :t, :mp)
                """
            ),
            values | {"gid": node_id(gateway)},
        )
        await conn.execute(
            text(
                """
                INSERT INTO text_message (packet_id, from_node_num, to_node_num,
                    channel, body, emoji, seen_at)
                VALUES (:p, :f, 4294967295, 'azmsh', :body, false, :t)
                """
            ),
            values,
        )


def drift(node: tuple) -> float:
    """Return the offset to add to a position.

    A tracker moves. All other nodes stay in one place.
    """
    if node[ROLE] != "TRACKER":
        return 0.0
    return RNG.uniform(-0.05, 0.05)


async def main() -> None:
    url = os.environ.get(
        "SEED_DATABASE_URL",
        "postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/azmsh",
    )
    engine = create_async_engine(url)

    async with engine.begin() as conn:
        # Empty the tables first. A second run must not add duplicates.
        #
        # One statement, because the job output tables (#351) reference
        # `node`, and PostgreSQL truncates a referenced table only
        # together with the tables that reference it.
        tables = (
            "neighbor_metrics",
            "position_metrics",
            "device_metrics",
            "environment_metrics",
            "text_message",
            "traceroute",
            "packet_seen",
            "packet",
            "packet_key",
            "gaps_index",
            "gaps_run",
            "gaps_node",
            "gaps_signal",
            "gaps_trace_answer",
            "gaps_siting",
            "gaps_siting_area",
            "gaps_siting_point",
            "gaps_siting_candidate",
            "node",
        )
        await conn.execute(text(f"TRUNCATE {', '.join(tables)}"))

        # Nodes.
        for num, short, long_name, hw, role, lat, lon, alt, gw in NODES:
            heard = NOW - timedelta(minutes=RNG.randint(1, 240))
            # The backbone is all on the primary preset, and a minority
            # of ordinary nodes sit on the other one.
            #
            # That is the shape a real mesh has. A community agrees one
            # preset and puts its routers on it; the nodes that turn up
            # on another are usually somebody running the factory
            # default. Splitting the routers between presets instead
            # would leave each map missing most of its backbone, which
            # is a worse preview and a less honest one.
            is_infrastructure = role in ("ROUTER", "ROUTER_LATE", "REPEATER")
            node_channel = PRIMARY_PRESET if is_infrastructure or num % 5 != 0 else SECONDARY_PRESET
            # Not every node knows where it is, and not every node that
            # does says so exactly. The nodes list filters on that, and
            # the siting half of the gaps feature is blind to a coarse
            # position, so a preview needs all three kinds or neither
            # behaviour can be seen.
            #
            # One node in seven reports nothing, and one in five reduces
            # its own precision before publishing — which is the node
            # doing it, not the broker.
            coarse = num % 5 == 0
            no_position = num % 7 == 0
            await conn.execute(
                text(
                    """
                    INSERT INTO node (node_num, node_id, long_name, short_name,
                        hw_model, role, is_licensed, last_lat, last_lon,
                        last_altitude, last_position_precision_bits,
                        position_time, last_heard,
                        is_mqtt_gateway, last_mqtt_topic, last_channel,
                        first_seen, updated_at, last_preset, last_preset_at,
                        uplink_preset, uplink_preset_at)
                    VALUES (:num, :nid, :long, :short, :hw, :role, false,
                        :lat, :lon, :alt, :bits, :ptime, :heard, :gw, :topic,
                        :node_channel, :first, :heard, :node_channel, :heard,
                        CASE WHEN :gw THEN :node_channel END,
                        CASE WHEN :gw THEN CAST(:heard AS timestamptz) END)
                    """
                ),
                {
                    "num": num,
                    "nid": node_id(num),
                    "long": long_name,
                    "short": short,
                    "hw": hw,
                    "role": role,
                    "lat": None if no_position else lat,
                    "lon": None if no_position else lon,
                    "alt": None if no_position else alt,
                    "bits": 13 if coarse and not no_position else None,
                    "ptime": heard,
                    "heard": heard,
                    "gw": gw,
                    "node_channel": node_channel,
                    "topic": f"msh/US/AZ/2/e/{node_channel}/" + node_id(num),
                    "first": NOW - timedelta(days=RNG.randint(30, 400)),
                },
            )

        # Packets. Each packet gets one observation for each gateway
        # that heard it. See AGENTS.md 9.5.
        packet_id = 100_000
        senders = [n[NUM] for n in NODES if n[NUM] not in GAP_DEMO]
        for minutes_ago in range(0, 24 * 60, 3):
            seen_at = NOW - timedelta(minutes=minutes_ago)
            for _ in range(RNG.randint(1, 3)):
                packet_id += 1
                sender = RNG.choice(senders)
                portnum = RNG.choices(
                    [
                        PORT_TEXT,
                        PORT_POSITION,
                        PORT_NODEINFO,
                        PORT_TELEMETRY,
                        PORT_TRACEROUTE,
                        PORT_NEIGHBORINFO,
                    ],
                    weights=[8, 30, 12, 30, 8, 12],
                )[0]
                channel = RNG.choice(CHANNELS)
                hop_start = RNG.choice([3, 3, 5, 7])

                await conn.execute(
                    text(
                        """
                        INSERT INTO packet_key (from_node_num, packet_id, first_seen_at)
                        VALUES (:f, :p, :t) ON CONFLICT DO NOTHING
                        """
                    ),
                    {"f": sender, "p": packet_id, "t": seen_at},
                )
                row = await conn.execute(
                    text(
                        """
                        INSERT INTO packet (from_node_num, packet_id, to_node_num,
                            portnum, channel, hop_start, hop_limit, want_ack,
                            rx_time, first_seen_at)
                        VALUES (:f, :p, :to, :port, :ch, :hs, :hl, false,
                            :rx, :t)
                        RETURNING id
                        """
                    ),
                    {
                        "f": sender,
                        "p": packet_id,
                        "to": BROADCAST,
                        "port": portnum,
                        "ch": channel,
                        "hs": hop_start,
                        "hl": hop_start - RNG.randint(0, 2),
                        "rx": int(seen_at.timestamp()),
                        "t": seen_at,
                    },
                )
                packet_pk = row.scalar_one()

                # One to three gateways upload the same packet.
                for gw in RNG.sample(GATEWAYS, RNG.randint(1, 3)):
                    await conn.execute(
                        text(
                            """
                            INSERT INTO packet_seen (packet_pk, from_node_num,
                                packet_id, gateway_node_num, mqtt_topic, channel,
                                rx_rssi, rx_snr, hop_limit, seen_at)
                            VALUES (:pk, :f, :p, :g, :topic, :ch, :rssi, :snr,
                                :hl, :t) ON CONFLICT DO NOTHING
                            """
                        ),
                        {
                            "pk": packet_pk,
                            "f": sender,
                            "p": packet_id,
                            "g": gw[0],
                            "topic": f"msh/US/AZ/2/e/{channel}/{node_id(sender)}",
                            "ch": channel,
                            "rssi": RNG.randint(-120, -60),
                            "snr": round(RNG.uniform(-12, 12), 2),
                            "hl": hop_start - RNG.randint(0, 2),
                            "t": seen_at,
                        },
                    )

                if portnum == PORT_TEXT:
                    await conn.execute(
                        text(
                            """
                            INSERT INTO text_message (packet_pk, packet_id,
                                from_node_num, to_node_num, channel, body,
                                emoji, seen_at)
                            VALUES (:pk, :p, :f, :to, :ch, :body, false, :t)
                            """
                        ),
                        {
                            "pk": packet_pk,
                            "p": packet_id,
                            "f": sender,
                            "to": BROADCAST,
                            "ch": channel,
                            "body": RNG.choice(MESSAGES),
                            "t": seen_at,
                        },
                    )
                elif portnum == PORT_TELEMETRY:
                    await conn.execute(
                        text(
                            """
                            INSERT INTO device_metrics (node_num, packet_pk,
                                packet_id, battery_level, voltage,
                                channel_utilization, air_util_tx,
                                uptime_seconds, time)
                            VALUES (:n, :pk, :p, :bat, :v, :cu, :au, :up, :t)
                            """
                        ),
                        {
                            "n": sender,
                            "pk": packet_pk,
                            "p": packet_id,
                            "bat": round(RNG.uniform(35, 100), 1),
                            "v": round(RNG.uniform(3.5, 4.2), 2),
                            "cu": round(RNG.uniform(1, 28), 2),
                            "au": round(RNG.uniform(0.2, 6), 2),
                            "up": RNG.randint(3600, 3600 * 24 * 30),
                            "t": seen_at,
                        },
                    )
                elif portnum == PORT_POSITION:
                    src = next(n for n in NODES if n[NUM] == sender)
                    # The same rule as the node row above, as ingest
                    # writes one value to both. The history said full
                    # precision for every node, and a node that shares no
                    # position had one in its history, so once the node
                    # page read positions from the history (#310) the
                    # rounded nodes read as exact and the e2e found no
                    # estimate to check.
                    coarse = sender % 5 == 0
                    no_position = sender % 7 == 0
                    await conn.execute(
                        text(
                            """
                            INSERT INTO position_metrics (node_num, packet_pk,
                                packet_id, latitude, longitude, altitude,
                                sats_in_view, precision_bits, time)
                            VALUES (:n, :pk, :p, :lat, :lon, :alt, :sats, :bits, :t)
                            """
                        ),
                        {
                            "n": sender,
                            "pk": packet_pk,
                            "p": packet_id,
                            "lat": None if no_position else src[LAT] + drift(src),
                            "lon": None if no_position else src[LON] + drift(src),
                            "alt": None if no_position else src[ALT],
                            "sats": RNG.randint(4, 12),
                            "bits": 13 if coarse and not no_position else 32,
                            "t": seen_at,
                        },
                    )

        # Environment telemetry. Only the sensor node sends it.
        for hours_ago in range(0, 48):
            t = NOW - timedelta(hours=hours_ago)
            await conn.execute(
                text(
                    """
                    INSERT INTO environment_metrics (node_num, temperature,
                        relative_humidity, barometric_pressure, time)
                    VALUES (:n, :temp, :rh, :bp, :t)
                    """
                ),
                {
                    "n": 0x0A51C002,
                    "temp": round(24 + 14 * RNG.random(), 1),
                    "rh": round(RNG.uniform(8, 35), 1),
                    "bp": round(RNG.uniform(995, 1015), 1),
                    "t": t,
                },
            )

        # The coverage gaps demonstration traffic.
        #
        # Two nodes, two findings, both built out of the one fact that
        # decides everything on that page: a packet is in this database
        # either because the node uploaded it itself, or because some
        # other radio heard it. The first proves nothing about radio.
        #
        # ORPH uploads its own traffic and nothing else ever carries it,
        # so no gateway has heard it over the air. It also publishes
        # neighbour reports, which proves its own receiver works. That
        # pair is the strongest finding the feature can make: a node that
        # hears the mesh and is not heard back.
        #
        # FLKY gets out over the air in some hours and not in others,
        # which is what `rf_intermittent` measures. The ratio is over
        # hours and not over packets, so the pattern here is what the
        # page reads.
        gap_packet_id = 900_000
        for hours_ago in range(0, 24):
            seen_at = NOW - timedelta(hours=hours_ago, minutes=7)
            hop_start = 3

            for _ in range(3):
                gap_packet_id += 1
                await conn.execute(
                    text(
                        """
                        INSERT INTO packet_key (from_node_num, packet_id, first_seen_at)
                        VALUES (:f, :p, :t) ON CONFLICT DO NOTHING
                        """
                    ),
                    {"f": GAP_ISOLATED, "p": gap_packet_id, "t": seen_at},
                )
                await conn.execute(
                    text(
                        """
                        INSERT INTO packet (from_node_num, packet_id, to_node_num,
                            portnum, channel, hop_start, hop_limit, want_ack,
                            rx_time, first_seen_at)
                        VALUES (:f, :p, :to, :port, :ch, :hs, :hs, false, :rx, :t)
                        """
                    ),
                    {
                        "f": GAP_ISOLATED,
                        "p": gap_packet_id,
                        "to": BROADCAST,
                        "port": PORT_TELEMETRY,
                        "ch": PRIMARY_PRESET,
                        "hs": hop_start,
                        "rx": int(seen_at.timestamp()),
                        "t": seen_at,
                    },
                )
                # The only upload is its own. This is the whole point.
                await conn.execute(
                    text(
                        """
                        INSERT INTO packet_seen (from_node_num, packet_id,
                            gateway_node_num, mqtt_topic, channel, rx_rssi, rx_snr,
                            hop_limit, seen_at)
                        VALUES (:f, :p, :f, :topic, :ch, -92, 6.25, :hs, :t)
                        ON CONFLICT DO NOTHING
                        """
                    ),
                    {
                        "f": GAP_ISOLATED,
                        "p": gap_packet_id,
                        "topic": f"msh/US/AZ/2/e/{PRIMARY_PRESET}/" + node_id(GAP_ISOLATED),
                        "ch": PRIMARY_PRESET,
                        "hs": hop_start,
                        "t": seen_at,
                    },
                )

            # FLKY is heard on the air in one hour out of three.
            heard = hours_ago % 3 == 0
            for _ in range(2):
                gap_packet_id += 1
                await conn.execute(
                    text(
                        """
                        INSERT INTO packet_key (from_node_num, packet_id, first_seen_at)
                        VALUES (:f, :p, :t) ON CONFLICT DO NOTHING
                        """
                    ),
                    {"f": GAP_INTERMITTENT, "p": gap_packet_id, "t": seen_at},
                )
                await conn.execute(
                    text(
                        """
                        INSERT INTO packet (from_node_num, packet_id, to_node_num,
                            portnum, channel, hop_start, hop_limit, want_ack,
                            rx_time, first_seen_at)
                        VALUES (:f, :p, :to, :port, :ch, :hs, :hs, false, :rx, :t)
                        """
                    ),
                    {
                        "f": GAP_INTERMITTENT,
                        "p": gap_packet_id,
                        "to": BROADCAST,
                        "port": PORT_POSITION,
                        "ch": PRIMARY_PRESET,
                        "hs": hop_start,
                        "rx": int(seen_at.timestamp()),
                        "t": seen_at,
                    },
                )
                # Its own upload is always there. In a good hour a real
                # gateway carries it as well, one hop out, which is the
                # evidence that something on the air heard it.
                uploads = [(GAP_INTERMITTENT, hop_start, 5.0)]
                if heard:
                    uploads.append((RNG.choice(GATEWAYS)[NUM], hop_start - 1, -14.5))
                for gateway, hop_limit, snr in uploads:
                    await conn.execute(
                        text(
                            """
                            INSERT INTO packet_seen (from_node_num, packet_id,
                                gateway_node_num, mqtt_topic, channel, rx_rssi,
                                rx_snr, hop_limit, seen_at)
                            VALUES (:f, :p, :g, :topic, :ch, -104, :snr, :hl, :t)
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        {
                            "f": GAP_INTERMITTENT,
                            "p": gap_packet_id,
                            "g": gateway,
                            "topic": (
                                f"msh/US/AZ/2/e/{PRIMARY_PRESET}/" + node_id(GAP_INTERMITTENT)
                            ),
                            "ch": PRIMARY_PRESET,
                            "snr": snr,
                            "hl": hop_limit,
                            "t": seen_at,
                        },
                    )

        # The neighbourhood the siting half sites against.
        #
        # Five gateways in the valley east of the White Tank Mountains,
        # each uploading its own traffic and nothing else. Every one of
        # them is therefore `radio_isolated`, which makes each of them a
        # place that wants help, and five places within a few kilometres
        # of each other make one area.
        #
        # They are written by hand for the same reason ORPH and FLKY
        # are: the random traffic loop would give each of them one to
        # three real gateways and leave the whole neighbourhood looking
        # healthy. See `GAP_DEMO`.
        for member in GAP_CLUSTER:
            for hours_ago in range(0, 24):
                seen_at = NOW - timedelta(hours=hours_ago, minutes=11)
                hop_start = 3
                for _ in range(2):
                    gap_packet_id += 1
                    await conn.execute(
                        text(
                            """
                            INSERT INTO packet_key (from_node_num, packet_id, first_seen_at)
                            VALUES (:f, :p, :t) ON CONFLICT DO NOTHING
                            """
                        ),
                        {"f": member, "p": gap_packet_id, "t": seen_at},
                    )
                    await conn.execute(
                        text(
                            """
                            INSERT INTO packet (from_node_num, packet_id, to_node_num,
                                portnum, channel, hop_start, hop_limit, want_ack,
                                rx_time, first_seen_at)
                            VALUES (:f, :p, :to, :port, :ch, :hs, :hs, false, :rx, :t)
                            """
                        ),
                        {
                            "f": member,
                            "p": gap_packet_id,
                            "to": BROADCAST,
                            "port": PORT_TELEMETRY,
                            "ch": PRIMARY_PRESET,
                            "hs": hop_start,
                            "rx": int(seen_at.timestamp()),
                            "t": seen_at,
                        },
                    )
                    # Its own upload, and no other. Nothing on the air
                    # has heard any of them.
                    await conn.execute(
                        text(
                            """
                            INSERT INTO packet_seen (from_node_num, packet_id,
                                gateway_node_num, mqtt_topic, channel, rx_rssi, rx_snr,
                                hop_limit, seen_at)
                            VALUES (:f, :p, :f, :topic, :ch, -90, 6.75, :hs, :t)
                            ON CONFLICT DO NOTHING
                            """
                        ),
                        {
                            "f": member,
                            "p": gap_packet_id,
                            "topic": f"msh/US/AZ/2/e/{PRIMARY_PRESET}/" + node_id(member),
                            "ch": PRIMARY_PRESET,
                            "hs": hop_start,
                            "t": seen_at,
                        },
                    )

        # ORPH publishes neighbour reports of its own. A node that
        # publishes one of these proves its receiver works, which is one
        # of only two ways this database can ever prove that. Paired with
        # "no gateway heard it", that is the asymmetry the page reports.
        for hours_ago in range(0, 12, 3):
            t = NOW - timedelta(hours=hours_ago)
            for neighbour, snr in ((0x0A51A001, -6.5), (0x0A51A002, -11.0)):
                await conn.execute(
                    text(
                        """
                        INSERT INTO neighbor_metrics (node_num, neighbor_node_num,
                            channel, snr, last_rx_time,
                            node_broadcast_interval_secs, time)
                        VALUES (:a, :b, :ch, :snr, :t, 900, :t)
                        """
                    ),
                    {
                        "a": GAP_ISOLATED,
                        "b": neighbour,
                        "ch": PRIMARY_PRESET,
                        "snr": snr,
                        "t": t,
                    },
                )

        # Neighbour reports. Each link is reported from both ends.
        for hours_ago in range(0, 12, 2):
            t = NOW - timedelta(hours=hours_ago)
            for node, neighbor, snr in LINKS:
                for a, b in ((node, neighbor), (neighbor, node)):
                    await conn.execute(
                        text(
                            """
                            INSERT INTO neighbor_metrics (node_num,
                                neighbor_node_num, channel, snr, last_rx_time,
                                node_broadcast_interval_secs, time)
                            VALUES (:a, :b, 'LongFast', :snr, :t, 900, :t)
                            """
                        ),
                        {"a": a, "b": b, "snr": round(snr + RNG.uniform(-1.5, 1.5), 2), "t": t},
                    )

        # Traceroutes. Each one has a path through the routers.
        paths = [
            (0x0A51B001, 0x0A51B005, [0x0A51A001, 0x0A51A003]),
            (0x0A51B007, 0x0A51B004, [0x0A51A005, 0x0A51A004, 0x0A51A002, 0x0A51A001]),
            (0x0A51B002, 0x0A51B006, [0x0A51A002, 0x0A51A001, 0x0A51A003]),
            (0x0A51B008, 0x0A51B003, [0x0A51A004, 0x0A51A002, 0x0A51A001]),
            (0x0A51C001, 0x0A51B009, [0x0A51A002, 0x0A51A004, 0x0A51A005]),
        ]
        for index, (src, dst, route) in enumerate(paths):
            seen_at = NOW - timedelta(hours=index * 2 + 1)
            packet_id += 1
            await conn.execute(
                text(
                    """
                    INSERT INTO traceroute (packet_id, request_id, from_node_num,
                        to_node_num, channel, route, route_back, snr_towards,
                        snr_back, seen_at)
                    VALUES (:p, :req, :f, :to, 'LongFast', :route, :back,
                        :snrt, :snrb, :t)
                    """
                ),
                {
                    "p": packet_id,
                    "req": packet_id - 1,
                    "f": src,
                    "to": dst,
                    "route": f"[{','.join(str(r) for r in route)}]",
                    "back": f"[{','.join(str(r) for r in reversed(route))}]",
                    "snrt": "["
                    + ",".join(str(round(RNG.uniform(-8, 11), 2)) for _ in range(len(route) + 1))
                    + "]",
                    "snrb": "["
                    + ",".join(str(round(RNG.uniform(-8, 11), 2)) for _ in range(len(route) + 1))
                    + "]",
                    "t": seen_at,
                },
            )

        # Traceroutes to two routers, with the answers some of them got.
        #
        # The reachable leaderboard ranks a node by the share of
        # traceroutes sent to it that it answered (#293), and it ranks
        # only a node with at least 10 traceroutes from 2 or more
        # senders. The traces above are replies with no request, which
        # count for nothing, so without these the board is always empty.
        #
        # One router on each preset, because the board shows the preset
        # the menu has chosen. Every row is older than the newest trace
        # above, so `/api/traceroutes?limit=1` still opens a real path.
        # The route lists are empty: these rows evidence no hop, so the
        # map and the graph draw nothing new.
        asked_by = [0x0A51B001, 0x0A51B002, 0x0A51B003]
        for preset, target, answered in (
            (PRIMARY_PRESET, 0x0A51A002, 11),
            (SECONDARY_PRESET, 0x0A51A001, 9),
        ):
            for index in range(12):
                request = 700_000 + index + (0 if preset == PRIMARY_PRESET else 100)
                asker = asked_by[index % len(asked_by)]
                asked_at = NOW - timedelta(hours=2, minutes=index * 40)
                rows = [(request, None, asker, target, asked_at)]
                if index < answered:
                    rows.append(
                        (request + 1000, request, target, asker, asked_at + timedelta(seconds=20))
                    )
                for packet, answers, sender, receiver, at in rows:
                    await conn.execute(
                        text(
                            """
                            INSERT INTO traceroute (packet_id, request_id, from_node_num,
                                to_node_num, channel, route, route_back, snr_towards,
                                snr_back, seen_at)
                            VALUES (:p, :req, :f, :to, :ch, '[]', '[]', '[]', '[]', :t)
                            """
                        ),
                        {
                            "p": packet,
                            "req": answers,
                            "f": sender,
                            "to": receiver,
                            "ch": preset,
                            "t": at,
                        },
                    )

        # A tapback that several people sent.
        #
        # The chat page draws these as one chip listing every sender, and
        # with long node names that row is wide. On a 320px viewport a
        # real one measured 344px and took the whole page sideways,
        # failing WCAG 2.1 SC 1.4.10 Reflow. Nothing here produced a
        # reaction at all, so the fixture could never show it.
        #
        # Several senders, and the longest names in the set, because one
        # thumbs-up from one node would not have caught it either.
        reacted = await conn.execute(
            text(
                "SELECT packet_id, from_node_num FROM text_message "
                "WHERE emoji = false AND packet_id IS NOT NULL "
                "ORDER BY seen_at DESC LIMIT 1"
            )
        )
        parent = reacted.first()
        if parent is not None:
            senders = await conn.execute(
                text(
                    "SELECT node_num FROM node WHERE long_name IS NOT NULL "
                    "ORDER BY length(long_name) DESC LIMIT 5"
                )
            )
            for index, row in enumerate(senders):
                await conn.execute(
                    text(
                        """
                        INSERT INTO text_message (packet_id, from_node_num,
                            to_node_num, channel, body, emoji, reply_id, seen_at)
                        VALUES (:p, :f, :to, :ch, :body, true, :reply, :t)
                        """
                    ),
                    {
                        "p": 900_000 + index,
                        "f": row.node_num,
                        "to": BROADCAST,
                        "ch": PRIMARY_PRESET,
                        "body": "\U0001f44d",
                        "reply": parent.packet_id,
                        "t": NOW - timedelta(minutes=index + 1),
                    },
                )

        # Every upload and packet above, tagged as ingest would (#313).
        await tag_presets(conn, NOW - timedelta(days=30))
        await write_preset_messages(conn)

    async with engine.connect() as conn:
        for table in (
            "node",
            "packet",
            "packet_seen",
            "text_message",
            "device_metrics",
            "position_metrics",
            "environment_metrics",
            "neighbor_metrics",
            "traceroute",
        ):
            count = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            print(f"{table:22} {count:>7}")

    await engine.dispose()


# --- Live mode ------------------------------------------------------


def _burned(rng: random.Random) -> int:
    """Return how many hops one upload of a packet burned.

    Weighted so most observations are relayed. AGENTS.md 9.5 measured
    about 82 percent relayed against 5 percent direct on live traffic, and
    a preview where nearly every observation is direct draws nearly every
    line flat. Flatness is the map's claim that two radios heard each
    other, so a preview that makes everything flat hides the one
    distinction the geometry exists to draw.
    """
    return rng.choices([0, 1, 2, 3], weights=[1, 5, 7, 4])[0]


async def live() -> None:
    """Keep adding packets at the present moment, until interrupted.

    The seeded window is fixed at the moment the seed ran, so a few
    minutes later the map's live window is empty and the animation has
    nothing to draw. Worse, the front end only animates a packet it has
    not seen before, so even a full window animates nothing on a reload.
    Watching the animation at all therefore needs traffic that keeps
    arriving, and this is it.

    The fan-out follows the measurement in AGENTS.md 9.5.1 rather than the
    main seed's one to three: a packet goes to several gateways, and some
    of them upload it more than once, so a preview exercises the three-arc
    cap, the "+N" numeral, the distinct-gateway count against the upload
    count, and the dedupe that keeps a repeat upload from drawing a second
    stroke over the first.

    Run it beside the preview, never against production:

        SEED_DATABASE_URL=... uv run python tools/dev/seed.py --live
    """
    url = os.environ.get(
        "SEED_DATABASE_URL",
        "postgresql+asyncpg://postgres:devpassword@127.0.0.1:5432/azmsh",
    )
    every = float(os.environ.get("SEED_LIVE_INTERVAL", "1.5"))
    engine = create_async_engine(url)
    rng = random.Random()
    senders = [n[NUM] for n in NODES]

    async with engine.connect() as conn:
        packet_id = (
            await conn.execute(text("SELECT coalesce(max(packet_id), 500000) FROM packet"))
        ).scalar_one()

    print(f"==> live traffic every {every}s from packet id {packet_id}. Ctrl-C to stop.")
    while True:
        async with engine.begin() as conn:
            batch_start = datetime.now(UTC)
            for _ in range(rng.randint(1, 3)):
                packet_id += 1
                seen_at = datetime.now(UTC)
                sender = rng.choice(senders)
                portnum = rng.choices(
                    [
                        PORT_TEXT,
                        PORT_POSITION,
                        PORT_NODEINFO,
                        PORT_TELEMETRY,
                        PORT_TRACEROUTE,
                        PORT_NEIGHBORINFO,
                    ],
                    weights=[8, 30, 12, 30, 8, 12],
                )[0]
                channel = rng.choice(CHANNELS)
                hop_start = rng.choice([3, 3, 5, 7])
                await conn.execute(
                    text(
                        """
                        INSERT INTO packet_key (from_node_num, packet_id, first_seen_at)
                        VALUES (:f, :p, :t) ON CONFLICT DO NOTHING
                        """
                    ),
                    {"f": sender, "p": packet_id, "t": seen_at},
                )
                row = await conn.execute(
                    text(
                        """
                        INSERT INTO packet (from_node_num, packet_id, to_node_num,
                            portnum, channel, hop_start, hop_limit, want_ack,
                            rx_time, first_seen_at)
                        VALUES (:f, :p, :to, :port, :ch, :hs, :hl, false, :rx, :t)
                        RETURNING id
                        """
                    ),
                    {
                        "f": sender,
                        "p": packet_id,
                        "to": BROADCAST,
                        "port": portnum,
                        "ch": channel,
                        "hs": hop_start,
                        "hl": hop_start - rng.randint(0, 2),
                        "rx": int(seen_at.timestamp()),
                        "t": seen_at,
                    },
                )
                packet_pk = row.scalar_one()

                # A wide fan, and some gateways upload twice. One of them
                # is sometimes the sender itself, which is an upload of its
                # own voice and not a radio hop: the endpoint reports that
                # with `has_line` false, and the map draws it as a pulse
                # with no arc. See AGENTS.md 9.5.1.
                # Most observations are relayed. AGENTS.md 9.5 measured
                # about 82 percent relayed against 5 percent direct, and a
                # preview where every packet is direct draws every line
                # flat — which is exactly the distinction the new geometry
                # exists to make, so it would go unchecked.
                chosen = rng.sample(GATEWAYS, rng.randint(2, len(GATEWAYS)))
                uploads = [(gw[0], hop_start - _burned(rng)) for gw in chosen]
                for gateway_num, hop_limit in list(uploads):
                    if rng.random() < 0.3:
                        uploads.append((gateway_num, hop_limit))
                if rng.random() < 0.25:
                    uploads.append((sender, hop_start))
                for gateway_num, hop_limit in uploads:
                    await conn.execute(
                        text(
                            """
                            INSERT INTO packet_seen (packet_pk, from_node_num,
                                packet_id, gateway_node_num, mqtt_topic, channel,
                                rx_rssi, rx_snr, hop_limit, seen_at)
                            VALUES (:pk, :f, :p, :g, :topic, :ch, :rssi, :snr,
                                :hl, :t) ON CONFLICT DO NOTHING
                            """
                        ),
                        {
                            "pk": packet_pk,
                            "f": sender,
                            "p": packet_id,
                            "g": gateway_num,
                            "topic": f"msh/US/AZ/2/e/{channel}/{node_id(sender)}",
                            "ch": channel,
                            "rssi": rng.randint(-120, -60),
                            "snr": round(rng.uniform(-12, 12), 2),
                            "hl": hop_limit,
                            "t": datetime.now(UTC),
                        },
                    )

            # A traceroute now and then, on the preset the map opens on.
            #
            # It is a reply, so it carries `request_id`: the map asks for
            # completed traceroutes only, because an unanswered request's
            # hop list is not a path to the node that was asked and
            # drawing it claims a route nobody proved (AGENTS.md 9.18).
            #
            # The readings are quarter dB, and one hop in three is written
            # as INT8_MIN, which means "not measured" and not -32 dB
            # (AGENTS.md 9.6). Without those the stippled hop never draws,
            # and the stipple is how the map says a reading is missing.
            if rng.random() < 0.18:
                packet_id += 1
                route = [n[NUM] for n in rng.sample(GATEWAYS, rng.randint(1, 3))]
                ends = rng.sample([n[NUM] for n in NODES if n[NUM] not in route], 2)
                readings = [
                    UNMEASURED_SNR if rng.random() < 0.33 else rng.randint(-32, 44)
                    for _ in range(len(route) + 1)
                ]
                await conn.execute(
                    text(
                        """
                        INSERT INTO traceroute (packet_id, request_id, from_node_num,
                            to_node_num, channel, route, route_back, snr_towards,
                            snr_back, seen_at)
                        VALUES (:p, :req, :f, :to, :ch, :route, :back, :snrt, :snrb, :t)
                        """
                    ),
                    {
                        "p": packet_id,
                        "req": packet_id - 1,
                        "f": ends[0],
                        "to": ends[1],
                        "ch": PRIMARY_PRESET,
                        "route": f"[{','.join(str(r) for r in route)}]",
                        "back": f"[{','.join(str(r) for r in reversed(route))}]",
                        "snrt": f"[{','.join(str(v) for v in readings)}]",
                        "snrb": f"[{','.join(str(v) for v in readings)}]",
                        "t": datetime.now(UTC),
                    },
                )
            await tag_presets(conn, batch_start)
        await asyncio.sleep(every)


if __name__ == "__main__":
    asyncio.run(live() if "--live" in sys.argv else main())
