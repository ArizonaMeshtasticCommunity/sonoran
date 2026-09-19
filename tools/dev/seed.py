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
GAP_DEMO = (GAP_ISOLATED, GAP_INTERMITTENT)

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
        for table in (
            "neighbor_metrics",
            "position_metrics",
            "device_metrics",
            "environment_metrics",
            "text_message",
            "traceroute",
            "packet_seen",
            "packet",
            "packet_key",
            "node",
        ):
            await conn.execute(text(f"TRUNCATE {table}"))

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
            await conn.execute(
                text(
                    """
                    INSERT INTO node (node_num, node_id, long_name, short_name,
                        hw_model, role, is_licensed, last_lat, last_lon,
                        last_altitude, position_time, last_heard,
                        is_mqtt_gateway, last_mqtt_topic, last_channel,
                        first_seen, updated_at)
                    VALUES (:num, :nid, :long, :short, :hw, :role, false,
                        :lat, :lon, :alt, :ptime, :heard, :gw, :topic,
                        :node_channel, :first, :heard)
                    """
                ),
                {
                    "num": num,
                    "nid": node_id(num),
                    "long": long_name,
                    "short": short,
                    "hw": hw,
                    "role": role,
                    "lat": lat,
                    "lon": lon,
                    "alt": alt,
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
                    await conn.execute(
                        text(
                            """
                            INSERT INTO position_metrics (node_num, packet_pk,
                                packet_id, latitude, longitude, altitude,
                                sats_in_view, precision_bits, time)
                            VALUES (:n, :pk, :p, :lat, :lon, :alt, :sats, 32, :t)
                            """
                        ),
                        {
                            "n": sender,
                            "pk": packet_pk,
                            "p": packet_id,
                            "lat": src[LAT] + drift(src),
                            "lon": src[LON] + drift(src),
                            "alt": src[ALT],
                            "sats": RNG.randint(4, 12),
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
        await asyncio.sleep(every)


if __name__ == "__main__":
    asyncio.run(live() if "--live" in sys.argv else main())
