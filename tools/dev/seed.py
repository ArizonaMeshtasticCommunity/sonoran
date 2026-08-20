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

The script empties the tables before it fills them. You can run it
again as many times as you want.
"""

from __future__ import annotations

import asyncio
import os
import random
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
        False,
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
        False,
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
        False,
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
        False,
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
        False,
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
]

# The positions in a NODES row.
NUM, SHORT, LONG, HW, ROLE, LAT, LON, ALT, GATEWAY = range(9)

GATEWAYS = [n for n in NODES if n[GATEWAY]]

# The neighbour links, as (node, neighbour, snr).
LINKS = [
    (0x0A51A001, 0x0A51A002, 4.5),
    (0x0A51A001, 0x0A51B001, 8.25),
    (0x0A51A001, 0x0A51B003, 6.0),
    (0x0A51A001, 0x0A51B004, 7.75),
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

CHANNELS = ["LongFast", "LongFast", "LongFast", "azmsh", "MediumSlow", "AZ-Weather"]

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
                        'LongFast', :first, :heard)
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
                    "topic": "msh/US/AZ/2/e/LongFast/" + node_id(num),
                    "first": NOW - timedelta(days=RNG.randint(30, 400)),
                },
            )

        # Packets. Each packet gets one observation for each gateway
        # that heard it. See AGENTS.md 9.5.
        packet_id = 100_000
        senders = [n[NUM] for n in NODES]
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


if __name__ == "__main__":
    asyncio.run(main())
